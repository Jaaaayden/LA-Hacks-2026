import { makeStagehand, requireEnv } from "./session.js";
import { ListingsSchema } from "./schema.js";

export async function searchFacebook(opts) {
  const { query, city, maxPrice, maxResults = 30, scrolls = 3 } = opts;

  const stagehand = makeStagehand({
    contextId: requireEnv("FB_CONTEXT_ID"),
    persist: false,
    proxies: false,
  });

  await stagehand.init();

  try {
    const params = new URLSearchParams({ query });
    if (maxPrice != null) params.set("maxPrice", String(maxPrice));
    const url = `https://www.facebook.com/marketplace/${city}/search/?${params.toString()}`;

    const page = stagehand.context.pages()[0] ?? (await stagehand.context.newPage());
    await page.goto(url, { timeoutMs: 60_000 });
    await page.waitForTimeout(3_000);

    await stagehand.act("dismiss any login or cookie modal if present");

    for (let i = 0; i < scrolls; i++) {
      await stagehand.act("scroll down to load more marketplace listings");
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
