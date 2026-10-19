import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testMatch: '**/*.spec.js',
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: 'http://127.0.0.1:8000', browserName: 'chromium', trace: 'retain-on-failure' },
  webServer: {
    command: 'uv run uvicorn app:app --host 127.0.0.1 --port 8000',
    url: 'http://127.0.0.1:8000/',
    reuseExistingServer: !process.env.CI,
    timeout: 30000
  }
});
