import { defineWorkersConfig, readD1Migrations } from '@cloudflare/vitest-pool-workers/config';

export default defineWorkersConfig(async () => {
  const migrations = await readD1Migrations('./migrations');
  return {
    test: {
      setupFiles: ['./test/apply-migrations.ts'],
      poolOptions: {
        workers: {
          singleWorker: true,
          isolatedStorage: true,
          wrangler: { configPath: './wrangler.toml' },
          miniflare: {
            // Test-only secrets/bindings (D1/KV/AE/vars come from wrangler.toml).
            bindings: {
              TEST_MIGRATIONS: migrations,
              LS_WEBHOOK_SECRET: 'test-webhook-secret',
              LEMONSQUEEZY_API_KEY: 'test-ls-key',
              RESEND_API_KEY: 'test-resend',
              ADMIN_SECRET: 'test-admin',
              R2_ACCOUNT_ID: 'test-acct',
              R2_BUCKET: 'test-bucket',
              R2_ACCESS_KEY_ID: 'test-akid',
              R2_SECRET_ACCESS_KEY: 'test-secret',
              R2_TEMP_TOKEN: 'test-temp',
            },
          },
        },
      },
    },
  };
});
