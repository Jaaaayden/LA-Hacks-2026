import "dotenv/config";
import { Stagehand } from "@browserbasehq/stagehand";
import { resolve } from "node:path";
import { mkdirSync } from "node:fs";

/** Directory where the local Chromium stores cookies / localStorage.
 *  Persists FB login across runs — same idea as Browserbase Contexts
 *  but free and your own IP (so FB location check passes).            */
const DEFAULT_USER_DATA_DIR = resolve("scraper/.chrome-profile");

/**
 * Create a Stagehand instance.
 *
 * Defaults to LOCAL mode so the browser runs on your machine with your
 * home IP — this avoids the "Verify your location" block that happens
 * when Browserbase's datacenter IP doesn't match your phone.
 *
 * Set `env: "BROWSERBASE"` in opts to use cloud mode (requires paid
 * plan for proxies / geolocation).
 */
export function makeStagehand(opts = {}) {
  const {
    env = "LOCAL",
    contextId,
    persist = true,
    keepAlive = false,
    headless = false,
    userDataDir = DEFAULT_USER_DATA_DIR,
  } = opts;

  if (!process.env.ANTHROPIC_API_KEY) {
    throw new Error("ANTHROPIC_API_KEY is required. Set it in .env.");
  }

  const model = {
    modelName: "anthropic/claude-sonnet-4-5",
    apiKey: process.env.ANTHROPIC_API_KEY,
  };

  // ── LOCAL mode ─────────────────────────────────────────────────────
  if (env === "LOCAL") {
    mkdirSync(userDataDir, { recursive: true });
    return new Stagehand({
      env: "LOCAL",
      model,
      localBrowserLaunchOptions: {
        headless,
        userDataDir,
        preserveUserDataDir: true,
        viewport: { width: 1280, height: 900 },
      },
    });
  }

  // ── BROWSERBASE mode (requires paid plan for proxies) ──────────────
  return new Stagehand({
    env: "BROWSERBASE",
    apiKey: requireEnv("BROWSERBASE_API_KEY"),
    projectId: requireEnv("BROWSERBASE_PROJECT_ID"),
    model,
    keepAlive,
    browserbaseSessionCreateParams: {
      projectId: requireEnv("BROWSERBASE_PROJECT_ID"),
      keepAlive,
      browserSettings: contextId
        ? { context: { id: contextId, persist } }
        : undefined,
    },
  });
}

export function requireEnv(name) {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}
