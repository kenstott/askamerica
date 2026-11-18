import { env, fetchMock } from 'cloudflare:test';
import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import { handleSaidSubscribe, handleSaidConfirm, handleSaidSend } from '../src/said-and-checked';

const E = env as any;
const RESEND = 'https://api.resend.com';

beforeAll(() => { fetchMock.activate(); fetchMock.disableNetConnect(); });
afterEach(() => fetchMock.assertNoPendingInterceptors());

function subscribe(email: string, ip = '203.0.113.1'): Promise<Response> {
  return handleSaidSubscribe(new Request('https://api.askamerica.ai/v1/said-and-checked/subscribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'CF-Connecting-IP': ip },
    body: JSON.stringify({ email }),
  }), env);
}

function confirm(token: string): Promise<Response> {
  return handleSaidConfirm(new Request(
    `https://api.askamerica.ai/v1/said-and-checked/confirm?token=${token}`), env);
}

function send(body: object, secret = 'test-admin'): Promise<Response> {
  return handleSaidSend(new Request('https://api.askamerica.ai/v1/said-and-checked/send', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${secret}` },
    body: JSON.stringify(body),
  }), env);
}

/** Subscribes and returns the token from the confirmation link Resend was asked to send. */
async function subscribeAndGetToken(email: string): Promise<string> {
  let sent: any;
  fetchMock.get(RESEND).intercept({ path: '/emails', method: 'POST' })
    .reply(200, (opts: any) => { sent = JSON.parse(opts.body); return { id: 'em_1' }; });
  expect((await subscribe(email)).status).toBe(200);
  expect(sent.to).toBe(email.toLowerCase());
  const m = /confirm\?token=([0-9a-f]{64})/.exec(sent.html);
  expect(m).not.toBeNull();
  return m![1];
}

describe('subscribe', () => {
  it('rejects a malformed address without sending', async () => {
    expect((await subscribe('not-an-email')).status).toBe(400);
  });

  it('sends a confirmation email and stores nothing at Resend', async () => {
    const token = await subscribeAndGetToken('New@Example.com');
    expect(await E.OTP.get(`sc_confirm:${token}`)).toBe('new@example.com');
  });

  it('caps confirmation emails per address', async () => {
    for (let i = 0; i < 3; i++) await subscribeAndGetToken('capped@example.com');
    expect((await subscribe('capped@example.com')).status).toBe(429);
  });

  it('reports a Resend failure instead of claiming success', async () => {
    fetchMock.get(RESEND).intercept({ path: '/emails', method: 'POST' }).reply(500, 'down');
    expect((await subscribe('down@example.com')).status).toBe(502);
  });
});

describe('confirm', () => {
  it('creates a new contact in the segment and burns the token', async () => {
    const token = await subscribeAndGetToken('fresh@example.com');
    fetchMock.get(RESEND).intercept({ path: '/contacts/fresh%40example.com', method: 'PATCH' })
      .reply(404, { message: 'not found' });
    let created: any;
    fetchMock.get(RESEND).intercept({ path: '/contacts', method: 'POST' })
      .reply(200, (opts: any) => { created = JSON.parse(opts.body); return { id: 'c_1' }; });
    const r = await confirm(token);
    expect(r.status).toBe(200);
    expect(created).toEqual({ email: 'fresh@example.com', unsubscribed: false, segments: [{ id: 'seg_test' }] });
    expect(await E.OTP.get(`sc_confirm:${token}`)).toBeNull();
    expect((await confirm(token)).status).toBe(410);
  });

  it('resubscribes a known contact and adds it to the segment', async () => {
    const token = await subscribeAndGetToken('back@example.com');
    fetchMock.get(RESEND).intercept({ path: '/contacts/back%40example.com', method: 'PATCH' })
      .reply(200, { id: 'c_2' });
    fetchMock.get(RESEND).intercept({ path: '/contacts/back%40example.com/segments/seg_test', method: 'POST' })
      .reply(200, { id: 'seg_test' });
    expect((await confirm(token)).status).toBe(200);
  });

  it('keeps the token when Resend fails, so the link can be retried', async () => {
    const token = await subscribeAndGetToken('retry@example.com');
    fetchMock.get(RESEND).intercept({ path: '/contacts/retry%40example.com', method: 'PATCH' })
      .reply(500, 'down');
    expect((await confirm(token)).status).toBe(502);
    expect(await E.OTP.get(`sc_confirm:${token}`)).toBe('retry@example.com');
  });

  it('rejects a malformed token', async () => {
    expect((await confirm('abc')).status).toBe(400);
  });
});

describe('send', () => {
  it('requires the admin secret', async () => {
    expect((await send({ date: '2026-11-17', subject: 's', html: 'h' }, 'wrong')).status).toBe(401);
  });

  it('sends one broadcast per day, with the unsubscribe link and postal address', async () => {
    let body: any;
    fetchMock.get(RESEND).intercept({ path: '/broadcasts', method: 'POST' })
      .reply(200, (opts: any) => { body = JSON.parse(opts.body); return { id: 'b_1' }; });
    const r = await send({ date: '2026-11-17', subject: 'Said & Checked, 2026-11-17', html: '<p>day</p>' });
    expect(r.status).toBe(200);
    expect(body.segment_id).toBe('seg_test');
    expect(body.send).toBe(true);
    expect(body.html.startsWith('<p>day</p>')).toBe(true);
    expect(body.html).toContain('{{{RESEND_UNSUBSCRIBE_URL}}}');
    expect(body.html).toContain('1 Test St., Testville, NC 00000');

    const again = await send({ date: '2026-11-17', subject: 's', html: 'h' });
    expect(again.status).toBe(409);
    expect((await again.json<any>()).broadcast_id).toBe('b_1');
  });

  it('does not mark the day sent when the broadcast fails', async () => {
    fetchMock.get(RESEND).intercept({ path: '/broadcasts', method: 'POST' }).reply(422, 'bad');
    expect((await send({ date: '2026-11-18', subject: 's', html: 'h' })).status).toBe(502);
    expect(await E.OTP.get('sc_sent:2026-11-18')).toBeNull();
  });
});
