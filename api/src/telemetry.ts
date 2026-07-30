import { Env } from './types';

/** Shared stamp the MCP client sends — a filter for drive-by traffic, not a secret. */
const EXPECTED_STAMP = 'askamerica-mcp';

/** Analytics Engine caps a blob at 5120 bytes; SQL is the only field that gets near it. */
const MAX_SQL = 2048;
const MAX_ERR = 512;

/** Accepted in one request, so a client loop cannot turn a single POST into a flood. */
const MAX_BATCH = 50;

interface Event {
  recorded_at?: string;
  session_id?: string;
  build?: string;
  tool?: string;
  duration_ms?: number;
  row_count?: number;
  success?: boolean;
  query_sql?: string;
  error_msg?: string;
}

/**
 * POST /v1/telemetry — records MCP tool-call telemetry to Analytics Engine.
 *
 * Analytics Engine rather than D1: this is high-cardinality time-series data written on
 * every tool call, which is what AE is for and what D1 is not. The client is opt-in, so
 * nothing arrives unless a user turned telemetry on.
 *
 * Accepts one event or a batch, so a busy session costs one request rather than fifty.
 * Blob and double positions are fixed — anything querying mcp_telemetry depends on this
 * ordering, so append new fields at the end rather than inserting.
 */
export async function handleTelemetry(request: Request, env: Env): Promise<Response> {
  let payload: { stamp?: string; events?: Event[] } & Event;
  try {
    payload = await request.json();
  } catch {
    return json({ error: 'invalid_json' }, 400);
  }

  if (payload.stamp !== EXPECTED_STAMP) {
    return json({ error: 'not_found' }, 404);
  }

  // One event or a batch; a single event may be sent at the top level.
  const events: Event[] = Array.isArray(payload.events)
    ? payload.events.slice(0, MAX_BATCH)
    : [payload];

  let written = 0;
  for (const e of events) {
    if (!e || typeof e !== 'object') continue;
    try {
      env.TELEMETRY.writeDataPoint({
        blobs: [
          str(e.session_id),
          str(e.build),
          str(e.tool),
          str(e.recorded_at),
          str(e.query_sql).slice(0, MAX_SQL),
          str(e.error_msg).slice(0, MAX_ERR),
        ],
        doubles: [
          num(e.duration_ms),
          num(e.row_count),
          e.success ? 1 : 0,
        ],
        // Indexed on tool: the dimension worth slicing by when asking which tool is
        // slow or failing. AE allows exactly one index.
        indexes: [str(e.tool) || 'unknown'],
      });
      written++;
    } catch {
      // One malformed event must not lose the rest of the batch.
    }
  }

  return json({ ok: true, written });
}

function str(v: unknown): string {
  return typeof v === 'string' ? v : v == null ? '' : String(v);
}

function num(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : 0;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
