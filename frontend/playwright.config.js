import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";
import { tmpdir } from "node:os";
import { randomUUID } from "node:crypto";

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 60000,
  use: {
    baseURL: "http://127.0.0.1:8011",
    viewport: { width: 1440, height: 1000 },
  },
  webServer: {
    command: "uv run python main.py",
    cwd: resolve(".."),
    url: "http://127.0.0.1:8011/api/health",
    timeout: 60000,
    reuseExistingServer: false,
    env: {
      PORT: "8011",
      AGENTGUARD_DB: resolve(tmpdir(), `agentguard-e2e-${randomUUID()}.db`),
      AGENTGUARD_API_TOKEN: "",
      AGENTGUARD_HOST: "127.0.0.1",
    },
  },
});
