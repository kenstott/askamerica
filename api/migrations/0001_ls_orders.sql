-- Idempotency + refund ledger for one-time (prepaid) Lemon Squeezy orders.
-- The webhook credits each order exactly once (INSERT OR IGNORE on order_id) and
-- can reverse it on refund. Apply with:
--   wrangler d1 execute askamerica --remote --file api/migrations/0001_ls_orders.sql
CREATE TABLE IF NOT EXISTS ls_orders (
  order_id  TEXT PRIMARY KEY,       -- Lemon Squeezy order id (data.id)
  user_id   TEXT NOT NULL,
  bytes     INTEGER NOT NULL,       -- quota granted by this order
  period    TEXT NOT NULL,          -- YYYY-MM the credit was applied to
  refunded  INTEGER NOT NULL DEFAULT 0
);
