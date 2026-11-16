import { env, fetchMock } from 'cloudflare:test';
import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import { handleQuotaStatus, handleUsageReport } from '../src/metering';
import { handleStripeWebhook } from '../src/webhook';
import { handleCheckout, PREPAID_PRICES } from '../src/checkout';

const GiB = 1024 * 1024 * 1024;
const E = env as any;

// ── helpers ──────────────────────────────────────────────────────────────────
async function sha256hex(s: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}

let seq = 0;
async function seedUser(tier = 'free', limitBytes = 1 * GiB) {
  const email = `u${seq++}@test.dev`;
  const userId = await sha256hex(email.toLowerCase());
  const apiKey = `aa_test_${userId.slice(0, 12)}`;
  const keyHash = await sha256hex(apiKey);
  const period = new Date().toISOString().slice(0, 7);
  await E.DB.prepare('INSERT OR REPLACE INTO users (id,email,created_at,tier) VALUES (?,?,?,?)')
    .bind(userId, email, Date.now(), tier).run();
  await E.DB.prepare('INSERT OR REPLACE INTO api_keys (key_hash,user_id,created_at) VALUES (?,?,?)')
    .bind(keyHash, userId, Date.now()).run();
  await E.KEYS.put(keyHash, userId);
  await E.DB.prepare('INSERT OR REPLACE INTO quota_periods (user_id,period,limit_bytes,used_bytes) VALUES (?,?,?,0)')
    .bind(userId, period, limitBytes).run();
  return { email, userId, apiKey, period };
}

async function meter(apiKey: string, bytes: number) {
  const r = await handleUsageReport(new Request('http://x/v1/metering/usage', {
    method: 'POST',
    headers: { 'X-API-Key': apiKey, 'Content-Type': 'application/json' },
    body: JSON.stringify({ query_id: 'q', table: 't', actual_bytes: bytes, planned_bytes: 0, row_count: 1, duration_ms: 1, query_text: 'x' }),
  }), env);
  expect(r.status).toBe(200);
}

async function quota(apiKey: string): Promise<any> {
  const r = await handleQuotaStatus(new Request('http://x/v1/quota', { headers: { 'X-API-Key': apiKey } }), env);
  return r.json();
}

const NOW = Math.floor(Date.now() / 1000);

async function sign(body: string, t = NOW): Promise<string> {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode('test-webhook-secret'),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const mac = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(`${t}.${body}`));
  const hex = [...new Uint8Array(mac)].map(b => b.toString(16).padStart(2, '0')).join('');
  return `t=${t},v1=${hex}`;
}

async function webhook(payload: Record<string, unknown>, signature?: string): Promise<Response> {
  const body = JSON.stringify(payload);
  return handleStripeWebhook(new Request('http://x/v1/webhooks/stripe', {
    method: 'POST',
    headers: { 'Stripe-Signature': signature ?? await sign(body), 'Content-Type': 'application/json' },
    body,
  }), env);
}

/** A Stripe subscription event for one of our prices (or any price), as Stripe shapes it. */
function subEvent(type: string, price: string, status: string, userId?: string, customer = 'cus_1') {
  return {
    type: `customer.subscription.${type}`,
    data: { object: {
      id: 'sub_1', customer, status,
      metadata: userId ? { user_id: userId } : {},
      items: { data: [{ price: { id: price } }] },
    } },
  };
}

beforeAll(() => { fetchMock.activate(); fetchMock.disableNetConnect(); });
afterEach(() => fetchMock.assertNoPendingInterceptors());

// ── tests ────────────────────────────────────────────────────────────────────
describe('metered consumption', () => {
  it('accrues usage and reports remaining', async () => {
    const { apiKey } = await seedUser();
    await meter(apiKey, 200 * 1024 * 1024);
    const q = await quota(apiKey);
    expect(q.tier).toBe('free');
    expect(q.used_bytes).toBe(200 * 1024 * 1024);
    expect(q.remaining_bytes).toBe(1 * GiB - 200 * 1024 * 1024);
  });

  it('accumulates across multiple reports', async () => {
    const { apiKey } = await seedUser();
    await meter(apiKey, 100 * 1024 * 1024);
    await meter(apiKey, 150 * 1024 * 1024);
    const q = await quota(apiKey);
    expect(q.used_bytes).toBe(250 * 1024 * 1024);
  });

  it('goes to zero/negative remaining when out of data', async () => {
    const { apiKey } = await seedUser();
    await meter(apiKey, 2 * GiB);
    const q = await quota(apiKey);
    expect(q.remaining_bytes).toBeLessThanOrEqual(0);
    expect(q.upgrade_url).toContain('/upgrade');
  });
});

