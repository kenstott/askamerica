-- Core schema for the askamerica-api Worker (reconstructed from the code).
-- IF NOT EXISTS so it's a safe no-op against the existing production database.
CREATE TABLE IF NOT EXISTS users (
  id                 TEXT PRIMARY KEY,           -- sha256(lowercased email)
  email              TEXT UNIQUE,
  created_at         INTEGER,
  tier               TEXT NOT NULL DEFAULT 'free',
  ls_customer_id     TEXT,
  ls_subscription_id TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
  key_hash   TEXT PRIMARY KEY,                   -- sha256(api_key)
  user_id    TEXT NOT NULL,
  created_at INTEGER
);

CREATE TABLE IF NOT EXISTS quota_periods (
  user_id     TEXT NOT NULL,
  period      TEXT NOT NULL,                     -- YYYY-MM (UTC)
  limit_bytes INTEGER NOT NULL,
  used_bytes  INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, period)
);
