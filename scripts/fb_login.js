/**
 * fb_login.js — Open system Chrome to facebook.com/login.
 *
 * Uses Playwright's `launch_persistent_context` with `channel: "chrome"`
 * to match the exact browser that Stagehand's chrome-launcher uses.
 * Cookies persist to scraper/.chrome-profile and are reused by both
 * the JS scraper (Stagehand LOCAL) and the Python messenger.
 */
import "dotenv/config";
import { chromium } from "playwright";
import { resolve } from "node:path";
import { mkdirSync } from "node:fs";

const PROFILE_DIR = resolve("scraper/.chrome-profile");
const LOGIN_TIMEOUT_MS = 6 * 60_000;

async function main() {
  mkdirSync(PROFILE_DIR, { recursive: true });

  console.log(`\n=========== LOGIN INSTRUCTIONS ===========`);
  console.log(`A Chrome window will open to facebook.com/login.`);
  console.log(`Sign in with your BURNER account.`);
  console.log(`The script polls for ~6 min, then closes.`);
  console.log(`Cookies are saved to scraper/.chrome-profile.`);
  console.log(`==========================================\n`);

  const context = await chromium.launchPersistentContext(PROFILE_DIR, {
    channel: "chrome",      // use system Chrome (same as chrome-launcher)
    headless: false,
    viewport: { width: 1280, height: 900 },
    locale: "en-US",
  });

  const page = context.pages()[0] ?? (await context.newPage());
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
    console.warn("Timed out waiting for login. Closing browser anyway.");
  } else {
    // Navigate to Marketplace to prime those cookies too
    await page.goto("https://www.facebook.com/marketplace/");
    await page.waitForTimeout(4_000);
    const finalUrl = page.url();
    console.log(`Marketplace landing URL: ${finalUrl}`);
    if (finalUrl.includes("/login") || finalUrl.includes("/checkpoint")) {
      console.warn("WARNING: marketplace bounced to login. Cookies may not have stuck.");
    }
  }

  await context.close();
  console.log("\nBrowser closed. Cookies saved to scraper/.chrome-profile.");
  console.log("Next step: npm run fb:scrape");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
