import { Env } from './types';
import { resolveUser } from './quota';

const STORE_ID = '285474';

// Checkout variant ids. These are the TEST ids while we validate billing —
// swap to the live ids at launch (live: starter 1285257, pro 1667060), and
// point the Worker's LEMONSQUEEZY_API_KEY at the live key.
const CHECKOUT_VARIANTS: Record<string, string> = {
  starter: '1934204',
  pro:     '1934205',
};

// One-time prepaid passes (LS single-payment products → order_created webhook).
// Empty until such products exist; fill with { variant_id: bytes }.
const PREPAID_VARIANTS: Record<string, number> = {};

/** Bytes granted by a one-time prepaid variant (0 if the variant isn't prepaid). */
export function prepaidBytesFor(variantId: string): number {
  return PREPAID_VARIANTS[variantId] ?? 0;
}

/** Create a hosted checkout via the LS API, returning its URL (custom.user_id baked in). */
async function createCheckout(env: Env, variantId: string, userId: string): Promise<string | null> {
  const res = await fetch('https://api.lemonsqueezy.com/v1/checkouts', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.LEMONSQUEEZY_API_KEY}`,
      'Content-Type': 'application/vnd.api+json',
      'Accept': 'application/vnd.api+json',
    },
    body: JSON.stringify({
      data: {
        type: 'checkouts',
        attributes: { checkout_data: { custom: { user_id: userId } } },
        relationships: {
          store:   { data: { type: 'stores', id: STORE_ID } },
          variant: { data: { type: 'variants', id: variantId } },
        },
      },
    }),
  });
  if (!res.ok) {
    return null;
  }
  const data = await res.json<{ data?: { attributes?: { url?: string } } }>();
  return data?.data?.attributes?.url ?? null;
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
    createCheckout(env, CHECKOUT_VARIANTS.starter, userId),
    createCheckout(env, CHECKOUT_VARIANTS.pro, userId),
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
