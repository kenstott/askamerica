import { Env } from './types';
import { resolveUser } from './quota';

const MAX_TITLE = 500;
const MAX_QUESTION = 2000;
// D1 caps a row well under this, but the practical failure mode worth catching here is
// a client bug sending something absurd, not the exact D1 ceiling.
const MAX_HTML = 2_000_000;

// Public studies pages live at <handle>.askamerica.ai, distinct from the JSON API's own
// api.askamerica.ai — this is a fixed constant, not derived from the request, because a
// POST to /v1/studies/register always arrives with Host: api.askamerica.ai and the URL
// handed back must point at the *other* domain.
export const STUDIES_ROOT_DOMAIN = 'askamerica.ai';

// Subdomains a handle must never collide with, since they're already spoken for.
export const RESERVED_HANDLES = new Set([
  'api', 'www', 'app', 'admin', 'mail', 'ftp', 'studies', 'blog', 'docs', 'status',
]);

interface StudiesAccount {
  user_id: string;
  handle: string;
  display_name: string;
  org: string | null;
  created_at: number;
}

interface StudyRow {
  id: string;
  user_id: string;
  title: string | null;
  question: string | null;
  html: string;
  created_at: number;
}

function slugify(name: string): string {
  const base = name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return base || 'user';
}

/**
 * Picks a handle for a new account: the plain slug if free, otherwise the slug plus a
 * short random suffix, retried a few times. Handles are permanent once assigned (see
 * handleStudiesRegister), so this only ever runs once per account.
 */
async function pickHandle(name: string, env: Env): Promise<string> {
  const base = slugify(name);
  for (let attempt = 0; attempt < 5; attempt++) {
    const candidate = attempt === 0
      ? base
      : `${base}-${crypto.randomUUID().slice(0, 6)}`;
    if (RESERVED_HANDLES.has(candidate)) continue;
    const existing = await env.DB.prepare(
      'SELECT 1 FROM studies_accounts WHERE handle = ?'
    ).bind(candidate).first();
    if (!existing) return candidate;
  }
  // Astronomically unlikely to be reached, but never loop forever.
  return `${base}-${crypto.randomUUID()}`;
}

function studiesIndexUrl(handle: string): string {
  return `https://${handle}.${STUDIES_ROOT_DOMAIN}/index`;
}

function studyReportUrl(handle: string, id: string): string {
  return `https://${handle}.${STUDIES_ROOT_DOMAIN}/${id}`;
}

async function requireUser(request: Request, env: Env): Promise<string | Response> {
  const apiKey = request.headers.get('X-API-Key') || '';
  if (!apiKey) return json({ error: 'missing_api_key' }, 401);
  const userId = await resolveUser(apiKey, env);
  if (!userId) return json({ error: 'invalid_api_key' }, 401);
  return userId;
}

/**
 * POST /v1/studies/register — creates or updates the caller's Studies account.
 *
 * The handle is assigned once, on first registration, and never changes afterward —
 * every link into an account's index/report pages depends on it staying stable, so a
 * later name change must not silently break links already shared.
 */
export async function handleStudiesRegister(request: Request, env: Env): Promise<Response> {
  const userId = await requireUser(request, env);
  if (userId instanceof Response) return userId;

  let payload: { name?: string; org?: string };
  try {
    payload = await request.json();
  } catch {
    return json({ error: 'invalid_json' }, 400);
  }
  const name = (payload.name ?? '').trim();
  if (!name) return json({ error: 'name is required' }, 400);
  const org = (payload.org ?? '').trim() || null;

  const existing = await env.DB.prepare(
    'SELECT handle FROM studies_accounts WHERE user_id = ?'
  ).bind(userId).first<{ handle: string }>();

  let handle: string;
  if (existing) {
    handle = existing.handle;
    await env.DB.prepare(
      'UPDATE studies_accounts SET display_name = ?, org = ? WHERE user_id = ?'
    ).bind(name, org, userId).run();
  } else {
    // The org name wins over the display name as the slug source when given, so
    // colleagues publishing under the same org get visually related subdomains.
    handle = await pickHandle(org || name, env);
    await env.DB.prepare(
      'INSERT INTO studies_accounts (user_id, handle, display_name, org, created_at) VALUES (?, ?, ?, ?, ?)'
    ).bind(userId, handle, name, org, Date.now()).run();
  }

  return json({ studiesUrl: studiesIndexUrl(handle) });
}

