import { defineConfig } from '@playwright/test';

// Presentation checks use mocked API responses, not a running Nicotine+ host.
export default defineConfig({
  testDir: '../tests/ui',
  use: { baseURL: 'http://127.0.0.1:4173', screenshot: 'only-on-failure' },
  webServer: {
    command: 'npm run dev -- --port 4173 --strictPort',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: false,
  },
});
