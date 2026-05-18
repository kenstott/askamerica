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
  R2_ACCESS_KEY_ID: string;
  R2_SECRET_ACCESS_KEY: string;
  R2_ACCOUNT_ID: string;
  R2_BUCKET: string;
  LS_WEBHOOK_SECRET: string;   // LemonSqueezy webhook signing secret

  // Vars
  ENVIRONMENT: string;
}

export interface QuotaRecord {
  limit_bytes: number;
  used_bytes:  number;
  period:      string; // 'YYYY-MM'
}

export const TIER_LIMITS: Record<string, number> = {
  free:    1  * 1024 * 1024 * 1024,  // 1 GB
  starter: 50 * 1024 * 1024 * 1024,  // 50 GB
  pro:     500 * 1024 * 1024 * 1024, // 500 GB
};

export const LS_VARIANT_TIERS: Record<string, string> = {
  "1285257": "starter",
  "1667060": "pro",
};
