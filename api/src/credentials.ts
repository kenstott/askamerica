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
    return json({ error: 'invalid_api_key' }, 401);
  }

  // Mint short-lived, read-only, bucket-scoped R2 credentials for this user.
  // Per-user + expiring + revocable: disabling the key stops future mints, and
  // any live credential dies within the TTL. The parent secret is never shipped.
  const ttlSeconds = 3600;
  const res = await fetch(
    `https://api.cloudflare.com/client/v4/accounts/${env.R2_ACCOUNT_ID}/r2/temp-access-credentials`,
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${env.R2_TEMP_TOKEN}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        bucket: env.R2_BUCKET,
        parentAccessKeyId: env.R2_ACCESS_KEY_ID,
        permission: 'object-read-only',
        ttlSeconds,
      }),
    },
  );

  const data = await res.json<{
    success: boolean;
    result?: { accessKeyId: string; secretAccessKey: string; sessionToken: string };
  }>();
  if (!res.ok || !data.success || !data.result) {
    return json({ error: 'credential_mint_failed' }, 502);
  }

  return json({
    access_key_id: data.result.accessKeyId,
    secret_access_key: data.result.secretAccessKey,
    session_token: data.result.sessionToken,
    region: 'auto',
    endpoint: `https://${env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
    bucket: env.R2_BUCKET,
    expires_in: ttlSeconds,
  });
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
