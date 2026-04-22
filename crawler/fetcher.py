"""
DAIS Crawler - Multi-Layer Stealth Fetcher
Mimics how ScrapingBee/Browserless works internally.

Fetch strategy (waterfall — each layer only triggered if previous fails/blocked):

  Layer 1 — curl_cffi (Chrome TLS fingerprint + real headers)
             Beats: TLS fingerprinting, basic header checks, most WAFs
             Speed: ~200-500ms

  Layer 2 — Stealth Playwright (headless Chrome, navigator.webdriver patched,
             human-like scroll + timing)
             Beats: JS challenges, navigator checks, basic Cloudflare
             Speed: ~3-8s

  Layer 3 — Playwright with full human simulation
             (random delays, mouse movement, scroll behaviour)
             Beats: behavioural bot detection, advanced Cloudflare
             Speed: ~5-12s

Block detection: 403, 401, 429, empty body, known block page patterns
"""

import time
import random
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup


# ─────────────────────────────────────────────
# Real Chrome user agents (rotated per request)
# ─────────────────────────────────────────────

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.86 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]
_ua_index = 0

def _next_ua() -> str:
    global _ua_index
    ua = _USER_AGENTS[_ua_index % len(_USER_AGENTS)]
    _ua_index += 1
    return ua


# ─────────────────────────────────────────────
# Shared realistic HTTP headers
# ─────────────────────────────────────────────

def _make_headers(ua: str) -> dict:
    return {
        "User-Agent":                ua,
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language":           "en-US,en;q=0.9",
        "Accept-Encoding":           "gzip, deflate, br",
        "Sec-Ch-Ua":                 '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile":          "?0",
        "Sec-Ch-Ua-Platform":        '"Windows"',
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "none",
        "Sec-Fetch-User":            "?1",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control":             "max-age=0",
        "Connection":                "keep-alive",
    }


# ─────────────────────────────────────────────
# Block detection
# ─────────────────────────────────────────────

# Known block-page content patterns
_BLOCK_PATTERNS = [
    r"access denied",
    r"403 forbidden",
    r"cloudflare.*ray id",
    r"please enable.*javascript.*to continue",
    r"checking your browser",
    r"ddos protection",
    r"just a moment",            # Cloudflare JS challenge
    r"enable javascript",
    r"bot.*detected",
    r"unusual traffic",
    r"captcha",
    r"verify you are human",
    r"security check",
    r"blocked",
]

def _is_blocked(html: str, status_code: int) -> tuple[bool, str]:
    """Returns (is_blocked, reason)"""
    if status_code in (403, 401, 429, 503):
        return True, f"HTTP {status_code}"

    if not html or len(html.strip()) < 200:
        return True, "empty/tiny response"

    html_lower = html.lower()
    for pattern in _BLOCK_PATTERNS:
        if re.search(pattern, html_lower):
            return True, f"block pattern: '{pattern}'"

    return False, ""


# ─────────────────────────────────────────────
# SPA / JS-render detection
# ─────────────────────────────────────────────

_SPA_MARKERS = [
    '_next/static', 'id="__NEXT_DATA__"', "id='__NEXT_DATA__'",
    '___gatsby', '__nuxt', '_nuxt/', '__remixContext',
    'ng-version', 'ng-app', 'astro-island',
    'id="root"', 'id="app"', '__vue',
]

def _needs_js_render(html: str) -> bool:
    """True if page looks like a JS-rendered SPA shell."""
    html_lower = html.lower()
    for marker in _SPA_MARKERS:
        if marker.lower() in html_lower:
            return True
    try:
        soup = BeautifulSoup(html, "lxml")
        body = soup.find("body")
        if not body:
            return True
        text   = body.get_text(separator=" ", strip=True)
        has_h1    = bool(soup.find("h1"))
        has_title = bool(soup.find("title") and soup.find("title").get_text(strip=True))
        has_links = len(soup.find_all("a", href=True)) > 3
        if len(text) > 400 and sum([has_h1, has_title, has_links]) < 2:
            return True
        if len(text) < 400:
            return True
    except Exception:
        return True
    return False


