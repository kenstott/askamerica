import { Env } from './types';
import { handleRequestOtp, handleVerifyOtp } from './auth';
import { handleUsageReport, handleQuotaStatus } from './metering';
import { handleLemonSqueezyWebhook } from './webhook';
import { handleCheckout } from './checkout';
import { handleCredentials } from './credentials';
import { handleAdminCreateKey, handleAdminGrant } from './admin';
import { handleIssueReport } from './issues';
import { handleTelemetry } from './telemetry';
import {
  handleStudiesRegister, handleStudiesMe, handleStudiesUpload, handleStudyDelete,
  handleStudiesIndex, handleStudyPage, STUDIES_ROOT_DOMAIN, RESERVED_HANDLES,
} from './studies';

/**
 * Extracts the handle from a Host header like "carol-ortiz.askamerica.ai", or null for
 * anything else — the apex domain (the Pages site), api.askamerica.ai (this Worker's own
 * JSON API), a workers.dev host (local/dev), or a reserved name that was never handed
 * out as a handle in the first place (see RESERVED_HANDLES in studies.ts).
 */
function subdomainHandle(host: string): string | null {
  const suffix = '.' + STUDIES_ROOT_DOMAIN;
  if (!host.endsWith(suffix)) return null;
  const sub = host.slice(0, -suffix.length);
  if (!sub || sub.includes('.') || RESERVED_HANDLES.has(sub)) return null;
  return sub;
}

function cors(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.set('Access-Control-Allow-Origin', '*');
  headers.set('Access-Control-Allow-Headers', 'Content-Type, X-API-Key, Authorization');
  return new Response(response.body, { status: response.status, headers });
}

function notFound(): Response {
  return new Response(JSON.stringify({ error: 'not_found' }), {
    status: 404,
    headers: { 'Content-Type': 'application/json' },
  });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type, X-API-Key, Authorization',
        },
      });
    }

    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;
    const handle = subdomainHandle(url.hostname);

    let response: Response;

    if (handle && method === 'GET' && path === '/index') {
      response = await handleStudiesIndex(request, env, handle);
    } else if (handle && method === 'GET' && path.match(/^\/[^/]+$/)) {
      response = await handleStudyPage(request, env, handle, path.slice(1));
    } else if (method === 'POST' && path === '/v1/auth/request-otp') {
      response = await handleRequestOtp(request, env);
    } else if (method === 'POST' && path === '/v1/auth/verify-otp') {
      response = await handleVerifyOtp(request, env);
    } else if (method === 'POST' && path === '/v1/metering/usage') {
      ctx.waitUntil(handleUsageReport(request, env));
      response = new Response(JSON.stringify({ ok: true }), {
        headers: { 'Content-Type': 'application/json' },
      });
    } else if (method === 'GET' && path === '/v1/quota') {
      response = await handleQuotaStatus(request, env);
    } else if (method === 'GET' && path === '/v1/checkout') {
      response = await handleCheckout(request, env);
    } else if (method === 'POST' && path === '/v1/webhooks/lemonsqueezy') {
      response = await handleLemonSqueezyWebhook(request, env);
    } else if (method === 'GET' && path === '/v1/catalog/credentials') {
      response = await handleCredentials(request, env);
    } else if (method === 'POST' && path === '/v1/telemetry') {
      // Awaited, despite this being fire-and-forget for the client. writeDataPoint does
      // no I/O in the request path, so deferring bought no latency -- and returning a
      // canned ok meant the stamp filter could not reject, so the route answered 200 to
      // any POST and advertised itself.
      response = await handleTelemetry(request, env);
    } else if (method === 'POST' && path === '/v1/issues') {
      // Awaited, unlike metering's waitUntil: the caller has just written up a report and
      // must be told whether it was stored, rather than getting an unconditional ok.
      response = await handleIssueReport(request, env);
    } else if (method === 'POST' && path === '/v1/admin/keys') {
      response = await handleAdminCreateKey(request, env);
    } else if (method === 'POST' && path === '/v1/admin/grant') {
      response = await handleAdminGrant(request, env);
    } else if (method === 'POST' && path === '/v1/studies/register') {
      response = await handleStudiesRegister(request, env);
    } else if (method === 'GET' && path === '/v1/studies/me') {
      response = await handleStudiesMe(request, env);
    } else if (method === 'POST' && path === '/v1/studies/reports') {
      response = await handleStudiesUpload(request, env);
    } else if (method === 'DELETE' && path.match(/^\/v1\/studies\/reports\/[^/]+$/)) {
      response = await handleStudyDelete(request, env, path.split('/').pop()!);
    } else if (method === 'GET' && path.match(/^\/studies\/[^/]+\/[^/]+$/)) {
      const [, , handle, id] = path.split('/');
      response = await handleStudyPage(request, env, handle, id);
    } else if (method === 'GET' && path.match(/^\/studies\/[^/]+\/?$/)) {
      const handle = path.split('/')[2];
      response = await handleStudiesIndex(request, env, handle);
    } else {
      response = notFound();
    }

    return cors(response);
  },
};
