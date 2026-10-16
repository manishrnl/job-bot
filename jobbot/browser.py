"""A persistent, real-Chrome browser session. You log in once by hand; cookies are kept in data/browser_profile."""
import json
import os
import random
import sys
import shutil
import time
from pathlib import Path
from contextlib import contextmanager

from playwright.sync_api import sync_playwright

from .config import BROWSER_DIR, CFG


@contextmanager
def session(headless=None):
    headless = CFG["apply"].get("headless", False) if headless is None else headless
    with sync_playwright() as pw:
        # Playwright adds --use-mock-keychain on macOS, which makes cookies copied from your real Chrome
        # undecryptable. Use the real keychain so `jb use-chrome` logins work.
        kw = dict(user_data_dir=str(BROWSER_DIR), headless=headless, no_viewport=True, chromium_sandbox=True,
                  ignore_default_args=["--use-mock-keychain", "--password-store=basic"],
                  args=["--start-maximized", "--disable-blink-features=AutomationControlled"])
        try:
            ctx = pw.chromium.launch_persistent_context(channel="chrome", **kw)  # your installed Chrome
        except Exception:
            ctx = pw.chromium.launch_persistent_context(**kw)  # bundled Chromium fallback
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            yield pw, ctx, page
        finally:
            ctx.close()


if sys.platform == "darwin":
    CHROME_DIR = Path.home() / "Library/Application Support/Google/Chrome"
elif sys.platform == "win32":
    CHROME_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Google/Chrome/User Data"
else:
    CHROME_DIR = Path.home() / ".config/google-chrome"
SKIP = {"Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache", "GrShaderCache",
        "ShaderCache", "Service Worker", "optimization_guide_model_store", "Crashpad", "component_crx_cache"}


def chrome_profiles():
    """[(dir_name, display_name, account_email)] from your real Chrome."""
    info = json.loads((CHROME_DIR / "Local State").read_text())["profile"]["info_cache"]
    return [(d, v.get("name", ""), v.get("user_name", "")) for d, v in info.items()]


def import_chrome(profile_dir):
    """Copy one of your real Chrome profiles (logins, cookies, extensions) into the bot's browser.

    Chrome 136+ refuses automation on its default data dir, so the bot runs a copy. Same Chrome app,
    same macOS keychain key, so your sessions keep working in the copy.
    """
    src = CHROME_DIR / profile_dir
    if BROWSER_DIR.exists():
        shutil.rmtree(BROWSER_DIR)
    BROWSER_DIR.mkdir(parents=True)
    shutil.copy2(CHROME_DIR / "Local State", BROWSER_DIR / "Local State")
    shutil.copytree(src, BROWSER_DIR / "Default", symlinks=True,
                    ignore=lambda d, names: [n for n in names if n in SKIP or n.endswith((".lock", "LOCK"))],
                    ignore_dangling_symlinks=True)


def pause(a=1.0, b=2.5):
    time.sleep(random.uniform(a, b))