# ─────────────────────────────────────────────
# Layer 1 — curl_cffi (Chrome TLS fingerprint)
# ─────────────────────────────────────────────

def _fetch_layer1_curlffi(url: str, timeout: int = 15) -> dict:
    """
    Uses curl_cffi to impersonate Chrome's exact TLS fingerprint.
    This beats Cloudflare TLS fingerprinting that defeats plain requests/httpx.
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return {"success": False, "error": "curl_cffi not installed", "status_code": 0,
                "html": "", "response_headers": {}, "load_time_ms": 0,
                "page_size_kb": 0, "final_url": url, "redirect_count": 0, "rendered_via": "curl_cffi"}

    ua      = _next_ua()
    headers = _make_headers(ua)
    start   = time.time()

    try:
        resp = cffi_requests.get(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
            impersonate="chrome124",   # ← key: matches Chrome's TLS cipher suite + extensions order
            verify=False,
        )
        load_time_ms = int((time.time() - start) * 1000)
        html         = resp.text
        page_size_kb = round(len(resp.content) / 1024, 2)

        return {
            "success":          True,
            "html":             html,
            "status_code":      resp.status_code,
            "response_headers": dict(resp.headers),
            "load_time_ms":     load_time_ms,
            "page_size_kb":     page_size_kb,
            "final_url":        str(resp.url),
            "redirect_count":   len(resp.history),
            "rendered_via":     "curl_cffi",
            "error":            None,
        }
    except Exception as e:
        return {
            "success": False, "error": str(e), "status_code": 0,
            "html": "", "response_headers": {}, "load_time_ms": int((time.time() - start) * 1000),
            "page_size_kb": 0, "final_url": url, "redirect_count": 0, "rendered_via": "curl_cffi",
        }


# ─────────────────────────────────────────────
# Playwright stealth init script
# ─────────────────────────────────────────────

_STEALTH_SCRIPT = """
// 1. Hide webdriver flag (most important check)
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// 2. Spoof plugins (headless has 0, real Chrome has many)
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', filename: 'internal-nacl-plugin' },
        ];
        plugins.__proto__ = PluginArray.prototype;
        return plugins;
    }
});

// 3. Spoof languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

// 4. Add window.chrome (missing in headless)
window.chrome = {
    app: { isInstalled: false, getDetails: () => {}, getIsInstalled: () => {} },
    runtime: {
        PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux' },
        PlatformArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
        RequestUpdateCheckStatus: { THROTTLED: 'throttled', NO_UPDATE: 'no_update', UPDATE_AVAILABLE: 'update_available' },
        OnInstalledReason: { INSTALL: 'install', UPDATE: 'update', CHROME_UPDATE: 'chrome_update' },
        OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
        connect: () => {}, sendMessage: () => {}, id: undefined,
    },
    loadTimes: () => {},
    csi: () => {},
};

// 5. Spoof permissions API
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);

// 6. Realistic screen dimensions
Object.defineProperty(screen, 'availWidth',  { get: () => 1280 });
Object.defineProperty(screen, 'availHeight', { get: () => 800  });
Object.defineProperty(screen, 'width',       { get: () => 1280 });
Object.defineProperty(screen, 'height',      { get: () => 800  });

