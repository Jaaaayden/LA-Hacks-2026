import { makeStagehand } from "./session.js";
import { ListingsSchema } from "./schema.js";

export async function searchFacebook(opts) {
  const { query, city, maxPrice, maxResults = 30, scrolls = 3 } = opts;

  const stagehand = makeStagehand();

  await stagehand.init();

  try {
    const params = new URLSearchParams({ query });
    if (maxPrice != null) params.set("maxPrice", String(maxPrice));
    const url = `https://www.facebook.com/marketplace/${city}/search/?${params.toString()}`;

    const page = stagehand.context.pages()[0] ?? (await stagehand.context.newPage());
    await page.goto(url, { timeoutMs: 60_000 });
    await page.waitForTimeout(3_000);

    // Dismiss all popups (notifications, cookies, login modals)
    const dismissSelectors = [
      '[aria-label="Not Now"]',             // "Turn on notifications?" → Not Now
      '[aria-label="Block"]',               // notification block button
      '[aria-label="Close"]',               // generic close (X) button
      '[aria-label="Decline optional cookies"]',
      'div[role="dialog"] [aria-label="Close"]',
    ];
    for (const sel of dismissSelectors) {
      try {
        const btn = page.locator(sel).first();
        if (await btn.isVisible({ timeout: 1000 })) {
          await btn.click();
          await page.waitForTimeout(500);
        }
      } catch (_) { /* not present, move on */ }
    }

    // Scroll with native JS instead of act() (deterministic, free)
    for (let i = 0; i < scrolls; i++) {
      await page.evaluate(() => window.scrollBy(0, 1500));
      await page.waitForTimeout(1_500 + Math.random() * 1_500);
    }

    const result = await stagehand.extract(
      "Extract every visible Facebook Marketplace listing card on this page. " +
        "For each card, return its title, numeric price (USD, 0 if free), " +
        "location text shown under the title, the absolute URL of the listing, " +
        "and the primary image URL if visible.",
      ListingsSchema,
    );

    return (result.listings ?? []).slice(0, maxResults);
  } finally {
    await stagehand.close();
  }
}
