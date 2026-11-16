import { Env } from './types';

const API = 'https://api.stripe.com/v1';
// Pinned so a change to the account's default version cannot change payload shapes under us.
const VERSION = '2026-08-26.dahlia';

/** Call the Stripe REST API (form-encoded). Returns the response; the caller decides on !ok. */
export function stripe(env: Env, method: 'GET' | 'POST', path: string,
    form?: Record<string, string>): Promise<Response> {
  return fetch(`${API}${path}`, {
    method,
    headers: {
      'Authorization': `Bearer ${env.STRIPE_SECRET_KEY}`,
      'Stripe-Version': VERSION,
      ...(form ? { 'Content-Type': 'application/x-www-form-urlencoded' } : {}),
    },
    body: form ? new URLSearchParams(form).toString() : undefined,
  });
}

/** The tier a Stripe price sells, or null when the price is not one of AskAmerica's plans. */
export function tierForPrice(env: Env, priceId: string): string | null {
  if (priceId === env.STRIPE_PRICE_STARTER) return 'starter';
  if (priceId === env.STRIPE_PRICE_PRO) return 'pro';
  return null;
}
