export interface Env {
  // KV namespaces
  KEYS:  KVNamespace;   // sha256(api_key) → user_id
  QUOTA: KVNamespace;   // "{user_id}:{period}" → QuotaRecord JSON
  OTP:   KVNamespace;   // "otp:{email}" → code (10 min TTL)

  // D1
  DB: D1Database;

  // Analytics Engine
  ANALYTICS: AnalyticsEngineDataset;
  TELEMETRY: AnalyticsEngineDataset;  // MCP tool telemetry — separate event shape

  // Secrets (set via: wrangler secret put <NAME>)
  RESEND_API_KEY: string;
  R2_ACCESS_KEY_ID: string;      // parent R2 access key id (for temp-cred minting)
  R2_SECRET_ACCESS_KEY: string;  // parent R2 secret (never shipped to clients)
  R2_ACCOUNT_ID: string;
  R2_BUCKET: string;
  R2_TEMP_TOKEN: string;         // Cloudflare API token to mint scoped temp R2 creds
  STRIPE_WEBHOOK_SECRET: string; // Stripe webhook endpoint signing secret (whsec_...)
  STRIPE_SECRET_KEY: string;     // Stripe key (mints checkouts, reads customers)
  ADMIN_SECRET: string;         // shared secret for admin key issuance
  GITHUB_TOKEN: string;         // PAT w/ repo:issues scope on kenstott/govdata-ops (github-sync.ts)

  // Vars
  ENVIRONMENT: string;
  STRIPE_PRICE_STARTER: string;  // Stripe price id of the Starter plan
  STRIPE_PRICE_PRO: string;      // Stripe price id of the Pro plan
}

export interface QuotaRecord {
  limit_bytes: number;
  used_bytes:  number;
  period:      string; // 'YYYY-MM'
}

export const TIER_LIMITS: Record<string, number> = {
  free:     1   * 1024 * 1024 * 1024,         // 1 GB
  starter:  50  * 1024 * 1024 * 1024,         // 50 GB
  pro:      500 * 1024 * 1024 * 1024,         // 500 GB
  internal: Number.MAX_SAFE_INTEGER,           // unlimited
};
