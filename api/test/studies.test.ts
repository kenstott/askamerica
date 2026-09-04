import { env } from 'cloudflare:test';
import { describe, it, expect } from 'vitest';
import {
  handleStudiesRegister, handleStudiesMe, handleStudiesUpload, handleStudyDelete,
  handleStudiesIndex, handleStudyPage,
} from '../src/studies';

const E = env as any;

// ── helpers ──────────────────────────────────────────────────────────────────
async function sha256hex(s: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}

let seq = 0;
async function seedUser() {
  const email = `u${seq++}@test.dev`;
  const userId = await sha256hex(email.toLowerCase());
  const apiKey = `aa_test_${userId.slice(0, 12)}`;
  const keyHash = await sha256hex(apiKey);
  await E.DB.prepare('INSERT OR REPLACE INTO users (id,email,created_at,tier) VALUES (?,?,?,?)')
    .bind(userId, email, Date.now(), 'free').run();
  await E.DB.prepare('INSERT OR REPLACE INTO api_keys (key_hash,user_id,created_at) VALUES (?,?,?)')
    .bind(keyHash, userId, Date.now()).run();
  await E.KEYS.put(keyHash, userId);
  return { email, userId, apiKey };
}

function register(apiKey: string, name: string, org?: string): Promise<Response> {
  return handleStudiesRegister(new Request('http://x/v1/studies/register', {
    method: 'POST',
    headers: { 'X-API-Key': apiKey, 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, org }),
  }), env);
}

