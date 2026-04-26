"""OfferUp login — open Chrome so the user can sign in manually.

Uses Playwright's persistent context with `channel: "chrome"` to match the
exact browser used by the scraper and messenger. Cookies persist to
scraper/.chrome-profile-offerup and are reused across runs.

Usage:
    python scripts/offerup_login.py
"""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

PROFILE_DIR = Path("scraper/.chrome-profile-offerup")
LOGIN_TIMEOUT_S = 6 * 60  # 6 minutes


async def main() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    print("\n=========== OFFERUP LOGIN INSTRUCTIONS ===========")
    print("A Chrome window will open to offerup.com/login.")
    print("Sign in with your email + password.")
    print("The script polls for ~6 min, then closes.")
    print(f"Cookies are saved to {PROFILE_DIR}.")
    print("===================================================\n")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR.resolve()),
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://offerup.com/login")

        deadline = asyncio.get_event_loop().time() + LOGIN_TIMEOUT_S
        logged_in = False

        while asyncio.get_event_loop().time() < deadline:
            url = page.url
            # After successful login OfferUp redirects away from /login
            if (
                "offerup.com" in url
                and "/login" not in url
                and "/register" not in url
                and "/verify" not in url
            ):
                print(f"Detected logged-in URL: {url}")
                logged_in = True
                break
            await asyncio.sleep(2)

        if not logged_in:
            print("Timed out waiting for login. Closing browser anyway.")
        else:
            # Navigate to home to prime session cookies
            await page.goto("https://offerup.com/")
            await asyncio.sleep(4)
            final_url = page.url
            print(f"Home landing URL: {final_url}")
            if "/login" in final_url or "/register" in final_url:
                print("WARNING: home bounced to login. Cookies may not have stuck.")

        await context.close()
        print(f"\nBrowser closed. Cookies saved to {PROFILE_DIR}.")
        print("Next step: python -m backend.services.offerup_scraper \"snowboard\"")


if __name__ == "__main__":
    asyncio.run(main())