describe('subscription lifecycle', () => {
  it('upgrade raises the limit and preserves used_bytes', async () => {
    const { apiKey, userId } = await seedUser();
    await meter(apiKey, 300 * 1024 * 1024);
    const r = await webhook(subEvent('updated', 'price_test_starter', 'active', userId));
    expect(r.status).toBe(200);
    const q = await quota(apiKey);
    expect(q.tier).toBe('starter');
    expect(q.limit_bytes).toBe(50 * GiB);
    expect(q.used_bytes).toBe(300 * 1024 * 1024);           // preserved
    expect(q.remaining_bytes).toBe(50 * GiB - 300 * 1024 * 1024);
    const row = await E.DB.prepare('SELECT stripe_customer_id c, stripe_subscription_id s FROM users WHERE id = ?')
      .bind(userId).first();
    expect(row).toEqual({ c: 'cus_1', s: 'sub_1' });
  });

  it('grants on subscription created, and while trialing', async () => {
    const { apiKey, userId } = await seedUser();
    await webhook(subEvent('created', 'price_test_pro', 'trialing', userId));
    expect((await quota(apiKey)).tier).toBe('pro');
  });

  it('does NOT grant on a non-active status (past_due)', async () => {
    const { apiKey, userId } = await seedUser('starter', 50 * GiB);
    await webhook(subEvent('updated', 'price_test_starter', 'past_due', userId));
    expect((await quota(apiKey)).tier).toBe('free');
  });

  it('downgrades to free when the subscription is deleted', async () => {
    const { apiKey, userId } = await seedUser('starter', 50 * GiB);
    await webhook(subEvent('deleted', 'price_test_starter', 'canceled', userId));
    expect((await quota(apiKey)).tier).toBe('free');
  });

  it('keeps the plan while a cancelled subscription is still active', async () => {
    const { apiKey, userId } = await seedUser('starter', 50 * GiB);
    const ev = subEvent('updated', 'price_test_starter', 'active', userId);
    (ev.data.object as any).cancel_at_period_end = true;
    await webhook(ev);
    expect((await quota(apiKey)).tier).toBe('starter');
  });

  it('derives user_id from the Stripe customer email when metadata is absent', async () => {
    const { apiKey, email } = await seedUser();
    fetchMock.get('https://api.stripe.com').intercept({ path: '/v1/customers/cus_mail' })
      .reply(200, { id: 'cus_mail', email: email.toUpperCase() });
    const r = await webhook(subEvent('updated', 'price_test_pro', 'active', undefined, 'cus_mail'));
    expect(r.status).toBe(200);
    expect((await quota(apiKey)).tier).toBe('pro');
  });

  it("ignores another product's subscription: no grant, no downgrade, no customer lookup", async () => {
    const paid = await seedUser('pro', 500 * GiB);
    const free = await seedUser();
    // The same account sells other subscriptions; these name our users but not our prices.
    expect((await webhook(subEvent('deleted', 'price_other_product', 'canceled', paid.userId))).status).toBe(200);
    expect((await webhook(subEvent('updated', 'price_other_product', 'active', free.userId))).status).toBe(200);
    expect((await webhook(subEvent('updated', 'price_other_product', 'active', undefined, 'cus_x'))).status).toBe(200);
    expect((await quota(paid.apiKey)).tier).toBe('pro');
    expect((await quota(free.apiKey)).tier).toBe('free');
  });

  it('asks Stripe to retry when the customer lookup fails', async () => {
    fetchMock.get('https://api.stripe.com').intercept({ path: '/v1/customers/cus_down' }).reply(500, {});
    const r = await webhook(subEvent('updated', 'price_test_pro', 'active', undefined, 'cus_down'));
    expect(r.status).toBe(500);
  });

  it('rejects a webhook with a bad signature, a malformed one, or one signed for another body', async () => {
    const ev = subEvent('updated', 'price_test_pro', 'active', 'u');
    expect((await webhook(ev, 't=1,v1=deadbeef')).status).toBe(403);
    expect((await webhook(ev, 'garbage')).status).toBe(403);
    expect((await webhook(ev, await sign('{"other":"body"}'))).status).toBe(403);
  });
});

