import { defineConfig } from "@playwright/test";

// End-to-end tests drive the real app in a headless browser.
// Needs the backend (port 8000) and `npm run dev` (port 5173) running, and the
// demo accounts:  cd backend && python -m app.scripts.seed_demo --yes
// Run:  npm run e2e        (screenshots end up in e2e/screenshots/)
export default defineConfig({
  testDir: "e2e",
  timeout: 180_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    // Uses the Chrome already installed on the machine (no browser download).
    // E2E_CHANNEL=msedge for Edge, or "chromium" after `npx playwright install chromium`.
    channel: process.env.E2E_CHANNEL ?? "chrome",
    headless: true,
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    viewport: { width: 1280, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
