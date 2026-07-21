export interface Env {
  // KV namespaces
  KEYS:  KVNamespace;   // sha256(api_key) → user_id
  QUOTA: KVNamespace;   // "{user_id}:{period}" → QuotaRecord JSON
  OTP:   KVNamespace;   // "otp:{email}" → code (10 min TTL)

  // D1
  DB: D1Database;

  // Analytics Engine
  ANALYTICS: AnalyticsEngineDataset;

  // Secrets (set via: wrangler secret put <NAME>)
  RESEND_API_KEY: string;
  R2_ACCESS_KEY_ID: string;      // parent R2 access key id (for temp-cred minting)
  R2_SECRET_ACCESS_KEY: string;  // parent R2 secret (never shipped to clients)
  R2_ACCOUNT_ID: string;
  R2_BUCKET: string;
  R2_TEMP_TOKEN: string;         // Cloudflare API token to mint scoped temp R2 creds
  LS_WEBHOOK_SECRET: string;    // Lemon Squeezy webhook signing secret
  LEMONSQUEEZY_API_KEY: string; // Lemon Squeezy API key (mints checkouts)
  ADMIN_SECRET: string;         // shared secret for admin key issuance

  // Vars
  ENVIRONMENT: string;
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

// Maps Lemon Squeezy variant id -> tier. Includes both live and test ids so the
// webhook attributes correctly in either mode.
export const LS_VARIANT_TIERS: Record<string, string> = {
  "1285257": "starter",  // live
  "1667060": "pro",      // live
  "1934204": "starter",  // test
  "1934205": "pro",      // test
};
