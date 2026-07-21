import { Env } from './types';

const OTP_TTL_SECONDS = 600; // 10 minutes
const MAX_OTP_SENDS = 3;          // codes emailed per email address per window
const MAX_OTP_SENDS_PER_IP = 15;  // codes requested per source IP per window
const OTP_SEND_WINDOW = 900;      // 15 minutes
const MAX_VERIFY_ATTEMPTS = 5;    // wrong-code guesses before the code is burned

function currentPeriod(): string {
  const d = new Date();
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

async function sha256hex(input: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

function generateOtp(): string {
  return String(crypto.getRandomValues(new Uint32Array(1))[0] % 1000000).padStart(6, '0');
}

function generateApiKey(tier: string): string {
  const prefix = tier === 'free' ? 'aa_free_' : 'aa_live_';
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  const token = btoa(String.fromCharCode(...bytes)).replace(/[+/=]/g, '');
  return prefix + token;
}

export async function handleRequestOtp(request: Request, env: Env): Promise<Response> {
  const { email } = await request.json<{ email: string }>();
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return json({ error: 'invalid_email' }, 400);
  }
  const emailLc = email.toLowerCase();

  // Abuse control: cap codes emailed per address (email-bombing a victim) and per
  // source IP (mass enumeration). KV is eventually consistent, so this is a soft
  // cap — enough to stop abuse without being an exact quota.
  const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
  const emailSends = parseInt((await env.OTP.get(`otp_send:${emailLc}`)) || '0', 10);
  if (emailSends >= MAX_OTP_SENDS) return json({ error: 'rate_limited' }, 429);
  const ipSends = parseInt((await env.OTP.get(`otp_send_ip:${ip}`)) || '0', 10);
  if (ipSends >= MAX_OTP_SENDS_PER_IP) return json({ error: 'rate_limited' }, 429);

  const code = generateOtp();
  await env.OTP.put(`otp:${emailLc}`, code, { expirationTtl: OTP_TTL_SECONDS });
  // Fresh code → reset the wrong-guess counter for this address.
  await env.OTP.put(`otp_att:${emailLc}`, '0', { expirationTtl: OTP_TTL_SECONDS });
  await env.OTP.put(`otp_send:${emailLc}`, String(emailSends + 1), { expirationTtl: OTP_SEND_WINDOW });
  await env.OTP.put(`otp_send_ip:${ip}`, String(ipSends + 1), { expirationTtl: OTP_SEND_WINDOW });

  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.RESEND_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      from: 'AskAmerica <noreply@askamerica.ai>',
      to: email,
      subject: 'Your AskAmerica access code',
      html: `
        <p>Your AskAmerica access code is:</p>
        <h1 style="letter-spacing:0.3em;font-family:monospace">${code}</h1>
        <p>This code expires in 10 minutes.</p>
        <p>If you didn't request this, you can ignore this email.</p>
        <p>— The AskAmerica Team<br><a href="https://askamerica.ai">askamerica.ai</a></p>
      `,
    }),
  });

  if (!res.ok) {
    console.error('resend error', await res.text());
    return json({ error: 'email_send_failed' }, 502);
  }

  return json({ ok: true });
}

export async function handleVerifyOtp(request: Request, env: Env): Promise<Response> {
  const { email, code } = await request.json<{ email: string; code: string }>();
  if (!email || !code) return json({ error: 'missing_fields' }, 400);

  const emailLc = email.toLowerCase();
  const key = `otp:${emailLc}`;
  const attemptsKey = `otp_att:${emailLc}`;
  const stored = await env.OTP.get(key);
  if (!stored) return json({ error: 'code_expired' }, 401);

  // Brute-force cap: burn the code once too many wrong guesses are made, so the
  // 6-digit space can't be walked within the 10-minute TTL.
  const attempts = parseInt((await env.OTP.get(attemptsKey)) || '0', 10);
  if (attempts >= MAX_VERIFY_ATTEMPTS) {
    await env.OTP.delete(key);
    await env.OTP.delete(attemptsKey);
    return json({ error: 'too_many_attempts' }, 429);
  }

  // constant-time comparison
  const codeBytes = new TextEncoder().encode(code.trim());
  const storedBytes = new TextEncoder().encode(stored);
  let match = codeBytes.length === storedBytes.length;
  let diff = 0;
  for (let i = 0; i < codeBytes.length && match; i++) diff |= codeBytes[i] ^ storedBytes[i];
  if (!match || diff !== 0) {
    await env.OTP.put(attemptsKey, String(attempts + 1), { expirationTtl: OTP_TTL_SECONDS });
    return json({ error: 'invalid_code' }, 401);
  }

  await env.OTP.delete(key);
  await env.OTP.delete(attemptsKey);

  // upsert user
  const userId = await sha256hex(email.toLowerCase());
  const now = Date.now();
  await env.DB.prepare(`
    INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)
    ON CONFLICT(email) DO NOTHING
  `).bind(userId, email.toLowerCase(), now).run();

  // issue free key
  const apiKey = generateApiKey('free');
  const keyHash = await sha256hex(apiKey);
  await env.DB.prepare(`
    INSERT INTO api_keys (key_hash, user_id, created_at) VALUES (?, ?, ?)
  `).bind(keyHash, userId, now).run();

  // fast-path KV lookup
  await env.KEYS.put(keyHash, userId);

  // seed quota record for current period
  const period = currentPeriod();
  await env.DB.prepare(`
    INSERT INTO quota_periods (user_id, period, limit_bytes, used_bytes) VALUES (?, ?, ?, 0)
    ON CONFLICT(user_id, period) DO NOTHING
  `).bind(userId, period, 1 * 1024 * 1024 * 1024).run();

  return json({ api_key: apiKey, tier: 'free', quota_gb: 1 });
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
