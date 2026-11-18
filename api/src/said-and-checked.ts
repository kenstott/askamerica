import { Env } from './types';

// Said & Checked daily email.
//
// subscribe → a confirmation email with a one-use link; nothing is stored at Resend yet.
// confirm   → the address becomes a Resend contact in the Said & Checked segment.
// send      → (SAID_CHECKED_SEND_SECRET) the day's email goes out once as a Resend broadcast to that segment.
//
// Every broadcast gets the same footer here: why the reader is getting it, the unsubscribe
// link Resend fills in, and the sender's postal address, which US law requires in
// commercial email.

const RESEND = 'https://api.resend.com';
const FROM = 'AskAmerica Said & Checked <said-and-checked@askamerica.ai>';
const CONFIRM_TTL_SECONDS = 2 * 24 * 3600;
const SEND_WINDOW_SECONDS = 3600;
const MAX_SENDS_PER_EMAIL = 3;   // confirmation emails per address per window
const MAX_SENDS_PER_IP = 10;     // sign-ups per source IP per window
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const SITE = 'https://askamerica.ai';
const ARCHIVE = SITE + '/studies/said-and-checked-archive/';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function page(title: string, body: string, status = 200): Response {
  return new Response(
    `<!doctype html><html lang="en"><head><meta charset="utf-8">` +
    `<meta name="viewport" content="width=device-width, initial-scale=1"><title>${title}</title>` +
    `<style>body{margin:0;background:#0d1117;color:#cdd9e5;font:17px/1.6 -apple-system,` +
    `BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}main{max-width:560px;margin:0 auto;` +
    `padding:64px 16px}h1{color:#f0f6fc;font-size:1.5rem}a{color:#e8a24a}</style></head>` +
    `<body><main><h1>${title}</h1>${body}</main></body></html>`,
    { status, headers: { 'Content-Type': 'text/html; charset=utf-8' } },
  );
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function resend(env: Env, method: string, path: string, body?: unknown): Promise<Response> {
  return fetch(RESEND + path, {
    method,
    headers: { 'Authorization': `Bearer ${env.RESEND_API_KEY}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

function newToken(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(32)))
    .map(b => b.toString(16).padStart(2, '0')).join('');
}

export function emailFooter(env: Env): string {
  return (
    '<hr style="border:none;border-top:1px solid #d0d7de;margin:32px 0 16px">' +
    '<p style="color:#57606a;font-size:13px;line-height:1.5;margin:0">' +
    `You are getting this because you subscribed to Said &amp; Checked at ` +
    `<a href="${ARCHIVE}" style="color:#57606a">askamerica.ai</a>. ` +
    '<a href="{{{RESEND_UNSUBSCRIBE_URL}}}" style="color:#57606a">Unsubscribe</a>.<br>' +
    `AskAmerica &middot; ${escapeHtml(env.MAIL_POSTAL_ADDRESS)}</p>`
  );
}

export async function handleSaidSubscribe(request: Request, env: Env): Promise<Response> {
  const { email } = await request.json<{ email: string }>();
  if (!email || email.length > 320 || !EMAIL_RE.test(email)) {
    return json({ error: 'invalid_email' }, 400);
  }
  const emailLc = email.toLowerCase();

  // Soft caps (KV is eventually consistent): stop one address being mail-bombed and one
  // source flooding sign-ups. These sends share Resend's daily cap with login codes.
  const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
  const byEmail = parseInt((await env.OTP.get(`sc_sub:${emailLc}`)) || '0', 10);
  if (byEmail >= MAX_SENDS_PER_EMAIL) return json({ error: 'rate_limited' }, 429);
  const byIp = parseInt((await env.OTP.get(`sc_sub_ip:${ip}`)) || '0', 10);
  if (byIp >= MAX_SENDS_PER_IP) return json({ error: 'rate_limited' }, 429);

  const token = newToken();
  await env.OTP.put(`sc_confirm:${token}`, emailLc, { expirationTtl: CONFIRM_TTL_SECONDS });
  await env.OTP.put(`sc_sub:${emailLc}`, String(byEmail + 1), { expirationTtl: SEND_WINDOW_SECONDS });
  await env.OTP.put(`sc_sub_ip:${ip}`, String(byIp + 1), { expirationTtl: SEND_WINDOW_SECONDS });

  const link = `${new URL(request.url).origin}/v1/said-and-checked/confirm?token=${token}`;
  const res = await resend(env, 'POST', '/emails', {
    from: FROM,
    to: emailLc,
    subject: 'Confirm your Said & Checked subscription',
    html:
      '<p>Confirm that you want the Said &amp; Checked daily email: what officeholders said ' +
      'each day, and which statements government data supports, contradicts or rules out.</p>' +
      `<p><a href="${link}" style="display:inline-block;background:#1a56db;color:#ffffff;` +
      'padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:600">' +
      'Confirm subscription</a></p>' +
      '<p>The link works for two days. If you did not ask for this, ignore this email and ' +
      'nothing will be sent.</p>',
  });
  if (!res.ok) {
    console.error('resend error (confirm email)', res.status, await res.text());
    return json({ error: 'email_send_failed' }, 502);
  }
  return json({ ok: true });
}

export async function handleSaidConfirm(request: Request, env: Env): Promise<Response> {
  const token = new URL(request.url).searchParams.get('token') || '';
  if (!/^[0-9a-f]{64}$/.test(token)) {
    return page('Link not valid', '<p>This confirmation link is not valid.</p>', 400);
  }
  const email = await env.OTP.get(`sc_confirm:${token}`);
  if (!email) {
    return page('Link expired',
      `<p>This confirmation link has expired or was already used. ` +
      `<a href="${ARCHIVE}">Sign up again</a>.</p>`, 410);
  }

  // An address seen before (for example one that unsubscribed) is updated; a new one is created.
  const seg = env.SAID_CHECKED_SEGMENT_ID;
  const enc = encodeURIComponent(email);
  const upd = await resend(env, 'PATCH', `/contacts/${enc}`, { unsubscribed: false });
  let ok: boolean;
  let detail: string;
  if (upd.status === 404) {
    const created = await resend(env, 'POST', '/contacts',
      { email, unsubscribed: false, segments: [{ id: seg }] });
    ok = created.ok;
    detail = ok ? '' : `create ${created.status} ${await created.text()}`;
  } else if (upd.ok) {
    const added = await resend(env, 'POST', `/contacts/${enc}/segments/${seg}`);
    ok = added.ok;
    detail = ok ? '' : `segment ${added.status} ${await added.text()}`;
  } else {
    ok = false;
    detail = `update ${upd.status} ${await upd.text()}`;
  }
  if (!ok) {
    console.error('resend error (confirm)', detail);
    return page('Something went wrong',
      '<p>Your subscription could not be saved. Please try the link again in a few minutes.</p>',
      502);
  }
  await env.OTP.delete(`sc_confirm:${token}`);
  return page('You are subscribed',
    '<p>Said &amp; Checked will arrive once a day, after each day is checked and published.</p>' +
    `<p><a href="${ARCHIVE}">Read the latest days</a></p>`);
}

export async function handleSaidSend(request: Request, env: Env): Promise<Response> {
  const auth = request.headers.get('Authorization') || '';
  if (!auth.startsWith('Bearer ') || auth.slice(7) !== env.SAID_CHECKED_SEND_SECRET) {
    return json({ error: 'unauthorized' }, 401);
  }
  const { date, subject, html } = await request.json<{ date: string; subject: string; html: string }>();
  if (!date || !DATE_RE.test(date)) return json({ error: 'invalid_date' }, 400);
  if (!subject || !html) return json({ error: 'missing_subject_or_html' }, 400);

  // One email per day: a rerun or a republish of the same day does not send again.
  const sentKey = `sc_sent:${date}`;
  const already = await env.OTP.get(sentKey);
  if (already) return json({ error: 'already_sent', broadcast_id: already }, 409);

  const res = await resend(env, 'POST', '/broadcasts', {
    segment_id: env.SAID_CHECKED_SEGMENT_ID,
    from: FROM,
    subject,
    name: `Said & Checked ${date}`,
    html: html + emailFooter(env),
    send: true,
  });
  if (!res.ok) {
    const text = await res.text();
    console.error('resend error (broadcast)', res.status, text);
    return json({ error: 'broadcast_failed', status: res.status, detail: text }, 502);
  }
  const { id } = await res.json<{ id: string }>();
  await env.OTP.put(sentKey, id);
  return json({ ok: true, broadcast_id: id });
}
