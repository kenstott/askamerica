import { Env } from './types';
import { currentPeriod } from './quota';

async function sha256hex(input: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

function generateApiKey(tier: string): string {
  const prefix = `aa_${tier}_`;
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  const token = btoa(String.fromCharCode(...bytes)).replace(/[+/=]/g, '');
  return prefix + token;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

export async function handleAdminCreateKey(request: Request, env: Env): Promise<Response> {
  const auth = request.headers.get('Authorization') || '';
  if (!auth.startsWith('Bearer ') || auth.slice(7) !== env.ADMIN_SECRET) {
    return json({ error: 'unauthorized' }, 401);
  }

  const { email, tier = 'internal', label = '' } =
    await request.json<{ email: string; tier?: string; label?: string }>();

  if (!email) return json({ error: 'missing_email' }, 400);

  const validTiers = ['free', 'starter', 'pro', 'internal'];
  if (!validTiers.includes(tier)) return json({ error: 'invalid_tier' }, 400);

  const userId = await sha256hex(email.toLowerCase());
  const now = Date.now();

  await env.DB.prepare(`
    INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)
    ON CONFLICT(email) DO NOTHING
  `).bind(userId, email.toLowerCase(), now).run();

  if (tier !== 'free') {
    await env.DB.prepare(`
      UPDATE users SET tier = ? WHERE id = ?
    `).bind(tier, userId).run();
  }

  const apiKey = generateApiKey(tier);
  const keyHash = await sha256hex(apiKey);
  const labelField = label || `admin-issued ${tier}`;

  await env.DB.prepare(`
    INSERT INTO api_keys (key_hash, user_id, created_at) VALUES (?, ?, ?)
  `).bind(keyHash, userId, now).run();

  await env.KEYS.put(keyHash, userId);

  return json({ api_key: apiKey, tier, email, label: labelField });
}

/**
 * POST /v1/admin/grant — grants a byte allowance to an existing user through a given month.
 *
 * Recovered from the deployed bundle (version 23). The route was live and routed in the
 * Worker but absent from this source tree, so a deploy from here would have silently
 * removed it. Reconstructed to match the deployed behaviour; the only differences are
 * TypeScript annotations and using this module's own sha256hex/json rather than the
 * bundler's renamed copies.
 */
export async function handleAdminGrant(request: Request, env: Env): Promise<Response> {
  const auth = request.headers.get('Authorization') || '';
  if (!auth.startsWith('Bearer ') || auth.slice(7) !== env.ADMIN_SECRET) {
    return json({ error: 'unauthorized' }, 401);
  }

  const { email, gb, expires } =
    await request.json<{ email: string; gb: number; expires: string }>();

  if (!email) return json({ error: 'missing_email' }, 400);
  if (typeof gb !== 'number' || !(gb > 0)) return json({ error: 'invalid_gb' }, 400);
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(expires || '')) {
    return json({ error: 'invalid_expires' }, 400);
  }

  const period = currentPeriod();
  if (expires < period) {
    return json({ error: 'expires_in_past', current_period: period }, 400);
  }

  const userId = await sha256hex(email.toLowerCase());
  const user = await env.DB.prepare(
    'SELECT tier FROM users WHERE id = ?',
  ).bind(userId).first<{ tier: string }>();
  if (!user) return json({ error: 'unknown_user' }, 404);

  const limitBytes = Math.round(gb * 1024 * 1024 * 1024);
  const now2 = Date.now();

  await env.DB.prepare(`
    INSERT INTO quota_grants (user_id, limit_bytes, expires_period, created_at)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(user_id) DO UPDATE SET
      limit_bytes = excluded.limit_bytes,
      expires_period = excluded.expires_period,
      created_at = excluded.created_at
  `).bind(userId, limitBytes, expires, now2).run();

  // Read the affected periods before the UPDATE so each cached QUOTA entry can be dropped;
  // a stale entry would keep serving the pre-grant limit.
  const affected = await env.DB.prepare(
    'SELECT period FROM quota_periods WHERE user_id = ? AND period >= ? AND period <= ?',
  ).bind(userId, period, expires).all<{ period: string }>();

  await env.DB.prepare(
    'UPDATE quota_periods SET limit_bytes = MAX(limit_bytes, ?) '
      + 'WHERE user_id = ? AND period >= ? AND period <= ?',
  ).bind(limitBytes, userId, period, expires).run();

  for (const r of affected.results ?? []) {
    await env.QUOTA.delete(`${userId}:${r.period}`);
  }

  return json({
    email,
    tier: user.tier,
    grant_gb: gb,
    limit_bytes: limitBytes,
    expires_period: expires,
  });
}