/** GET /v1/studies/me — looks up the caller's Studies page link. */
export async function handleStudiesMe(request: Request, env: Env): Promise<Response> {
  const userId = await requireUser(request, env);
  if (userId instanceof Response) return userId;

  const acct = await env.DB.prepare(
    'SELECT handle FROM studies_accounts WHERE user_id = ?'
  ).bind(userId).first<{ handle: string }>();
  if (!acct) return json({ error: 'not_registered' }, 404);

  return json({ studiesUrl: studiesIndexUrl(acct.handle) });
}

/**
 * POST /v1/studies/reports — uploads the report body publish_report last built.
 *
 * Requires an existing account: the MCP client already checks this locally before
 * calling, but that check must not be trusted as the only gate — a direct call here
 * with no prior register must not silently create an orphaned report.
 */
export async function handleStudiesUpload(request: Request, env: Env): Promise<Response> {
  const userId = await requireUser(request, env);
  if (userId instanceof Response) return userId;

  const acct = await env.DB.prepare(
    'SELECT handle FROM studies_accounts WHERE user_id = ?'
  ).bind(userId).first<{ handle: string }>();
  if (!acct) return json({ error: 'not_registered' }, 404);

  let payload: { title?: string; question?: string; html?: string };
  try {
    payload = await request.json();
  } catch {
    return json({ error: 'invalid_json' }, 400);
  }
  const html = payload.html ?? '';
  if (!html) return json({ error: 'html is required' }, 400);
  if (html.length > MAX_HTML) return json({ error: 'html too large' }, 413);

  const id = crypto.randomUUID();
  await env.DB.prepare(
    `INSERT INTO studies (id, user_id, title, question, html, created_at)
     VALUES (?, ?, ?, ?, ?, ?)`
  ).bind(
    id,
    userId,
    (payload.title ?? '').slice(0, MAX_TITLE) || null,
    (payload.question ?? '').slice(0, MAX_QUESTION) || null,
    html,
    Date.now(),
  ).run();

  return json({ url: studyReportUrl(acct.handle, id) });
}

/**
 * DELETE /v1/studies/reports/:id — removes one report, owner only.
 *
 * The owner check is the entire security model for delete: never trust the caller's
 * own claim about which account a report belongs to, only the row's own user_id.
 */
export async function handleStudyDelete(
  request: Request, env: Env, id: string
): Promise<Response> {
  const userId = await requireUser(request, env);
  if (userId instanceof Response) return userId;

  const row = await env.DB.prepare(
    'SELECT user_id FROM studies WHERE id = ?'
  ).bind(id).first<{ user_id: string }>();
  if (!row) return json({ error: 'not_found' }, 404);
  if (row.user_id !== userId) return json({ error: 'forbidden' }, 403);

  await env.DB.prepare('DELETE FROM studies WHERE id = ?').bind(id).run();
  return json({ ok: true });
}

/** GET /studies/:handle — the account's public index page. */
export async function handleStudiesIndex(
  request: Request, env: Env, handle: string
): Promise<Response> {
  const acct = await env.DB.prepare(
    'SELECT * FROM studies_accounts WHERE handle = ?'
  ).bind(handle).first<StudiesAccount>();
  if (!acct) return html(notFoundPage(), 404);

  const { results } = await env.DB.prepare(
    'SELECT id, title, question, created_at FROM studies WHERE user_id = ? ORDER BY created_at DESC'
  ).bind(acct.user_id).all<Pick<StudyRow, 'id' | 'title' | 'question' | 'created_at'>>();

  return html(renderIndexPage(acct, results ?? []));
}

/** GET /studies/:handle/:id — one report, served as the self-contained page it was
 * uploaded as, with a small back-link banner spliced in. */
export async function handleStudyPage(
  request: Request, env: Env, handle: string, id: string
): Promise<Response> {
  const acct = await env.DB.prepare(
    'SELECT user_id FROM studies_accounts WHERE handle = ?'
  ).bind(handle).first<{ user_id: string }>();
  if (!acct) return html(notFoundPage(), 404);

  const row = await env.DB.prepare(
    'SELECT html FROM studies WHERE id = ? AND user_id = ?'
  ).bind(id, acct.user_id).first<{ html: string }>();
  if (!row) return html(notFoundPage(), 404);

  const banner = `
<div style="position:sticky;top:0;z-index:999;background:#080b0f;border-bottom:1px solid #1e2d3d;
padding:10px 20px;font-family:'JetBrains Mono',monospace;font-size:13px;">
  <a href="/index" style="color:#e8a24a;text-decoration:none;">&larr; Back to this Studies page</a>
</div>`.trim();
  const spliced = row.html.replace(/(<body[^>]*>)/, `$1\n${banner}`);
  return html(spliced);
}