// 7. Hide automation in iframe contentWindow
Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
    get: function() {
        const win = this.__proto__.__proto__.contentWindow.call(this);
        if (win) {
            Object.defineProperty(win.navigator, 'webdriver', { get: () => undefined });
        }
        return win;
    }
});
"""


# ─────────────────────────────────────────────
# Layer 2 — Stealth Playwright (standard)
# ─────────────────────────────────────────────

def _fetch_layer2_playwright(url: str, timeout: int = 30) -> dict:
    """Headless Chrome with full stealth patches. No human simulation."""
    from playwright.sync_api import sync_playwright

    start = time.time()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--disable-extensions",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--window-size=1280,800",
                    "--disable-web-security",
                    "--allow-running-insecure-content",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )

            ua      = _next_ua()
            context = browser.new_context(
                user_agent=ua,
                viewport={"width": 1280, "height": 800},
                java_script_enabled=True,
                locale="en-US",
                timezone_id="America/New_York",
                device_scale_factor=1,
                has_touch=False,
                extra_http_headers=_make_headers(ua),
            )

            page = context.new_page()
            page.add_init_script(_STEALTH_SCRIPT)

            response_headers = {}
            status_code      = 200

            def on_response(resp):
                nonlocal response_headers, status_code
                if resp.url.rstrip("/") == url.rstrip("/"):
                    response_headers = dict(resp.headers)
                    status_code = resp.status

            page.on("response", on_response)

            try:
                page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            except Exception:
                pass  # grab whatever rendered

            html         = page.content()
            final_url    = page.url
            load_time_ms = int((time.time() - start) * 1000)
            page_size_kb = round(len(html.encode()) / 1024, 2)
            browser.close()

        return {
            "success": True, "html": html,
            "status_code": status_code or 200,
            "response_headers": response_headers,
            "load_time_ms": load_time_ms, "page_size_kb": page_size_kb,
            "final_url": final_url, "redirect_count": 0,
            "rendered_via": "playwright_stealth", "error": None,
        }
    except Exception as e:
        return {
            "success": False, "error": str(e), "status_code": 0,
            "html": "", "response_headers": {},
            "load_time_ms": int((time.time() - start) * 1000),
            "page_size_kb": 0, "final_url": url, "redirect_count": 0,
            "rendered_via": "playwright_stealth",
        }


# ─────────────────────────────────────────────
# Layer 3 — Playwright with human simulation
# ─────────────────────────────────────────────

def _fetch_layer3_human(url: str, timeout: int = 45) -> dict:
    """
    Full human behaviour simulation:
    - Random wait before interaction
    - Mouse movement across viewport
    - Gradual scroll down and back up
    - Random micro-pauses between actions
    Beats advanced behavioural bot detection.
    """
    from playwright.sync_api import sync_playwright

    start = time.time()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--window-size=1366,768",
                    "--no-first-run",
                ],
            )

            ua      = _next_ua()
            context = browser.new_context(
                user_agent=ua,
                viewport={"width": 1366, "height": 768},
                java_script_enabled=True,
                locale="en-US",
                timezone_id="America/Chicago",
                device_scale_factor=1,
                has_touch=False,
                extra_http_headers=_make_headers(ua),
            )

            page = context.new_page()
            page.add_init_script(_STEALTH_SCRIPT)

            response_headers = {}
            status_code      = 200

            def on_response(resp):
                nonlocal response_headers, status_code
                if resp.url.rstrip("/") == url.rstrip("/"):
                    response_headers = dict(resp.headers)
                    status_code = resp.status

            page.on("response", on_response)

            # Navigate
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            except Exception:
                pass

            # ── Human simulation ────────────────────────────────────
            # 1. Random pause after load (humans don't act instantly)
            time.sleep(random.uniform(1.2, 2.8))

            # 2. Move mouse from corner to center in a curve
            page.mouse.move(0, 0)
            time.sleep(random.uniform(0.05, 0.15))
            page.mouse.move(
                random.randint(300, 700),
                random.randint(100, 300),
            )
            time.sleep(random.uniform(0.1, 0.3))

            # 3. Gradual scroll down (read behaviour)
            scroll_steps = random.randint(3, 6)
            page_height  = page.evaluate("() => document.body.scrollHeight") or 1000
            for i in range(scroll_steps):
                scroll_to = int((page_height / scroll_steps) * (i + 1))
                page.evaluate(f"window.scrollTo({{top: {scroll_to}, behavior: 'smooth'}})")
                time.sleep(random.uniform(0.3, 0.8))

            # 4. Pause at bottom (reading)
            time.sleep(random.uniform(0.5, 1.5))

            # 5. Scroll back up (common user behaviour)
            page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
            time.sleep(random.uniform(0.3, 0.7))

            # 6. Wait for any lazy-loaded content
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            html         = page.content()
            final_url    = page.url
            load_time_ms = int((time.time() - start) * 1000)
            page_size_kb = round(len(html.encode()) / 1024, 2)
            browser.close()

        return {
            "success": True, "html": html,
            "status_code": status_code or 200,
            "response_headers": response_headers,
            "load_time_ms": load_time_ms, "page_size_kb": page_size_kb,
            "final_url": final_url, "redirect_count": 0,
            "rendered_via": "playwright_human", "error": None,
        }
    except Exception as e:
        return {
            "success": False, "error": str(e), "status_code": 0,
            "html": "", "response_headers": {},
            "load_time_ms": int((time.time() - start) * 1000),
            "page_size_kb": 0, "final_url": url, "redirect_count": 0,
            "rendered_via": "playwright_human",
        }


# ─────────────────────────────────────────────
# Main fetch_page — waterfall strategy
# ─────────────────────────────────────────────

def fetch_page(url: str, force_playwright: bool = False) -> dict:
    """
    Waterfall fetch strategy — escalates through layers until we get
    a clean, unblocked response with real page content.

    Layer 1 → curl_cffi (Chrome TLS fingerprint)  — fast, beats most WAFs
    Layer 2 → Playwright stealth                   — JS rendering + navigator patches
    Layer 3 → Playwright + human simulation        — behavioural bot detection bypass
    """
    if not url.startswith("http"):
        url = "https://" + url

    # ── Layer 1: curl_cffi ─────────────────────────────────────────
    if not force_playwright:
        print(f"  [L1] curl_cffi fetch → {url}")
        result = _fetch_layer1_curlffi(url)

        if result["success"]:
            blocked, reason = _is_blocked(result["html"], result["status_code"])

            if not blocked and not _needs_js_render(result["html"]):
                print(f"  [L1] ✓ Clean response ({result['status_code']}, {result['page_size_kb']}KB, {result['load_time_ms']}ms)")
                return result

            if blocked:
                print(f"  [L1] Blocked: {reason} — escalating to L2")
            else:
                print(f"  [L1] Needs JS render — escalating to L2")
        else:
            print(f"  [L1] Failed: {result['error']} — escalating to L2")

    # ── Layer 2: Stealth Playwright ────────────────────────────────
    print(f"  [L2] Stealth Playwright → {url}")
    result = _fetch_layer2_playwright(url)

    if result["success"]:
        blocked, reason = _is_blocked(result["html"], result["status_code"])

        if not blocked:
            print(f"  [L2] ✓ Clean response ({result['status_code']}, {result['page_size_kb']}KB, {result['load_time_ms']}ms)")
            return result

        print(f"  [L2] Still blocked: {reason} — escalating to L3 (human simulation)")
    else:
        print(f"  [L2] Failed: {result['error']} — escalating to L3")

    # ── Layer 3: Human simulation ──────────────────────────────────
    print(f"  [L3] Human simulation Playwright → {url}")
    result = _fetch_layer3_human(url)

    blocked, reason = _is_blocked(result["html"], result["status_code"])
    if result["success"] and not blocked:
        print(f"  [L3] ✓ Clean response ({result['status_code']}, {result['page_size_kb']}KB, {result['load_time_ms']}ms)")
    else:
        print(f"  [L3] Still blocked after all layers: {reason}")
        # Tag it so the caller knows — don't crash, return what we have
        result["blocked"] = True
        result["block_reason"] = reason

    return result
