"""Shared local Chrome launch for OfferUp automation.

Uses a persistent Chrome profile at scraper/.chrome-profile-offerup,
anti-automation stealth patches, and both launch + CDP-attach helpers.

The profile is populated once by `python scripts/offerup_login.py` and reused
by the scraper and messenger.
"""

import subprocess
import sys
import time
from pathlib import Path

from playwright.async_api import BrowserContext

CHROME_PROFILE = Path("scraper/.chrome-profile-offerup")

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

// window.chrome is missing in non-Chrome contexts; some sites check for it.
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


def _release_profile_lock() -> None:
    """Kill any Chrome process using the OfferUp profile and remove lock files.

    Chrome uses a SingletonLock file to prevent multiple instances from sharing
    the same user-data-dir. If Chrome is already running with this profile,
    Playwright's launch will fail with "Opening in existing browser session".
    """
    profile = CHROME_PROFILE.resolve()

    # Remove Chrome's lock files so the new instance can claim the profile
    for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        lock_file = profile / lock_name
        try:
            lock_file.unlink(missing_ok=True)
        except Exception:
            pass

    if sys.platform != "win32":
        return

    # On Windows, find and kill Chrome processes using this profile directory
    profile_str = str(profile).lower()
    try:
        # List all chrome.exe processes with their command lines
        result = subprocess.run(
            ["wmic", "process", "where", "name='chrome.exe'", "get",
             "ProcessId,CommandLine", "/format:list"],
            capture_output=True, text=True, timeout=10,
        )
        lines = result.stdout.split("\n")
        pid = None
        cmd = None
        for line in lines:
            line = line.strip()
            if line.startswith("CommandLine="):
                cmd = line
            elif line.startswith("ProcessId="):
                pid = line.split("=", 1)[1].strip()
                # Check if this Chrome process is using our profile
                if cmd and profile_str in cmd.lower():
                    print(f"[browser-offerup] killing Chrome pid={pid} (holds our profile)")
                    subprocess.run(
                        ["taskkill", "/F", "/PID", pid],
                        capture_output=True, timeout=5,
                    )
                pid = None
                cmd = None
        time.sleep(1)  # Give Chrome time to release file locks
    except Exception as e:
        print(f"[browser-offerup] could not check for existing Chrome: {e}")


async def launch_logged_in_chrome(p, *, headless: bool = False) -> BrowserContext:
    """Open the OfferUp-logged-in persistent profile with anti-automation cloak.

    `p` is the result of `async_playwright().__aenter__()`.
    """
    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)

    # Kill any existing Chrome holding this profile to avoid
    # "Opening in existing browser session" errors
    _release_profile_lock()

    context = await p.chromium.launch_persistent_context(
        user_data_dir=str(CHROME_PROFILE.resolve()),
        channel="chrome",
        headless=headless,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        user_agent=CHROME_UA,
        # OfferUp uses account-level location, not JS Geolocation API —
        # no geolocation override needed.
        ignore_default_args=["--enable-automation"],
        args=["--disable-blink-features=AutomationControlled"],
    )
    await context.add_init_script(_STEALTH_INIT_SCRIPT)
    return context


async def attach_to_user_chrome(p, cdp_url: str = "http://localhost:9222") -> BrowserContext:
    """Attach to a Chrome process the user manually started with
    --remote-debugging-port=9222.  Fallback when OfferUp fingerprints the
    Playwright-launched browser despite stealth patches.
    """
    browser = await p.chromium.connect_over_cdp(cdp_url)
    if not browser.contexts:
        raise RuntimeError(
            f"Connected to Chrome at {cdp_url} but no contexts are open. "
            "Make sure Chrome was started with --remote-debugging-port=9222 "
            "and at least one window is open."
        )
    return browser.contexts[0]
