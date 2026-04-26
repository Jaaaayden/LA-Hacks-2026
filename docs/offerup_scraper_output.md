# OfferUp Scraper Output

The OfferUp scraper prints or saves a JSON object with query metadata and an
array of enriched listings. Search results come from OfferUp's GraphQL feed, and
each listing is enriched by parsing the item detail page's embedded Next.js data.

Example command:

```bash
python -m backend.services.offerup_scraper "snowboard" --location 90024 --min-price 2 --max-price 300 --max-results 5 --save snowboard_90024.json
```

## Top-Level Shape

```json
{
  "query": {
    "query": "snowboard",
    "minPrice": 2,
    "maxPrice": 300
  },
  "listings": []
}
```

## Listing Shape

Each entry in `listings` has this normalized shape:

```json
{
  "title": "BURTON SNOWBOARD",
  "price": 100.0,
  "location": "Huntington Park, CA",
  "url": "https://offerup.com/item/detail/e9f3b6d8-05cb-310a-a4c5-6411561487b0",
  "image_url": "https://images.offerup.com/...jpg",
  "condition": null,
  "description": "I have a used Burton snowboard good condition",
  "condition_code": 40,
  "post_date": "2026-04-26T00:54:41.421Z",
  "state": "LISTED",
  "is_removed": false,
  "is_local": true,
  "is_firm_on_price": false,
  "quantity": 1,
  "photos": [
    {
      "uuid": "6d545f46417449c4ae763f3f747cb927",
      "detail_url": "https://images.offerup.com/.../250x333/....jpg",
      "full_url": "https://images.offerup.com/.../615x820/....jpg",
      "square_url": "https://images.offerup.com/.../615x615/....jpg",
      "list_url": "https://images.offerup.com/.../250x250/....jpg"
    }
  ],
  "seller": {
    "id": 168587733,
    "name": "Lia Lopez",
    "avatar_url": "https://d2fa3j67sd1nwo.cloudfront.net/images/default-avatar-small-v2.png",
    "public_location": "Walnut Park, CA",
    "date_joined": "2026-04-16T20:53:28Z",
    "last_active": "Active a few hours ago",
    "items_sold": "0",
    "items_purchased": "0",
    "response_time": "",
    "rating_average": 0,
    "rating_count": 0,
    "is_truyou_verified": null,
    "is_business_account": false
  },
  "category": {
    "id": "7.9",
    "name": "Ice & Snow sports",
    "l1_name": "Sports & Outdoors",
    "l2_name": "Ice & Snow sports",
    "l3_name": null,
    "attributes": [
      {
        "name": "brand",
        "label": "Brand",
        "value": ["Burton"],
        "priority": 1
      }
    ]
  },
  "fulfillment": {
    "local_pickup_enabled": true,
    "shipping_enabled": false,
    "can_ship_to_buyer": false,
    "buy_it_now_enabled": false,
    "seller_pays_shipping": false,
    "shipping_price": null
  },
  "distance": {
    "value": 14.71,
    "unit": "MILE"
  },
  "location_detail": {
    "name": "Huntington Park, CA",
    "latitude": "33.985",
    "longitude": "-118.207"
  }
}
```

## Field Notes

- `query.query`: the OfferUp search text.
- `query.minPrice`: the price floor sent to OfferUp and rechecked locally by the scraper. Defaults to `2` to filter out `$0`/`$1` bait listings.
- `query.maxPrice`: the local price ceiling applied by the scraper. `null` means no price ceiling.
- `price`: parsed numeric USD price.
- `location`: OfferUp's display location for the listing.
- `description`: item-page description from the listing detail page.
- `condition`: human-readable search-card condition text when OfferUp provides it. This is often `null`.
- `condition_code`: OfferUp's numeric condition value.
- `photos`: image URLs at several OfferUp sizes.
- `seller`: normalized seller profile data.
- `category.attributes[].priority`: OfferUp's display/order priority for that category attribute. Lower values appear to be more important.
- `fulfillment`: local pickup / shipping / buy-now flags.
- `distance`: distance from the requested search location, usually in miles.
- `location_detail`: listing location coordinates and display name from the detail page.

## Known Condition Codes

| Code | Meaning |
| --- | --- |
| `10` | New (best guess) |
| `20` | Open box / Like new (best guess) |
| `30` | Good (best guess) |
| `40` | Used (normal wear) |
| `50` | For parts / poor condition (best guess) |

Only `40 = Used (normal wear)` has been observed directly so far. Treat the
other mappings as working guesses until we verify them against real listings.
