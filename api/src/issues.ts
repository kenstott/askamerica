import { Env } from './types';
import { resolveUser } from './quota';

/**
 * Shared stamp the MCP client sends. This is a filter, not a secret — the endpoint is
 * deliberately public so a customer can report a problem even when their key is the
 * thing that is broken. It exists so the handler can drop drive-by traffic that finds
 * the route without spending a D1 write on it.
 */
const EXPECTED_STAMP = 'askamerica-mcp';

const MAX_SUBJECT = 200;
const MAX_BODY = 20000;

/**
 * POST /v1/issues — records one customer-reported issue.
 *
 * Public by design. An API key is optional: when present it is resolved so the row can
 * be attributed, but a bad or absent key never rejects the report. Someone whose key has
 * expired is exactly who needs to file one.
 */
export async function handleIssueReport(request: Request, env: Env): Promise<Response> {
  let payload: {
    stamp?: string;
    build?: string;
    session_id?: string;
    reported_at?: string;
    subject?: string;
    body?: string;
  };
  try {
    payload = await request.json();
  } catch {
    return json({ error: 'invalid_json' }, 400);
  }

  if (payload.stamp !== EXPECTED_STAMP) {
    // Same shape as a missing route, so a scanner learns nothing about what is expected.
    return json({ error: 'not_found' }, 404);
  }

  const subject = (payload.subject ?? '').trim();
  const body = (payload.body ?? '').trim();
  if (!subject || !body) {
    return json({ error: 'subject and body are required' }, 400);
  }

  // Attribution is best-effort: an unknown key must not cost the caller their report.
  let userId: string | null = null;
  const apiKey = request.headers.get('X-API-Key');
  if (apiKey) {
    try {
      userId = await resolveUser(apiKey, env);
    } catch {
      userId = null;
    }
  }

  const id = crypto.randomUUID();
  try {
    await env.DB.prepare(
      `INSERT INTO issues
         (id, reported_at, stamp, build, session_id, user_id, subject, body)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    )
      .bind(
        id,
        payload.reported_at ?? null,
        payload.stamp,
        payload.build ?? null,
        payload.session_id ?? null,
        userId,
        subject.slice(0, MAX_SUBJECT),
        body.slice(0, MAX_BODY),
      )
      .run();
  } catch (e) {
    // Reported, not swallowed: the client tells the user their report did not land, so
    // they can keep it rather than assume it was filed.
    return json({ error: 'storage_failed', detail: String(e).slice(0, 200) }, 500);
  }

  return json({ ok: true, id });
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