function renderIndexPage(
  acct: StudiesAccount,
  rows: Pick<StudyRow, 'id' | 'title' | 'question' | 'created_at'>[]
): string {
  const items = rows.map(r => {
    const label = escapeHtml(r.question || r.title || '(untitled report)');
    return `<li class="study-row" data-id="${escapeAttr(r.id)}">
      <a href="/${escapeAttr(r.id)}">${label}</a>
      <button class="del" hidden aria-label="Delete">&#128465;</button>
    </li>`;
  }).join('\n');

  const orgLine = acct.org ? ` <span class="org">&middot; ${escapeHtml(acct.org)}</span>` : '';

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHtml(acct.display_name)}'s AskAmerica Studies</title>
<style>
  body { background:#080b0f; color:#cdd9e5; font-family:'JetBrains Mono',monospace;
         font-size:14px; line-height:1.7; margin:0; }
  main { max-width:800px; margin:0 auto; padding:2rem; }
  h1 { color:#f0f6fc; font-size:1.3rem; }
  .org { color:#768390; font-weight:normal; }
  ul { list-style:none; padding:0; }
  .study-row { display:flex; align-items:center; justify-content:space-between;
               padding:0.6rem 0; border-bottom:1px solid #1e2d3d; }
  a { color:#e8a24a; text-decoration:none; }
  a:hover { text-decoration:underline; }
  .del { background:none; border:none; color:#768390; cursor:pointer; font-size:1rem; }
  .del:hover { color:#e05252; }
  #manage { margin-top:2rem; padding-top:1rem; border-top:1px solid #1e2d3d; }
  #manage input { background:#0d1117; border:1px solid #1e2d3d; color:#cdd9e5;
                  font-family:inherit; font-size:0.85rem; padding:0.4rem; width:20rem; }
  #manage button { font-family:inherit; }
  #status { font-size:0.85rem; color:#768390; margin-left:0.5rem; }
</style></head>
<body>
<main>
  <h1>${escapeHtml(acct.display_name)}'s AskAmerica Studies${orgLine}</h1>
  <ul>${items || '<li>No studies published yet.</li>'}</ul>
  <div id="manage">
    <label>Owner? Enter your API key to manage:
      <input id="key" type="password" autocomplete="off">
    </label>
    <button id="unlock">Unlock</button>
    <span id="status"></span>
  </div>
</main>
<script>
(function () {
  var handle = ${JSON.stringify(acct.handle)};
  var keyInput = document.getElementById('key');
  var status = document.getElementById('status');
  document.getElementById('unlock').addEventListener('click', function () {
    var key = keyInput.value.trim();
    if (!key) return;
    status.textContent = 'checking...';
    fetch('https://api.${STUDIES_ROOT_DOMAIN}/v1/studies/me', { headers: { 'X-API-Key': key } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || data.studiesUrl.indexOf('://' + handle + '.') === -1) {
          status.textContent = 'not the owner of this page';
          return;
        }
        try { localStorage.setItem('askamerica_studies_key', key); } catch (e) {}
        status.textContent = 'unlocked';
        document.querySelectorAll('.del').forEach(function (btn) { btn.hidden = false; });
        document.querySelectorAll('.del').forEach(function (btn) {
          btn.addEventListener('click', function () {
            var row = btn.closest('.study-row');
            var id = row.getAttribute('data-id');
            if (!confirm('Delete this report? This cannot be undone.')) return;
            fetch('https://api.${STUDIES_ROOT_DOMAIN}/v1/studies/reports/' + id, {
              method: 'DELETE',
              headers: { 'X-API-Key': key },
            }).then(function (r) {
              if (r.ok) row.remove();
              else status.textContent = 'delete failed';
            });
          });
        });
      });
  });
  try {
    var saved = localStorage.getItem('askamerica_studies_key');
    if (saved) { keyInput.value = saved; }
  } catch (e) {}
})();
</script>
</body></html>`;
}

function notFoundPage(): string {
  return `<!doctype html><html><head><meta charset="utf-8"><title>Not found</title></head>
<body style="background:#080b0f;color:#cdd9e5;font-family:monospace;padding:2rem;">
Not found.</body></html>`;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c] as string));
}

function escapeAttr(s: string): string {
  return escapeHtml(s);
}

function html(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  });
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
