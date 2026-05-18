import { Env } from './types';
import { resolveUser } from './quota';

const LS_STORE = 'simpleishard.lemonsqueezy.com';

const VARIANT_IDS: Record<string, string> = {
  starter: '1285257',
  pro:     '1667060',
};

function checkoutUrl(variantId: string, userId: string): string {
  const base = `https://${LS_STORE}/buy/${variantId}`;
  return `${base}?checkout[custom][user_id]=${encodeURIComponent(userId)}`;
}

export async function handleCheckout(request: Request, env: Env): Promise<Response> {
  const apiKey = request.headers.get('X-API-Key');
  if (!apiKey) return json({ error: 'unauthorized' }, 401);

  const userId = await resolveUser(apiKey, env);
  if (!userId) return json({ error: 'unauthorized' }, 401);

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
