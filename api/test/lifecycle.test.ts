import { env } from 'cloudflare:test';
import { describe, it, expect } from 'vitest';
import { handleQuotaStatus, handleUsageReport } from '../src/metering';
import { handleLemonSqueezyWebhook } from '../src/webhook';

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

async function sign(body: string): Promise<string> {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode('test-webhook-secret'),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const mac = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(body));
  return [...new Uint8Array(mac)].map(b => b.toString(16).padStart(2, '0')).join('');
}

async function webhook(payload: object, signature?: string): Promise<Response> {
  const body = JSON.stringify(payload);
  return handleLemonSqueezyWebhook(new Request('http://x/v1/webhooks/lemonsqueezy', {
    method: 'POST',
    headers: { 'X-Signature': signature ?? await sign(body), 'Content-Type': 'application/json' },
    body,
  }), env);
}

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
    const r = await webhook({
      meta: { event_name: 'subscription_updated', custom_data: { user_id: userId } },
      data: { id: 's1', attributes: { status: 'active', variant_id: 1934204, customer_id: 1, first_subscription_item: { subscription_id: 1 } } },
    });
    expect(r.status).toBe(200);
    const q = await quota(apiKey);
    expect(q.tier).toBe('starter');
    expect(q.limit_bytes).toBe(50 * GiB);
    expect(q.used_bytes).toBe(300 * 1024 * 1024);           // preserved
    expect(q.remaining_bytes).toBe(50 * GiB - 300 * 1024 * 1024);
  });

  it('does NOT grant on a non-active status (past_due)', async () => {
    const { apiKey, userId } = await seedUser('starter', 50 * GiB);
    await webhook({
      meta: { event_name: 'subscription_updated', custom_data: { user_id: userId } },
      data: { id: 's', attributes: { status: 'past_due', variant_id: 1934204 } },
    });
    expect((await quota(apiKey)).tier).toBe('free');
  });

  it('downgrades to free on subscription_expired', async () => {
    const { apiKey, userId } = await seedUser('starter', 50 * GiB);
    await webhook({
      meta: { event_name: 'subscription_expired', custom_data: { user_id: userId } },
      data: { id: 's', attributes: {} },
    });
    expect((await quota(apiKey)).tier).toBe('free');
  });

  it('derives user_id from email when custom_data is absent', async () => {
    const { apiKey, email } = await seedUser();
    const r = await webhook({
      meta: { event_name: 'subscription_updated' },
      data: { id: 's', attributes: { status: 'active', variant_id: 1934205, user_email: email.toUpperCase() } },
    });
    expect(r.status).toBe(200);
    expect((await quota(apiKey)).tier).toBe('pro');          // 1934205 = pro
  });

  it('rejects a webhook with a bad signature', async () => {
    const r = await webhook({ meta: { event_name: 'subscription_updated' }, data: {} }, 'deadbeef');
    expect(r.status).toBe(403);
  });
});
