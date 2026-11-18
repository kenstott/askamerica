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
              STRIPE_WEBHOOK_SECRET: 'test-webhook-secret',
              STRIPE_SECRET_KEY: 'sk_test_unit',
              STRIPE_PRICE_STARTER: 'price_test_starter',
              STRIPE_PRICE_PRO: 'price_test_pro',
              RESEND_API_KEY: 'test-resend',
              ADMIN_SECRET: 'test-admin',
              SAID_CHECKED_SEGMENT_ID: 'seg_test',
              SAID_CHECKED_SEND_SECRET: 'test-send',
              MAIL_POSTAL_ADDRESS: '1 Test St., Testville, NC 00000',
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
