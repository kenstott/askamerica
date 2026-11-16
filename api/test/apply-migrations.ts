import { applyD1Migrations, env } from 'cloudflare:test';

// Apply the D1 migrations (schema + prepaid_orders) to the isolated test database
// before the suite runs.
await applyD1Migrations(env.DB, (env as any).TEST_MIGRATIONS);
