// The directory is a static page reading a static feed, so the whole test needs
// nothing but a file server over the repository root: mockup/index.html fetches
// ../data/, which is the committed feed.
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 30000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://127.0.0.1:8799',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'python3 -m http.server 8799',
    url: 'http://127.0.0.1:8799/mockup/index.html',
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
  },
});
