import "dotenv/config";
import { searchFacebook } from "../scraper/facebook.js";
import { writeFileSync, mkdirSync } from "node:fs";

const QUERIES = [
  { query: "snowboard", city: "losangeles", maxPrice: 300 },
  { query: "snowboard boots size 10", city: "losangeles", maxPrice: 150 },
  { query: "snowboard bindings", city: "losangeles", maxPrice: 120 },
  { query: "ski goggles", city: "losangeles", maxPrice: 60 },
];

async function main() {
  mkdirSync("scraper/output", { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");

  for (const q of QUERIES) {
    console.log(`\n=== ${q.query} (${q.city}, <=$${q.maxPrice}) ===`);
    try {
      const listings = await searchFacebook({ ...q, maxResults: 20 });
      console.log(`Got ${listings.length} listings`);
      for (const l of listings.slice(0, 5)) {
        console.log(`  - $${l.price} | ${l.title} | ${l.location}`);
      }
      const out = `scraper/output/${stamp}_${q.query.replace(/\s+/g, "-")}.json`;
      writeFileSync(out, JSON.stringify({ query: q, listings }, null, 2));
      console.log(`Wrote ${out}`);
    } catch (e) {
      console.error(`FAILED:`, e);
    }
  }
}

main().then(() => process.exit(0)).catch(() => process.exit(1));
