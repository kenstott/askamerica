import { Env } from './types';
import { resolveUser, recordActualUsage } from './quota';

// Engines from this release on send one aggregate per API key per hour:
//   {query_count, actual_bytes, row_count, duration_ms}
// Released engines still send one report per query:
//   {query_id, table, query_text, planned_bytes, actual_bytes, row_count, duration_ms}
// which is recorded as an aggregate of one query.
const NUMERIC_FIELDS = ['actual_bytes', 'row_count', 'duration_ms'] as const;

export async function handleUsageReport(request: Request, env: Env): Promise<Response> {
  const apiKey = request.headers.get('X-API-Key');
  if (!apiKey) return json({ error: 'unauthorized' }, 401);

  const userId = await resolveUser(apiKey, env);
  if (!userId) {
    console.warn('usage report rejected: key not in KEYS');
    return json({ error: 'unauthorized' }, 401);
  }

  let r: any;
  try {
    r = await request.json();
  } catch {
    return json({ error: 'invalid_json' }, 400);
  }
  if (typeof r !== 'object' || r === null) {
    return json({ error: 'invalid_report' }, 400);
  }
  const perQuery = r.query_count === undefined;
  const fields: readonly string[] = perQuery
    ? [...NUMERIC_FIELDS, 'planned_bytes'] : [...NUMERIC_FIELDS, 'query_count'];
  for (const name of fields) {
    const v = r[name];
    if (typeof v !== 'number' || !Number.isFinite(v) || v < 0) {
      return json({ error: 'invalid_field', field: name }, 400);
    }
  }
  const queryCount: number = perQuery ? 1 : r.query_count;

  env.ANALYTICS.writeDataPoint({
    blobs: perQuery
      ? [userId, r.query_id, r.table, (r.query_text ?? '').slice(0, 1024)]
      : [userId, 'aggregate', '', ''],
    doubles: [
      perQuery ? r.planned_bytes : r.actual_bytes,
      r.actual_bytes,
      r.row_count,
      r.duration_ms,
      queryCount,
    ],
    indexes: [userId],
  });

  await recordActualUsage(userId, r.actual_bytes, env);
  console.log(`usage recorded user=${userId} queries=${queryCount} bytes=${r.actual_bytes}`);

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

  // Upgrade points at the /upgrade page, which mints a per-user checkout via
  // /v1/checkout (the LS Checkouts API) — no stale hardcoded product links.
  const nextTier = tier === 'free' ? 'starter' : tier === 'starter' ? 'pro' : null;
  const upgrade = nextTier ? 'https://askamerica.ai/upgrade' : null;

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
