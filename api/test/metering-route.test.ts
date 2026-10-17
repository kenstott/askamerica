import { SELF, env } from 'cloudflare:test';
import { describe, it, expect } from 'vitest';

// These go through the Worker's own fetch handler (SELF), not handleUsageReport directly.
// lifecycle.test.ts calls the handler directly, which is how a route that answered ok before
// the work ran, and then threw on "Can't read from request stream after response has been
// sent", went unnoticed: every usage report was dropped while the suite stayed green.

const GiB = 1024 * 1024 * 1024;
const E = env as any;

async function sha256hex(s: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}

let seq = 0;
async function seedUser() {
  const email = `route${seq++}@test.dev`;
  const userId = await sha256hex(email);
  const apiKey = `aa_route_${userId.slice(0, 12)}`;
  const keyHash = await sha256hex(apiKey);
  const period = new Date().toISOString().slice(0, 7);
  await E.DB.prepare('INSERT OR REPLACE INTO users (id,email,created_at,tier) VALUES (?,?,?,?)')
    .bind(userId, email, Date.now(), 'free').run();
  await E.DB.prepare('INSERT OR REPLACE INTO api_keys (key_hash,user_id,created_at) VALUES (?,?,?)')
    .bind(keyHash, userId, Date.now()).run();
  await E.KEYS.put(keyHash, userId);
  await E.DB.prepare('INSERT OR REPLACE INTO quota_periods (user_id,period,limit_bytes,used_bytes) VALUES (?,?,?,0)')
    .bind(userId, period, 1 * GiB).run();
  return { userId, apiKey, period };
}

function report(apiKey: string | null, body: unknown): Promise<Response> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (apiKey !== null) headers['X-API-Key'] = apiKey;
  return SELF.fetch('https://api.example.test/v1/metering/usage', {
    method: 'POST',
    headers,
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

const good = (bytes: number) => ({
  query_id: 'q', table: 't', actual_bytes: bytes, planned_bytes: bytes, row_count: 3,
  duration_ms: 5, query_text: 'select 1',
});

async function usedBytes(userId: string, period: string): Promise<number> {
  const row = await E.DB.prepare('SELECT used_bytes FROM quota_periods WHERE user_id = ? AND period = ?')
    .bind(userId, period).first();
  return row ? row.used_bytes : -1;
}

describe('POST /v1/metering/usage through the Worker', () => {
  it('records the reported bytes against the key owner before it answers', async () => {
    const u = await seedUser();
    const r = await report(u.apiKey, good(1234));
    expect(r.status).toBe(200);
    expect(await r.json()).toEqual({ ok: true });
    // Read straight after the response: the work must be done by now, not in the background.
    expect(await usedBytes(u.userId, u.period)).toBe(1234);
  });

  it('adds up several reports', async () => {
    const u = await seedUser();
    expect((await report(u.apiKey, good(100))).status).toBe(200);
    expect((await report(u.apiKey, good(250))).status).toBe(200);
    expect(await usedBytes(u.userId, u.period)).toBe(350);
  });

  it('refuses an unknown key instead of answering ok', async () => {
    const u = await seedUser();
    const r = await report('aa_not_a_real_key', good(999));
    expect(r.status).toBe(401);
    expect(await usedBytes(u.userId, u.period)).toBe(0);
  });

  it('refuses a request with no key', async () => {
    const r = await report(null, good(10));
    expect(r.status).toBe(401);
  });

  it('refuses a body that is not JSON', async () => {
    const u = await seedUser();
    const r = await report(u.apiKey, 'not json {');
    expect(r.status).toBe(400);
    expect(await usedBytes(u.userId, u.period)).toBe(0);
  });

  it('refuses a negative or non-numeric figure and records nothing', async () => {
    const u = await seedUser();
    const negative = await report(u.apiKey, { ...good(10), actual_bytes: -5 });
    expect(negative.status).toBe(400);
    const text = await report(u.apiKey, { ...good(10), row_count: 'many' });
    expect(text.status).toBe(400);
    expect(await usedBytes(u.userId, u.period)).toBe(0);
  });
});
