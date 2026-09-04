-- Dynamic per-user "Studies" publishing (distinct from the static, team-curated
-- web/studies/ site built by web/build_studies.py). Apply with:
--   wrangler d1 execute askamerica --remote --file api/migrations/0002_studies.sql
CREATE TABLE IF NOT EXISTS studies_accounts (
  user_id      TEXT PRIMARY KEY,
  handle       TEXT UNIQUE NOT NULL,   -- URL slug, e.g. /studies/<handle>
  display_name TEXT NOT NULL,
  org          TEXT,
  created_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS studies (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL,
  title      TEXT,
  question   TEXT,
  html       TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_studies_user ON studies(user_id, created_at);
