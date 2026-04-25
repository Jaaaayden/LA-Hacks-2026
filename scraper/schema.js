import { z } from "zod";

export const ListingSchema = z.object({
  title: z.string().describe("Item title as shown on the listing"),
  price: z.number().describe("Numeric price in USD; 0 if not listed"),
  location: z.string().describe("City or neighborhood shown under the title"),
  url: z.string().describe("Absolute URL to the listing detail page"),
  imageUrl: z.string().nullable().describe("Primary image URL if visible"),
});

export const ListingsSchema = z.object({
  listings: z.array(ListingSchema),
});
