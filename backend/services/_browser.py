"""Shared local Chrome launch for FB Marketplace automation.

Both messenger.py and scraper.py drive the same persistent Chrome profile
populated by `node scripts/fb_login.js`. Centralizing the path + launch options
keeps them in sync — drift between the two has bitten us before.

Anti-automation patches: FB fingerprints Playwright sessions via the
--enable-automation flag and `navigator.webdriver`. We strip the flag at
launch and patch the navigator props at every page load via add_init_script.
This is the playwright-stealth subset relevant to FB's checks; hand-rolled
to avoid pulling another dep.
"""

from pathlib import Path

from playwright.async_api import BrowserContext

CHROME_PROFILE = Path("scraper/.chrome-profile")

# UCLA campus — matches the network IP block (164.67.0.0/16). Aligning the
# JS geolocation with the IP's geo helps with FB's consistency check.
LA_GEO = {"latitude": 34.0689, "longitude": -118.4452}

# Recent stable Chrome user-agent. Bump occasionally to stay current.
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_STEALTH_INIT_SCRIPT = """
// Hide the webdriver flag — set in real Chrome but exposed by Playwright.
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Real Chrome reports a non-empty plugin list; Playwright's is empty.
Object.defineProperty(navigator, 'plugins', {
  get: () => [
    { name: 'PDF Viewer' },
    { name: 'Chrome PDF Viewer' },
    { name: 'Chromium PDF Viewer' },
    { name: 'Microsoft Edge PDF Viewer' },
    { name: 'WebKit built-in PDF' },
  ],
});

// Languages array sometimes empty under headless/automation.
Object.defineProperty(navigator, 'languages', {
  get: () => ['en-US', 'en'],
});

// window.chrome is missing in non-Chrome contexts; FB checks for it.
window.chrome = window.chrome || { runtime: {}, loadTimes: () => ({}), csi: () => ({}) };

// Permissions.query for notifications returns "denied" under automation
// but "default" in real browsers — patch to default.
const _origQuery = window.navigator.permissions && window.navigator.permissions.query;
if (_origQuery) {
  window.navigator.permissions.query = (params) =>
    params && params.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : _origQuery(params);
}
"""


async def launch_logged_in_chrome(p, *, headless: bool = False) -> BrowserContext:
    """Open the FB-logged-in persistent profile with anti-automation cloak.

    `p` is the result of `async_playwright().__aenter__()`.
    """
    context = await p.chromium.launch_persistent_context(
        user_data_dir=str(CHROME_PROFILE.resolve()),
        channel="chrome",
        headless=headless,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        user_agent=CHROME_UA,
        geolocation=LA_GEO,
        permissions=["geolocation"],
        # Drop --enable-automation and the AutomationControlled blink feature.
        # Without these, navigator.webdriver still reads `true` even on real
        # Chrome — combined with the init script below, it becomes `undefined`.
        ignore_default_args=["--enable-automation"],
        args=["--disable-blink-features=AutomationControlled"],
    )
    await context.add_init_script(_STEALTH_INIT_SCRIPT)
    return context


async def attach_to_user_chrome(p, cdp_url: str = "http://localhost:9222") -> BrowserContext:
    """Attach to a Chrome process the user manually started with
    --remote-debugging-port=9222. Used as the Layer 3 fallback when FB still
    fingerprints the Playwright-launched browser despite stealth patches.

    The browser IS the user's real Chrome — same cookies, history, fingerprint —
    so FB has no reason to gate it. Caveat: shares state with the user's normal
    browsing; don't run unattended.
    """
    browser = await p.chromium.connect_over_cdp(cdp_url)
    if not browser.contexts:
        raise RuntimeError(
            f"Connected to Chrome at {cdp_url} but no contexts are open. "
            "Make sure Chrome was started with --remote-debugging-port=9222 "
            "and at least one window is open."
        )
    return browser.contexts[0]
