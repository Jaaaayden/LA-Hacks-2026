"""Shared local Chrome launch for FB Marketplace automation.

Both messenger.py and scraper.py drive the same persistent Chrome profile
populated by `node scripts/fb_login.js`. Centralizing the path + launch options
keeps them in sync — drift between the two has bitten us before.
"""

from pathlib import Path

from playwright.async_api import BrowserContext

CHROME_PROFILE = Path("scraper/.chrome-profile")

# UCLA campus — matches the network IP block (164.67.0.0/16). Aligning the
# JS geolocation with the IP's geo helps with FB's consistency check. The
# real "Verify your location" gate is account-level; this is supplementary.
LA_GEO = {"latitude": 34.0689, "longitude": -118.4452}


async def launch_logged_in_chrome(p, *, headless: bool = False) -> BrowserContext:
    """Open the FB-logged-in persistent profile.

    `p` is the result of `async_playwright().__aenter__()`.
    """
    return await p.chromium.launch_persistent_context(
        user_data_dir=str(CHROME_PROFILE.resolve()),
        channel="chrome",
        headless=headless,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        geolocation=LA_GEO,
        permissions=["geolocation"],
    )
