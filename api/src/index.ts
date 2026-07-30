import { Env } from './types';
import { handleRequestOtp, handleVerifyOtp } from './auth';
import { handleUsageReport, handleQuotaStatus } from './metering';
import { handleLemonSqueezyWebhook } from './webhook';
import { handleCheckout } from './checkout';
import { handleCredentials } from './credentials';
import { handleAdminCreateKey, handleAdminGrant } from './admin';
import { handleIssueReport } from './issues';
import { handleTelemetry } from './telemetry';

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

    let response: Response;

    if (method === 'POST' && path === '/v1/auth/request-otp') {
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
    } else {
      response = notFound();
    }

    return cors(response);
  },
};
