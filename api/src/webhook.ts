import { Env, TIER_LIMITS, LS_VARIANT_TIERS } from './types';
import { prepaidBytesFor } from './checkout';

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

async function verifySignature(body: string, signature: string | null, env: Env): Promise<boolean> {
  if (!signature) return false;
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(env.LS_WEBHOOK_SECRET),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const mac = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(body));
  const expected = Array.from(new Uint8Array(mac)).map(b => b.toString(16).padStart(2, '0')).join('');
  return timingSafeEqual(signature, expected);
}

interface LSEvent {
  meta?: { event_name?: string; custom_data?: { user_id?: string } };
  data?: {
    id?: string | number;
    attributes?: {
      variant_id?: number;
      customer_id?: number;
      status?: string;
      first_subscription_item?: { subscription_id?: number };
      first_order_item?: { variant_id?: number };
    };
  };
}

export async function handleLemonSqueezyWebhook(request: Request, env: Env): Promise<Response> {
  const body = await request.text();
  if (!(await verifySignature(body, request.headers.get('X-Signature'), env))) {
    return new Response('Forbidden', { status: 403 });
  }

  let event: LSEvent;
  try {
    event = JSON.parse(body) as LSEvent;
  } catch {
    return new Response('Bad Request', { status: 400 });
  }

  const eventName = event.meta?.event_name ?? '';
  const userId = event.meta?.custom_data?.user_id;
  const attrs = event.data?.attributes ?? {};
  const dataId = String(event.data?.id ?? '');
  if (!userId) {
    return new Response('OK'); // no user context — nothing to attribute
  }

  try {
    switch (eventName) {
      // Grant while the subscription is paying; drop to free on any non-active state.
      case 'subscription_created':
      case 'subscription_updated': {
        const status = String(attrs.status ?? '');
        const active = status === 'active' || status === 'on_trial';
        const tier = active ? (LS_VARIANT_TIERS[String(attrs.variant_id ?? '')] ?? 'starter') : 'free';
        await applyTier(env, userId, tier,
          String(attrs.customer_id ?? ''),
          String(attrs.first_subscription_item?.subscription_id ?? ''));
        break;
      }

      // A cancelled subscription keeps access until it actually ends — downgrade on expiry/pause.
      case 'subscription_expired':
      case 'subscription_paused':
        await applyTier(env, userId, 'free', '', '');
        break;

      // One-time prepaid pass: credit the month's quota exactly once (idempotent on order id).
      case 'order_created': {
        const bytes = prepaidBytesFor(String(attrs.first_order_item?.variant_id ?? ''));
        if (bytes > 0 && dataId) {
          await creditPrepaidOnce(env, userId, dataId, bytes);
        }
        break;
      }

      // Claw back a refunded prepaid pass.
      case 'order_refunded':
        if (dataId) {
          await refundPrepaid(env, userId, dataId);
        }
        break;

      default:
        break; // ack unhandled events so LS stops retrying
    }
  } catch {
    // Signal failure so Lemon Squeezy retries. All writes above are idempotent, so a
    // retry re-applies safely (tier is set, not incremented; prepaid is deduped by order id).
    return new Response('error', { status: 500 });
  }

  return new Response('OK');
}

/** Set the user's tier and this period's quota limit; keep existing LS ids if not supplied. */
async function applyTier(env: Env, userId: string, tier: string,
    customerId: string, subscriptionId: string): Promise<void> {
  const limit = TIER_LIMITS[tier] ?? TIER_LIMITS['free'];
  const period = currentPeriod();
  await env.DB.prepare(
    `UPDATE users SET tier = ?,
       ls_customer_id = COALESCE(?, ls_customer_id),
       ls_subscription_id = COALESCE(?, ls_subscription_id)
     WHERE id = ?`
  ).bind(tier, customerId || null, subscriptionId || null, userId).run();
  await env.DB.prepare(
    `INSERT INTO quota_periods (user_id, period, limit_bytes, used_bytes) VALUES (?, ?, ?, 0)
     ON CONFLICT(user_id, period) DO UPDATE SET limit_bytes = excluded.limit_bytes`
  ).bind(userId, period, limit).run();
  await env.QUOTA.delete(`${userId}:${period}`);
}

/** Credit prepaid bytes to the current period once per order (dedupes LS webhook retries). */
async function creditPrepaidOnce(env: Env, userId: string, orderId: string, bytes: number): Promise<void> {
  const period = currentPeriod();
  const res = await env.DB.prepare(
    `INSERT OR IGNORE INTO ls_orders (order_id, user_id, bytes, period, refunded) VALUES (?, ?, ?, ?, 0)`
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

/** Reverse a prepaid credit when its order is refunded (once). */
async function refundPrepaid(env: Env, userId: string, orderId: string): Promise<void> {
  const row = await env.DB.prepare(
    `SELECT bytes, period, refunded FROM ls_orders WHERE order_id = ?`
  ).bind(orderId).first<{ bytes: number; period: string; refunded: number }>();
  if (!row || row.refunded) {
    return;
  }
  await env.DB.prepare(`UPDATE ls_orders SET refunded = 1 WHERE order_id = ?`).bind(orderId).run();
  await env.DB.prepare(
    `UPDATE quota_periods SET limit_bytes = MAX(0, limit_bytes - ?) WHERE user_id = ? AND period = ?`
  ).bind(row.bytes, userId, row.period).run();
  await env.QUOTA.delete(`${userId}:${row.period}`);
}
