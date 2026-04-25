import "dotenv/config";
import { Stagehand } from "@browserbasehq/stagehand";

export function makeStagehand(opts = {}) {
  const { contextId, persist = true, proxies = false, keepAlive = false } = opts;

  if (!process.env.ANTHROPIC_API_KEY) {
    throw new Error("ANTHROPIC_API_KEY is required. Set it in .env.");
  }

  return new Stagehand({
    env: "BROWSERBASE",
    apiKey: requireEnv("BROWSERBASE_API_KEY"),
    projectId: requireEnv("BROWSERBASE_PROJECT_ID"),
    model: {
      modelName: "anthropic/claude-sonnet-4-5",
      apiKey: process.env.ANTHROPIC_API_KEY,
    },
    keepAlive,
    browserbaseSessionCreateParams: {
      projectId: requireEnv("BROWSERBASE_PROJECT_ID"),
      proxies,
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
