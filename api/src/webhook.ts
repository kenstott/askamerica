import { Env, TIER_LIMITS } from './types';
import { prepaidBytesFor } from './checkout';
import { stripe, tierForPrice } from './stripe';

function currentPeriod(): string {
  const d = new Date();
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

/**
 * Verify a Stripe webhook: the Stripe-Signature header carries `t=<unix>,v1=<hex>[,v1=...]`,
 * and v1 is HMAC-SHA256 over `<t>.<raw body>` keyed by the endpoint's signing secret.
 */
async function verifySignature(body: string, header: string | null, env: Env): Promise<boolean> {
  if (!header) return false;
  const parts = header.split(',').map(p => p.trim().split('='));
  const t = parts.find(([k]) => k === 't')?.[1];
  const candidates = parts.filter(([k]) => k === 'v1').map(([, v]) => v);
  if (!t || !candidates.length) return false;
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(env.STRIPE_WEBHOOK_SECRET),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const mac = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(`${t}.${body}`));
  const expected = Array.from(new Uint8Array(mac)).map(b => b.toString(16).padStart(2, '0')).join('');
  return candidates.some(c => timingSafeEqual(c, expected));
}

interface StripeEvent {
  type?: string;
  data?: { object?: Record<string, any> };
}

async function sha256hex(input: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Connect a subscription to an AskAmerica user: the explicit metadata.user_id from our
 * /upgrade flow, else the buyer's email read from the Stripe customer (user_id = sha256(email)).
 */
async function userForSubscription(env: Env, sub: Record<string, any>): Promise<string | null> {
  const explicit = sub.metadata?.user_id;
  if (explicit) return String(explicit);
  if (!sub.customer) return null;
  const res = await stripe(env, 'GET', `/customers/${sub.customer}`);
  if (!res.ok) throw new Error(`Stripe answered ${res.status} for customer ${sub.customer}`);
  const customer = await res.json<{ email?: string | null }>();
  return customer.email ? sha256hex(customer.email.toLowerCase()) : null;
}

export async function handleStripeWebhook(request: Request, env: Env): Promise<Response> {
  const body = await request.text();
  if (!(await verifySignature(body, request.headers.get('Stripe-Signature'), env))) {
    return new Response('Forbidden', { status: 403 });
  }

  let event: StripeEvent;
  try {
    event = JSON.parse(body) as StripeEvent;
  } catch {
    return new Response('Bad Request', { status: 400 });
  }

  const type = event.type ?? '';
  const obj = event.data?.object ?? {};

  try {
    switch (type) {
      // Grant while the subscription is paying; drop to free on any non-active state.
      // A cancelled subscription stays `active` until its period ends, then Stripe deletes it.
      case 'customer.subscription.created':
      case 'customer.subscription.updated':
      case 'customer.subscription.deleted': {
        // The Stripe account sells other products too. A subscription whose price is not an
        // AskAmerica plan is not ours: ack it and change nothing.
        const plan = tierForPrice(env, String(obj.items?.data?.[0]?.price?.id ?? ''));
        if (!plan) break;
        const userId = await userForSubscription(env, obj);
        if (!userId) break; // no user context — nothing to attribute
        const active = type !== 'customer.subscription.deleted'
          && (obj.status === 'active' || obj.status === 'trialing');
        await applyTier(env, userId, active ? plan : 'free',
          String(obj.customer ?? ''), String(obj.id ?? ''));
        break;
      }

      // One-time prepaid pass: credit the month's quota exactly once (idempotent on the
      // payment intent, which is also what a later refund names).
      case 'checkout.session.completed': {
        const bytes = prepaidBytesFor(String(obj.metadata?.price_id ?? ''));
        const userId = obj.metadata?.user_id;
        if (obj.mode === 'payment' && obj.payment_status === 'paid' && bytes > 0
            && userId && obj.payment_intent) {
          await creditPrepaidOnce(env, String(userId), String(obj.payment_intent), bytes);
        }
        break;
      }

      // Claw back a refunded prepaid pass.
      case 'charge.refunded':
        if (obj.payment_intent) {
          await refundPrepaid(env, String(obj.payment_intent));
        }
        break;

      default:
        break; // ack unhandled events so Stripe stops retrying
    }
  } catch {
    // Signal failure so Stripe retries. All writes above are idempotent, so a retry
    // re-applies safely (tier is set, not incremented; prepaid is deduped by payment intent).
    return new Response('error', { status: 500 });
  }

  return new Response('OK');
}

/** Set the user's tier and this period's quota limit; keep existing Stripe ids if not supplied. */
async function applyTier(env: Env, userId: string, tier: string,
    customerId: string, subscriptionId: string): Promise<void> {
  const limit = TIER_LIMITS[tier] ?? TIER_LIMITS['free'];
  const period = currentPeriod();
  await env.DB.prepare(
    `UPDATE users SET tier = ?,
       stripe_customer_id = COALESCE(?, stripe_customer_id),
       stripe_subscription_id = COALESCE(?, stripe_subscription_id)
     WHERE id = ?`
  ).bind(tier, customerId || null, subscriptionId || null, userId).run();
  await env.DB.prepare(
    `INSERT INTO quota_periods (user_id, period, limit_bytes, used_bytes) VALUES (?, ?, ?, 0)
     ON CONFLICT(user_id, period) DO UPDATE SET limit_bytes = excluded.limit_bytes`
  ).bind(userId, period, limit).run();
  await env.QUOTA.delete(`${userId}:${period}`);
}

/** Credit prepaid bytes to the current period once per order (dedupes webhook retries). */
async function creditPrepaidOnce(env: Env, userId: string, orderId: string, bytes: number): Promise<void> {
  const period = currentPeriod();
  const res = await env.DB.prepare(
    `INSERT OR IGNORE INTO prepaid_orders (order_id, user_id, bytes, period, refunded) VALUES (?, ?, ?, ?, 0)`
  ).bind(orderId, userId, bytes, period).run();
  if (!res.meta.changes) {
    return; // already processed this order
  }
  await env.DB.prepare(
    `INSERT INTO quota_periods (user_id, period, limit_bytes, used_bytes) VALUES (?, ?, ?, 0)
     ON CONFLICT(user_id, period) DO UPDATE SET limit_bytes = limit_bytes + excluded.limit_bytes`
  ).bind(userId, period, bytes).run();
  await env.QUOTA.delete(`${userId}:${period}`);
}

/** Reverse a prepaid credit when its order is refunded (once). Not ours if it has no ledger row. */
async function refundPrepaid(env: Env, orderId: string): Promise<void> {
  const row = await env.DB.prepare(
    `SELECT user_id, bytes, period, refunded FROM prepaid_orders WHERE order_id = ?`
  ).bind(orderId).first<{ user_id: string; bytes: number; period: string; refunded: number }>();
  if (!row || row.refunded) {
    return;
  }
  await env.DB.prepare(`UPDATE prepaid_orders SET refunded = 1 WHERE order_id = ?`).bind(orderId).run();
  await env.DB.prepare(
    `UPDATE quota_periods SET limit_bytes = MAX(0, limit_bytes - ?) WHERE user_id = ? AND period = ?`
  ).bind(row.bytes, row.user_id, row.period).run();
  await env.QUOTA.delete(`${row.user_id}:${row.period}`);
}
