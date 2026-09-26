-- Adds the `type` field the client already sends (askamerica-engine's report_issue tool
-- classifies every report as "defect" or "sourcing") but the handler was silently dropping —
-- verified live 2026-09-26: handleIssueReport's payload type and INSERT never referenced it.
-- Also adds the bookkeeping columns the new scheduled github-sync.ts job needs to file each
-- row into kenstott/govdata-ops exactly once. Apply with:
--   wrangler d1 execute askamerica --remote --file migrations/0003_issue_type_and_github_sync.sql
--
-- The CREATE TABLE below is IF NOT EXISTS and a no-op against the live database — `issues`
-- has existed there since before this migrations/ folder tracked it (created directly against
-- production, outside any migration file; discovered 2026-09-26 when this migration became the
-- first one to ever reference the table, and `npm test`'s from-scratch D1 build — which only
-- knows about tables created via tracked migrations — failed with "no such table: issues").
-- Its columns match handleIssueReport's INSERT in src/issues.ts exactly.
CREATE TABLE IF NOT EXISTS issues (
  id         TEXT PRIMARY KEY,
  reported_at TEXT,
  stamp      TEXT NOT NULL,
  build      TEXT,
  session_id TEXT,
  user_id    TEXT,
  subject    TEXT NOT NULL,
  body       TEXT NOT NULL
);

ALTER TABLE issues ADD COLUMN type TEXT;
ALTER TABLE issues ADD COLUMN github_issue_number INTEGER;
ALTER TABLE issues ADD COLUMN github_filed_at TEXT;
ALTER TABLE issues ADD COLUMN github_file_error TEXT;

CREATE INDEX IF NOT EXISTS idx_issues_unfiled ON issues(github_issue_number, reported_at);
