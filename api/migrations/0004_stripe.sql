-- Billing moved from Lemon Squeezy (stops processing 2027-03-31) to Stripe Managed Payments.
-- The provider ids and the prepaid ledger keep their meaning; only the names change.
-- Apply with:
--   wrangler d1 execute askamerica --remote --file api/migrations/0004_stripe.sql
ALTER TABLE users RENAME COLUMN ls_customer_id TO stripe_customer_id;
ALTER TABLE users RENAME COLUMN ls_subscription_id TO stripe_subscription_id;
ALTER TABLE ls_orders RENAME TO prepaid_orders;
