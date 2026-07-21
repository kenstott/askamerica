import { Env, QuotaRecord, TIER_LIMITS } from './types';

export function currentPeriod(): string {
  const d = new Date();
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

async function sha256hex(input: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

export async function resolveUser(apiKey: string, env: Env): Promise<string | null> {
  const keyHash = await sha256hex(apiKey);
  return env.KEYS.get(keyHash);
}

export async function checkAndReserveQuota(
  userId: string,
  plannedBytes: number,
  env: Env
): Promise<{ allowed: boolean; remaining: number }> {
  const period = currentPeriod();
  const kvKey = `${userId}:${period}`;

  let record = await env.QUOTA.get<QuotaRecord>(kvKey, { type: 'json' });

  if (!record) {
    // load from D1 (cold path)
    const row = await env.DB.prepare(
      'SELECT limit_bytes, used_bytes FROM quota_periods WHERE user_id = ? AND period = ?'
    ).bind(userId, period).first<{ limit_bytes: number; used_bytes: number }>();

    if (!row) {
      // first query this period — seed it
      const user = await env.DB.prepare(
        'SELECT tier FROM users WHERE id = ?'
      ).bind(userId).first<{ tier: string }>();
      const tier = user?.tier ?? 'free';
      const limit = TIER_LIMITS[tier] ?? TIER_LIMITS['free'];
      await env.DB.prepare(
        'INSERT INTO quota_periods (user_id, period, limit_bytes, used_bytes) VALUES (?, ?, ?, 0) ON CONFLICT DO NOTHING'
      ).bind(userId, period, limit).run();
      record = { limit_bytes: limit, used_bytes: 0, period };
    } else {
      record = { limit_bytes: row.limit_bytes, used_bytes: row.used_bytes, period };
    }
    // warm the cache (5 min TTL)
    await env.QUOTA.put(kvKey, JSON.stringify(record), { expirationTtl: 300 });
  }

  const remaining = record.limit_bytes - record.used_bytes;
  if (plannedBytes > remaining) {
    return { allowed: false, remaining };
  }

  // reserve bytes atomically in D1, then update KV cache
  await env.DB.prepare(
    'UPDATE quota_periods SET used_bytes = used_bytes + ? WHERE user_id = ? AND period = ?'
  ).bind(plannedBytes, userId, period).run();

  const updated: QuotaRecord = {
    ...record,
    used_bytes: record.used_bytes + plannedBytes,
  };
  await env.QUOTA.put(kvKey, JSON.stringify(updated), { expirationTtl: 300 });

  return { allowed: true, remaining: remaining - plannedBytes };
}

export async function recordActualUsage(
  userId: string,
  egressBytes: number,
  env: Env
): Promise<void> {
  // Client reports estimated R2 egress per query; add it to this period's usage.
  const bytes = Math.max(0, Math.floor(egressBytes || 0));
  if (bytes === 0) return;

  const period = currentPeriod();

  // Seed the period row from the user's tier if this is their first query of the
  // period, then add the egress — both in one upsert so usage is never dropped.
  const user = await env.DB.prepare(
    'SELECT tier FROM users WHERE id = ?'
  ).bind(userId).first<{ tier: string }>();
  const limit = TIER_LIMITS[user?.tier ?? 'free'] ?? TIER_LIMITS['free'];

  await env.DB.prepare(
    `INSERT INTO quota_periods (user_id, period, limit_bytes, used_bytes)
     VALUES (?, ?, ?, ?)
     ON CONFLICT(user_id, period) DO UPDATE SET used_bytes = used_bytes + excluded.used_bytes`
  ).bind(userId, period, limit, bytes).run();

  // invalidate KV so the next quota read re-reads from D1
  await env.QUOTA.delete(`${userId}:${period}`);
}
