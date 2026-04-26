/**
 * fb_verify.js — Open a marketplace listing in the persistent Chrome profile
 * so you can manually complete the "Verify your location" step.
 *
 * Steps:
 *   1. Run: node scripts/fb_verify.js
 *   2. A Chrome window opens to a Marketplace listing
 *   3. Click "Message" on any listing
 *   4. When the "Verify your location" popup appears, click OK
 *   5. Open the Facebook app on your phone and share your location
 *   6. Come back to this browser — it should let you message now
 *   7. Close the browser (Ctrl+C or just close the window)
 *
 * After this, the verification is saved in .chrome-profile and the
 * agent can message autonomously without hitting the popup again.
 */
import "dotenv/config";
import { chromium } from "playwright";
import { resolve } from "node:path";
import { mkdirSync } from "node:fs";

const PROFILE_DIR = resolve("scraper/.chrome-profile");

async function main() {
  mkdirSync(PROFILE_DIR, { recursive: true });

  console.log(`\n=========== LOCATION VERIFICATION ===========`);
  console.log(`A Chrome window will open to FB Marketplace.`);
  console.log(`1. Click "Message" on any listing`);
  console.log(`2. Complete the "Verify your location" step`);
  console.log(`3. Open the Facebook app on your phone → share location`);
  console.log(`4. Once verified, close this window or press Ctrl+C`);
  console.log(`===============================================\n`);

  const context = await chromium.launchPersistentContext(PROFILE_DIR, {
    channel: "chrome",
    headless: false,
    viewport: { width: 1280, height: 900 },
    locale: "en-US",
  });

  const page = context.pages()[0] ?? (await context.newPage());
  await page.goto("https://www.facebook.com/marketplace/");

  // Keep the browser open until user closes it
  await new Promise((resolve) => {
    context.on("close", resolve);
    process.on("SIGINT", async () => {
      console.log("\nClosing browser...");
      await context.close();
      resolve();
    });
  });

  console.log("Browser closed. Verification should be saved.");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