describe('prepaid passes', () => {
  const session = (userId: string, pi: string) => ({
    type: 'checkout.session.completed',
    data: { object: { mode: 'payment', payment_status: 'paid', payment_intent: pi,
      metadata: { user_id: userId, price_id: 'price_test_pass' } } },
  });

  it('credits a paid pass once, and a refund takes it back once', async () => {
    PREPAID_PRICES['price_test_pass'] = 10 * GiB;
    try {
      const { apiKey, userId } = await seedUser();
      await webhook(session(userId, 'pi_1'));
      await webhook(session(userId, 'pi_1'));                 // Stripe retry
      expect((await quota(apiKey)).limit_bytes).toBe(11 * GiB);
      const refund = { type: 'charge.refunded', data: { object: { payment_intent: 'pi_1' } } };
      await webhook(refund);
      await webhook(refund);
      expect((await quota(apiKey)).limit_bytes).toBe(1 * GiB);
    } finally {
      delete PREPAID_PRICES['price_test_pass'];
    }
  });

  it("ignores a paid session for a price that is not a pass, and a refund of someone else's charge", async () => {
    const { apiKey, userId } = await seedUser();
    await webhook(session(userId, 'pi_2'));                   // price_test_pass is not configured
    await webhook({ type: 'charge.refunded', data: { object: { payment_intent: 'pi_unknown' } } });
    expect((await quota(apiKey)).limit_bytes).toBe(1 * GiB);
  });
});

describe('checkout', () => {
  it('opens a Managed Payments subscription checkout per plan, carrying the user on both objects', async () => {
    const { apiKey, userId } = await seedUser();
    const seen: URLSearchParams[] = [];
    fetchMock.get('https://api.stripe.com')
      .intercept({ path: '/v1/checkout/sessions', method: 'POST' })
      .reply(200, (req) => {
        const form = new URLSearchParams(String(req.body));
        seen.push(form);
        return { url: `https://checkout.stripe.com/c/pay/${form.get('line_items[0][price]')}` };
      }).times(2);
    const r = await handleCheckout(new Request('http://x/v1/checkout', { headers: { 'X-API-Key': apiKey } }), env);
    expect(r.status).toBe(200);
    const body: any = await r.json();
    expect(body.starter).toEqual({ price_usd: 19, quota_gb: 50, checkout_url: 'https://checkout.stripe.com/c/pay/price_test_starter' });
    expect(body.pro.checkout_url).toBe('https://checkout.stripe.com/c/pay/price_test_pro');
    expect(seen.length).toBe(2);
    for (const form of seen) {
      expect(form.get('mode')).toBe('subscription');
      expect(form.get('managed_payments[enabled]')).toBe('true');
      expect(form.get('metadata[user_id]')).toBe(userId);
      expect(form.get('subscription_data[metadata][user_id]')).toBe(userId);
    }
  });

  it('answers 502 when Stripe refuses a checkout, and 401 without a valid key', async () => {
    const { apiKey } = await seedUser();
    fetchMock.get('https://api.stripe.com')
      .intercept({ path: '/v1/checkout/sessions', method: 'POST' }).reply(400, { error: {} }).times(2);
    const r = await handleCheckout(new Request('http://x/v1/checkout', { headers: { 'X-API-Key': apiKey } }), env);
    expect(r.status).toBe(502);
    expect((await handleCheckout(new Request('http://x/v1/checkout'), env)).status).toBe(401);
    expect((await handleCheckout(new Request('http://x/v1/checkout', { headers: { 'X-API-Key': 'nope' } }), env)).status).toBe(401);
  });
});
