import { Env } from './types';
import { resolveUser } from './quota';
import { stripe } from './stripe';

const SITE = 'https://askamerica.ai';

// One-time prepaid passes (Stripe one-time prices → checkout.session.completed webhook).
// Empty until such prices exist; fill with { price_id: bytes }.
export const PREPAID_PRICES: Record<string, number> = {};

/** Bytes granted by a one-time prepaid price (0 if the price isn't prepaid). */
export function prepaidBytesFor(priceId: string): number {
  return PREPAID_PRICES[priceId] ?? 0;
}

/**
 * Create a Stripe-hosted checkout for one plan, returning its URL. Stripe Managed Payments is
 * the merchant of record. user_id rides on the session and on the subscription it creates, so
 * every subscription event names the AskAmerica user.
 */
async function createCheckout(env: Env, priceId: string, userId: string): Promise<string | null> {
  const res = await stripe(env, 'POST', '/checkout/sessions', {
    'mode': 'subscription',
    'managed_payments[enabled]': 'true',
    'line_items[0][price]': priceId,
    'line_items[0][quantity]': '1',
    'metadata[user_id]': userId,
    'subscription_data[metadata][user_id]': userId,
    'success_url': `${SITE}/upgrade.html?paid=1`,
    'cancel_url': `${SITE}/upgrade.html`,
  });
  if (!res.ok) {
    return null;
  }
  const data = await res.json<{ url?: string }>();
  return data.url ?? null;
}

export async function handleCheckout(request: Request, env: Env): Promise<Response> {
  const apiKey = request.headers.get('X-API-Key');
  if (!apiKey) {
    return json({ error: 'unauthorized' }, 401);
  }
  const userId = await resolveUser(apiKey, env);
  if (!userId) {
    return json({ error: 'unauthorized' }, 401);
  }

  const [starter, pro] = await Promise.all([
    createCheckout(env, env.STRIPE_PRICE_STARTER, userId),
    createCheckout(env, env.STRIPE_PRICE_PRO, userId),
  ]);
  if (!starter || !pro) {
    return json({ error: 'checkout_unavailable' }, 502);
  }

  return json({
    starter: { price_usd: 19, quota_gb: 50,  checkout_url: starter },
    pro:     { price_usd: 99, quota_gb: 500, checkout_url: pro },
    prepaid: [],
  });
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
