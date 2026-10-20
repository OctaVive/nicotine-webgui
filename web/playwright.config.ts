import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: '../tests/e2e',
  fullyParallel: false,
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:8181', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: {
    command: 'python3 ../dev/mock_bridge.py',
    url: 'http://127.0.0.1:8181/api/v1/health',
    reuseExistingServer: false,
    timeout: 15000,
  },
});