function upload(apiKey: string, body: object): Promise<Response> {
  return handleStudiesUpload(new Request('http://x/v1/studies/reports', {
    method: 'POST',
    headers: { 'X-API-Key': apiKey, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }), env);
}

function me(apiKey: string): Promise<Response> {
  return handleStudiesMe(new Request('http://x/v1/studies/me', {
    headers: { 'X-API-Key': apiKey },
  }), env);
}

function del(apiKey: string, id: string): Promise<Response> {
  return handleStudyDelete(new Request(`http://x/v1/studies/reports/${id}`, {
    method: 'DELETE',
    headers: { 'X-API-Key': apiKey },
  }), env, id);
}

// ── tests ────────────────────────────────────────────────────────────────────
describe('register', () => {
  it('requires an API key', async () => {
    const r = await register('', 'Jane Ortiz');
    expect(r.status).toBe(401);
  });

  it('rejects an unknown key', async () => {
    const r = await register('not-a-real-key', 'Jane Ortiz');
    expect(r.status).toBe(401);
  });

  it('creates an account and returns a studies URL keyed off the org', async () => {
    const { apiKey } = await seedUser();
    const r = await register(apiKey, 'Jane Ortiz', 'Ortiz Policy Lab');
    expect(r.status).toBe(200);
    const body = await r.json<{ studiesUrl: string }>();
    expect(body.studiesUrl).toBe('https://ortiz-policy-lab.askamerica.ai/index');
  });

  it('falls back to the display name when no org is given', async () => {
    const { apiKey } = await seedUser();
    const r = await register(apiKey, 'Jane Ortiz');
    const body = await r.json<{ studiesUrl: string }>();
    expect(body.studiesUrl).toBe('https://jane-ortiz.askamerica.ai/index');
  });

  it('re-registering keeps the same handle', async () => {
    const { apiKey } = await seedUser();
    const first = await (await register(apiKey, 'Jane Ortiz')).json<{ studiesUrl: string }>();
    const second = await (await register(apiKey, 'Jane O. Ortiz', 'New Org')).json<{ studiesUrl: string }>();
    expect(second.studiesUrl).toBe(first.studiesUrl);
  });

  it('dedupes handles across two accounts with the same display name', async () => {
    const a = await seedUser();
    const b = await seedUser();
    const ra = await (await register(a.apiKey, 'Jane Ortiz')).json<{ studiesUrl: string }>();
    const rb = await (await register(b.apiKey, 'Jane Ortiz')).json<{ studiesUrl: string }>();
    expect(ra.studiesUrl).not.toBe(rb.studiesUrl);
  });
});

describe('mysite (/v1/studies/me)', () => {
  it('404s when not registered', async () => {
    const { apiKey } = await seedUser();
    const r = await me(apiKey);
    expect(r.status).toBe(404);
  });

  it('returns the studies URL once registered', async () => {
    const { apiKey } = await seedUser();
    await register(apiKey, 'Jane Ortiz');
    const r = await me(apiKey);
    expect(r.status).toBe(200);
    expect((await r.json<{ studiesUrl: string }>()).studiesUrl)
      .toBe('https://jane-ortiz.askamerica.ai/index');
  });
});

describe('upload_report (/v1/studies/reports)', () => {
  it('404s when the caller has not registered', async () => {
    const { apiKey } = await seedUser();
    const r = await upload(apiKey, { title: 't', question: 'q', html: '<html><body>x</body></html>' });
    expect(r.status).toBe(404);
  });

  it('rejects an empty html body', async () => {
    const { apiKey } = await seedUser();
    await register(apiKey, 'Jane Ortiz');
    const r = await upload(apiKey, { title: 't', question: 'q', html: '' });
    expect(r.status).toBe(400);
  });

  it('uploads and returns a report URL under the account handle', async () => {
    const { apiKey } = await seedUser();
    await register(apiKey, 'Jane Ortiz');
    const r = await upload(apiKey, {
      title: 'Wages vs inflation', question: 'Did real wages rise?',
      html: '<!doctype html><html><body><h1>hi</h1></body></html>',
    });
    expect(r.status).toBe(200);
    const body = await r.json<{ url: string }>();
    expect(body.url).toMatch(/^https:\/\/jane-ortiz\.askamerica\.ai\/[^/]+$/);
  });
});

describe('public pages', () => {
  it('index lists uploaded reports newest first, labeled by question', async () => {
    const { apiKey } = await seedUser();
    await register(apiKey, 'Jane Ortiz');
    await upload(apiKey, { title: 'First', question: 'Q1', html: '<html><body>1</body></html>' });
    await upload(apiKey, { title: 'Second', question: 'Q2', html: '<html><body>2</body></html>' });

    const r = await handleStudiesIndex(new Request('http://x/studies/jane-ortiz'), env, 'jane-ortiz');
    expect(r.status).toBe(200);
    const text = await r.text();
    expect(text.indexOf('Q2')).toBeLessThan(text.indexOf('Q1'));
  });

  it('index 404s for an unknown handle', async () => {
    const r = await handleStudiesIndex(new Request('http://x/studies/nobody'), env, 'nobody');
    expect(r.status).toBe(404);
  });

  it('report page splices a back-link banner into the stored HTML', async () => {
    const { apiKey } = await seedUser();
    await register(apiKey, 'Jane Ortiz');
    const up = await (await upload(apiKey, {
      title: 'T', question: 'Q', html: '<!doctype html><html><body><h1>hi</h1></body></html>',
    })).json<{ url: string }>();
    const id = up.url.split('/').pop()!;

    const r = await handleStudyPage(new Request('http://x/studies/jane-ortiz/' + id), env, 'jane-ortiz', id);
    expect(r.status).toBe(200);
    const text = await r.text();
    expect(text).toContain('Back to this Studies page');
    expect(text).toContain('<h1>hi</h1>');
  });

  it('report page 404s for a report belonging to a different handle', async () => {
    const a = await seedUser();
    const b = await seedUser();
    await register(a.apiKey, 'Jane Ortiz');
    await register(b.apiKey, 'Bob Smith');
    const up = await (await upload(a.apiKey, {
      title: 'T', question: 'Q', html: '<html><body>x</body></html>',
    })).json<{ url: string }>();
    const id = up.url.split('/').pop()!;

    const r = await handleStudyPage(new Request('http://x/studies/bob-smith/' + id), env, 'bob-smith', id);
    expect(r.status).toBe(404);
  });
});

describe('delete', () => {
  it('owner can delete their own report', async () => {
    const { apiKey } = await seedUser();
    await register(apiKey, 'Jane Ortiz');
    const up = await (await upload(apiKey, {
      title: 'T', question: 'Q', html: '<html><body>x</body></html>',
    })).json<{ url: string }>();
    const id = up.url.split('/').pop()!;

    const r = await del(apiKey, id);
    expect(r.status).toBe(200);

    const page = await handleStudyPage(new Request('http://x/studies/jane-ortiz/' + id), env, 'jane-ortiz', id);
    expect(page.status).toBe(404);
  });

  it('a non-owner cannot delete another account\'s report', async () => {
    const a = await seedUser();
    const b = await seedUser();
    await register(a.apiKey, 'Jane Ortiz');
    await register(b.apiKey, 'Bob Smith');
    const up = await (await upload(a.apiKey, {
      title: 'T', question: 'Q', html: '<html><body>x</body></html>',
    })).json<{ url: string }>();
    const id = up.url.split('/').pop()!;

    const r = await del(b.apiKey, id);
    expect(r.status).toBe(403);
  });

  it('404s for an unknown report id', async () => {
    const { apiKey } = await seedUser();
    await register(apiKey, 'Jane Ortiz');
    const r = await del(apiKey, 'no-such-id');
    expect(r.status).toBe(404);
  });
});
