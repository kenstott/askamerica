import { Env } from './types';

async function lookupKeyHash(env: Env, rawKey: string): Promise<string | null> {
  const enc = new TextEncoder();
  const buf = await crypto.subtle.digest('SHA-256', enc.encode(rawKey));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

export async function handleCredentials(request: Request, env: Env): Promise<Response> {
  const apiKey = request.headers.get('X-API-Key') || '';
  if (!apiKey) {
    return new Response(JSON.stringify({ error: 'missing_api_key' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  const keyHash = await lookupKeyHash(env, apiKey);
  const userId = await env.KEYS.get(keyHash);
  if (!userId) {
    return new Response(JSON.stringify({ error: 'invalid_api_key' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  // Return shared read-only R2 credentials.
  // All authenticated users share these read-only credentials.
  // Quota enforcement happens via self-reported metering.
  return new Response(
    JSON.stringify({
      access_key_id: env.R2_ACCESS_KEY_ID,
      secret_access_key: env.R2_SECRET_ACCESS_KEY,
      region: 'auto',
      endpoint: `https://${env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
      bucket: env.R2_BUCKET,
    }),
    { headers: { 'Content-Type': 'application/json' } },
  );
}
