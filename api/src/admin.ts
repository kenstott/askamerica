import { Env } from './types';

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
