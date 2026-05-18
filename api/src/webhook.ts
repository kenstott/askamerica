import { Env, TIER_LIMITS, LS_VARIANT_TIERS } from './types';

async function verifyLemonSqueezySignature(request: Request, env: Env): Promise<boolean> {
  const signature = request.headers.get('X-Signature');
  if (!signature) return false;

  const body = await request.text();
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(env.LS_WEBHOOK_SECRET),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );
  const mac = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(body));
  const expected = Array.from(new Uint8Array(mac)).map(b => b.toString(16).padStart(2, '0')).join('');
  return signature === expected;
}

export async function handleLemonSqueezyWebhook(request: Request, env: Env): Promise<Response> {
  const cloned = request.clone();
  const valid = await verifyLemonSqueezySignature(cloned, env);
  if (!valid) return new Response('Forbidden', { status: 403 });

  const event = await request.json<{
    meta: { event_name: string; custom_data?: { user_id?: string } };
    data: {
      attributes: {
        variant_id:      number;
        customer_id:     number;
        status:          string;
        first_subscription_item?: { subscription_id: number };
      };
    };
  }>();

  const eventName = event.meta.event_name;
  const userId    = event.meta.custom_data?.user_id;
  if (!userId) return new Response('OK'); // ignore events without user context

  const variantId     = String(event.data.attributes.variant_id);
  const customerId    = String(event.data.attributes.customer_id);
  const subscriptionId = String(event.data.attributes.first_subscription_item?.subscription_id ?? '');
  const tier          = LS_VARIANT_TIERS[variantId] ?? 'starter';
  const limitBytes    = TIER_LIMITS[tier] ?? TIER_LIMITS['starter'];

  if (eventName === 'subscription_created' || eventName === 'subscription_updated') {
    await env.DB.prepare(`
      UPDATE users SET tier = ?, ls_customer_id = ?, ls_subscription_id = ? WHERE id = ?
    `).bind(tier, customerId, subscriptionId, userId).run();

    // update current period quota limit
    const d = new Date();
    const period = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
    await env.DB.prepare(`
      INSERT INTO quota_periods (user_id, period, limit_bytes, used_bytes) VALUES (?, ?, ?, 0)
      ON CONFLICT(user_id, period) DO UPDATE SET limit_bytes = excluded.limit_bytes
    `).bind(userId, period, limitBytes).run();

    // invalidate KV quota cache
    await env.QUOTA.delete(`${userId}:${period}`);
  }

  if (eventName === 'subscription_cancelled') {
    await env.DB.prepare(
      'UPDATE users SET tier = ? WHERE id = ?'
    ).bind('free', userId).run();
  }

  return new Response('OK');
}
