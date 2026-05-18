import { Env } from './types';
import { resolveUser, recordActualUsage } from './quota';
import { upgradeUrl, VARIANT_IDS } from './checkout';

export async function handleUsageReport(request: Request, env: Env): Promise<Response> {
  const apiKey = request.headers.get('X-API-Key');
  if (!apiKey) return json({ error: 'unauthorized' }, 401);

  const userId = await resolveUser(apiKey, env);
  if (!userId) return json({ error: 'unauthorized' }, 401);

  const { query_id, table, actual_bytes, planned_bytes, row_count, duration_ms, query_text } =
    await request.json<{
      query_id:     string;
      table:        string;
      actual_bytes: number;
      planned_bytes: number;
      row_count:    number;
      duration_ms:  number;
      query_text:   string;
    }>();

  env.ANALYTICS.writeDataPoint({
    blobs: [
      userId,
      query_id,
      table,
      (query_text ?? '').slice(0, 1024),
    ],
    doubles: [
      planned_bytes,
      actual_bytes,
      row_count,
      duration_ms,
    ],
    indexes: [userId],
  });

  await recordActualUsage(userId, actual_bytes, planned_bytes, env);

  return json({ ok: true });
}

export async function handleQuotaStatus(request: Request, env: Env): Promise<Response> {
  const apiKey = request.headers.get('X-API-Key');
  if (!apiKey) return json({ error: 'unauthorized' }, 401);

  const userId = await resolveUser(apiKey, env);
  if (!userId) return json({ error: 'unauthorized' }, 401);

  const d = new Date();
  const period = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;

  const row = await env.DB.prepare(
    'SELECT limit_bytes, used_bytes FROM quota_periods WHERE user_id = ? AND period = ?'
  ).bind(userId, period).first<{ limit_bytes: number; used_bytes: number }>();

  const limit = row?.limit_bytes ?? 1 * 1024 * 1024 * 1024;
  const used  = row?.used_bytes  ?? 0;

  const tier = (await env.DB.prepare(
    'SELECT tier FROM users WHERE id = ?'
  ).bind(userId).first<{ tier: string }>())?.tier ?? 'free';

  const nextTier = tier === 'free' ? 'starter' : tier === 'starter' ? 'pro' : null;
  const upgrade = nextTier ? upgradeUrl(VARIANT_IDS[nextTier], userId) : null;

  return json({
    period,
    tier,
    used_bytes:      used,
    limit_bytes:     limit,
    remaining_bytes: limit - used,
    upgrade_url:     upgrade,
  });
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
