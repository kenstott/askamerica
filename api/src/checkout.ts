import { Env } from './types';
import { resolveUser } from './quota';

const LS_STORE = 'simpleishard.lemonsqueezy.com';

const VARIANT_IDS: Record<string, string> = {
  starter: '1285257',
  pro:     '1667060',
};

const GiB = 1024 * 1024 * 1024;

// One-time prepaid passes: buy a month of quota up front, no subscription. These
// are Lemon Squeezy *one-time* products, so they arrive as `order_created` webhooks
// (see webhook.ts). Fill in the real variant ids from your LS dashboard.
const PREPAID_VARIANTS: Record<string, { gb: number; price_usd: number; bytes: number }> = {
  // '0000001': { gb: 50,  price_usd: 15, bytes: 50  * GiB },
  // '0000002': { gb: 500, price_usd: 90, bytes: 500 * GiB },
};

/** Bytes granted by a one-time prepaid variant (0 if the variant isn't prepaid). */
export function prepaidBytesFor(variantId: string): number {
  return PREPAID_VARIANTS[variantId]?.bytes ?? 0;
}

function checkoutUrl(variantId: string, userId: string): string {
  const base = `https://${LS_STORE}/buy/${variantId}`;
  return `${base}?checkout[custom][user_id]=${encodeURIComponent(userId)}`;
}

export async function handleCheckout(request: Request, env: Env): Promise<Response> {
  const apiKey = request.headers.get('X-API-Key');
  if (!apiKey) return json({ error: 'unauthorized' }, 401);

  const userId = await resolveUser(apiKey, env);
  if (!userId) return json({ error: 'unauthorized' }, 401);

  const prepaid = Object.entries(PREPAID_VARIANTS).map(([variantId, p]) => ({
    quota_gb:     p.gb,
    price_usd:    p.price_usd,
    one_time:     true,
    checkout_url: checkoutUrl(variantId, userId),
  }));

  return json({
    starter: {
      price_usd:    19,
      quota_gb:     50,
      checkout_url: checkoutUrl(VARIANT_IDS.starter, userId),
    },
    pro: {
      price_usd:    99,
      quota_gb:     500,
      checkout_url: checkoutUrl(VARIANT_IDS.pro, userId),
    },
    prepaid,
  });
}

export function upgradeUrl(variantId: string, userId: string): string {
  return checkoutUrl(variantId, userId);
}

export { VARIANT_IDS, LS_STORE };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
