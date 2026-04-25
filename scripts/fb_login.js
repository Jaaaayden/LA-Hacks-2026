import "dotenv/config";
import { Browserbase } from "@browserbasehq/sdk";
import { Stagehand } from "@browserbasehq/stagehand";
import { writeFileSync, readFileSync, existsSync } from "node:fs";
import { requireEnv } from "../scraper/session.js";

const ENV_PATH = ".env";
const LOGIN_TIMEOUT_MS = 6 * 60_000;

async function main() {
  const apiKey = requireEnv("BROWSERBASE_API_KEY");
  const projectId = requireEnv("BROWSERBASE_PROJECT_ID");
  if (!process.env.ANTHROPIC_API_KEY) {
    throw new Error("ANTHROPIC_API_KEY is required. Set it in .env.");
  }

  const bb = new Browserbase({ apiKey });

  let contextId = process.env.FB_CONTEXT_ID;
  if (!contextId) {
    console.log("Creating new Browserbase Context...");
    const ctx = await bb.contexts.create({ projectId });
    contextId = ctx.id;
    persistEnv("FB_CONTEXT_ID", contextId);
    console.log(`Saved FB_CONTEXT_ID=${contextId} to .env`);
  } else {
    console.log(`Reusing FB_CONTEXT_ID=${contextId}`);
  }

  const stagehand = new Stagehand({
    env: "BROWSERBASE",
    apiKey,
    projectId,
    model: { modelName: "anthropic/claude-sonnet-4-5", apiKey: process.env.ANTHROPIC_API_KEY },
    keepAlive: true,
    browserbaseSessionCreateParams: {
      projectId,
      keepAlive: true,
      browserSettings: { context: { id: contextId, persist: true } },
    },
  });

  await stagehand.init();
  const sessionId = stagehand.sessionId;

  console.log(`\n=========== LOGIN INSTRUCTIONS ===========`);
  console.log(`Open the live view in your browser:`);
  console.log(`  https://www.browserbase.com/sessions/${sessionId ?? "(open Browserbase dashboard, latest session)"}`);
  console.log(`Then sign in to Facebook with your BURNER account.`);
  console.log(`The script polls for ~6 min, then saves cookies into the Context.`);
  console.log(`==========================================\n`);

  const page = stagehand.context.pages()[0] ?? (await stagehand.context.newPage());
  await page.goto("https://www.facebook.com/login");

  const deadline = Date.now() + LOGIN_TIMEOUT_MS;
  let loggedIn = false;
  while (Date.now() < deadline) {
    const url = page.url();
    if (
      url.startsWith("https://www.facebook.com/") &&
      !url.includes("/login") &&
      !url.includes("/checkpoint") &&
      !url.includes("/recover")
    ) {
      console.log(`Detected logged-in URL: ${url}`);
      loggedIn = true;
      break;
    }
    await page.waitForTimeout(2_000);
  }

  if (!loggedIn) {
    console.warn("Timed out waiting for login. Closing session anyway.");
  } else {
    await page.goto("https://www.facebook.com/marketplace/");
    await page.waitForTimeout(4_000);
    const finalUrl = page.url();
    console.log(`Marketplace landing URL: ${finalUrl}`);
    if (finalUrl.includes("/login") || finalUrl.includes("/checkpoint")) {
      console.warn("WARNING: marketplace bounced to login. Cookies may not have stuck.");
    }
  }

  await stagehand.close();
  console.log("\nSession closed. Context cookies saved.");
  console.log("Next step: npm run fb:scrape");
}

function persistEnv(key, value) {
  let body = existsSync(ENV_PATH) ? readFileSync(ENV_PATH, "utf8") : "";
  if (new RegExp(`^${key}=`, "m").test(body)) {
    body = body.replace(new RegExp(`^${key}=.*$`, "m"), `${key}=${value}`);
  } else {
    body += `\n${key}=${value}\n`;
  }
  writeFileSync(ENV_PATH, body);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
