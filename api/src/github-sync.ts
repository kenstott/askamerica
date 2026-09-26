import { Env } from './types';

/**
 * Scheduled (Cron Trigger) job: files every un-synced row in D1's `issues` table as a
 * real GitHub issue in kenstott/govdata-ops, then marks it filed so it is never re-filed.
 *
 * Auto-files directly — no staging/review step. A raw customer report has no vetted
 * `kind`/`schema` label (those require the domain triage a human or the
 * defect-register-runner/sourcing-runner skills do for hand-filed issues), so this only
 * attaches `type:*` (from the column `issues.ts` now persists), `status:open`, and
 * `source:customer-report` so a triager can find these and add kind/schema by hand.
 * Nothing here is sacred about landing in GitHub — a bad auto-filed issue is exactly as
 * curable after the fact as a human-filed one (relabel, close as invalid, merge as a
 * duplicate), so this deliberately does not try to pre-validate report quality.
 */

const REPO = 'kenstott/govdata-ops';
const BATCH_SIZE = 20; // keeps one run comfortably under GitHub's per-token rate limit

interface IssueRow {
  id: string;
  reported_at: string | null;
  build: string | null;
  session_id: string | null;
  user_id: string | null;
  subject: string;
  body: string;
  type: string | null;
}

export async function syncIssuesToGithub(env: Env): Promise<{ filed: number; failed: number }> {
  if (!env.GITHUB_TOKEN) {
    // Not configured yet — a no-op, not an error, so a deploy before the secret is set
    // doesn't spam the Worker's error logs on every cron tick.
    return { filed: 0, failed: 0 };
  }

  const { results } = await env.DB.prepare(
    `SELECT id, reported_at, build, session_id, user_id, subject, body, type
       FROM issues
      WHERE github_issue_number IS NULL
      ORDER BY reported_at ASC
      LIMIT ?`,
  )
    .bind(BATCH_SIZE)
    .all<IssueRow>();

  let filed = 0;
  let failed = 0;

  for (const row of results) {
    try {
      const number = await fileOne(row, env.GITHUB_TOKEN);
      await env.DB.prepare(
        `UPDATE issues SET github_issue_number = ?, github_filed_at = ?, github_file_error = NULL WHERE id = ?`,
      )
        .bind(number, new Date().toISOString(), row.id)
        .run();
      filed++;
    } catch (e) {
      // Left with github_issue_number still NULL, so the next run retries it. The error is
      // recorded so a persistent per-row failure (e.g. a body GitHub rejects) is visible
      // without needing to read Worker logs.
      await env.DB.prepare(`UPDATE issues SET github_file_error = ? WHERE id = ?`)
        .bind(String(e).slice(0, 500), row.id)
        .run();
      failed++;
    }
  }

  return { filed, failed };
}

async function fileOne(row: IssueRow, token: string): Promise<number> {
  const labels = ['status:open', 'source:customer-report'];
  labels.push(row.type === 'defect' || row.type === 'sourcing' ? `type:${row.type}` : 'type:defect');

  const body = [
    row.body,
    '',
    '---',
    '_Filed automatically from a customer report — needs kind:/schema: triage._',
    `- D1 issue id: \`${row.id}\``,
    row.reported_at ? `- Reported at: ${row.reported_at}` : null,
    row.build ? `- Build: \`${row.build}\`` : null,
    row.session_id ? `- Session: \`${row.session_id}\`` : null,
    row.user_id ? `- User: \`${row.user_id}\`` : '- User: (unattributed)',
  ]
    .filter((line) => line !== null)
    .join('\n');

  const resp = await fetch(`https://api.github.com/repos/${REPO}/issues`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
      'User-Agent': 'askamerica-api-github-sync',
    },
    body: JSON.stringify({
      title: row.subject.slice(0, 256),
      body,
      labels,
    }),
  });

  if (!resp.ok) {
    const detail = await resp.text().catch(() => '');
    throw new Error(`GitHub issue create failed: HTTP ${resp.status} ${detail.slice(0, 200)}`);
  }

  const created = (await resp.json()) as { number: number };
  return created.number;
}
