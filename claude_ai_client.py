#!/usr/bin/env python3
"""
Claude.ai RE Client v4 — REST/SSE Security Research Tool
Features: Real-time streaming, model selection, stealth mode, credit optimizer.
Architecture: Capture creds once → Replay via CLI (no browser during prompts).
v4: Dynamic timezone, secure CDP (localhost-only), encrypted credential path.
"""
import argparse, json, os, re, sys, uuid, time, copy, subprocess, shutil, threading
import datetime, socket, stat

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except: pass

# ═══════════════════════════════════════════════════════════
#  DEPENDENCY CHECK
# ═══════════════════════════════════════════════════════════

try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

try:
    import requests as std_requests
except ImportError:
    std_requests = None

if not HAS_CFFI and not std_requests:
    print("[!] pip install curl_cffi")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════
#  CONSTANTS & MODELS
# ═══════════════════════════════════════════════════════════

DIR       = os.path.dirname(os.path.abspath(__file__))
PROFILE   = os.path.join(DIR, "claude_profile")

# Credential storage: outside repo in user config directory
if sys.platform == "win32":
    _CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "claude_re")
else:
    _CONFIG_DIR = os.path.expanduser("~/.config/claude_re")
os.makedirs(_CONFIG_DIR, exist_ok=True)
CRED_FILE = os.path.join(_CONFIG_DIR, "claude_session.json")

URL_BASE  = "https://claude.ai"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36")
DEFAULT_MODEL = "claude-sonnet-4-6"

# Verified models (tested against claude.ai endpoint 2026-04-24)
# FREE = works on free tier, PRO = needs Pro/Max subscription
MODEL_ALIASES = {
    # ── Current generation (FREE) ─────────────
    "haiku":        "claude-haiku-4-5",
    "sonnet":       "claude-sonnet-4-6",          # latest, default
    "sonnet-4-5":   "claude-sonnet-4-5",          # previous sonnet
    # ── Dated snapshots (FREE) ────────────────
    "haiku-snap":   "claude-haiku-4-5-20251001",
    "sonnet-snap":  "claude-sonnet-4-5-20250929",
    # ── Premium (PRO/MAX only) ────────────────
    "opus":         "claude-opus-4-7",
    "opus-3":       "claude-3-opus-20240229",
}

def resolve_model(name):
    """Resolve shorthand or full model name."""
    if name in MODEL_ALIASES:
        return MODEL_ALIASES[name]
    return name  # pass through as-is

def _detect_timezone():
    """Detect system IANA timezone. Falls back to UTC with warning."""
    # Method 1: Python 3.9+ datetime.astimezone()
    try:
        tz = datetime.datetime.now().astimezone().tzinfo
        # Python 3.9+ has .key on ZoneInfo objects
        if hasattr(tz, 'key'):
            return tz.key
        # tzname() may return IANA on some systems
        name = tz.tzname(datetime.datetime.now())
        if name and '/' in name:
            return name
    except: pass

    # Method 2: try tzlocal (if installed)
    try:
        from tzlocal import get_localzone
        tz = str(get_localzone())
        if tz and '/' in tz:
            return tz
    except ImportError: pass

    # Method 3: Windows registry
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation")
            tz_name, _ = winreg.QueryValueEx(key, "TimeZoneKeyName")
            winreg.CloseKey(key)
            # Map common Windows timezone names to IANA
            _win_to_iana = {
                "India Standard Time": "Asia/Kolkata",
                "Eastern Standard Time": "America/New_York",
                "Pacific Standard Time": "America/Los_Angeles",
                "Central Standard Time": "America/Chicago",
                "Mountain Standard Time": "America/Denver",
                "GMT Standard Time": "Europe/London",
                "Central European Standard Time": "Europe/Berlin",
                "Tokyo Standard Time": "Asia/Tokyo",
                "China Standard Time": "Asia/Shanghai",
                "AUS Eastern Standard Time": "Australia/Sydney",
            }
            if tz_name in _win_to_iana:
                return _win_to_iana[tz_name]
        except: pass

    # Method 4: /etc/timezone (Linux)
    try:
        with open("/etc/timezone") as f:
            tz = f.read().strip()
            if tz and '/' in tz:
                return tz
    except: pass

    print("[!] WARNING: Could not detect system timezone. Falling back to UTC.")
    return "Etc/UTC"

SYSTEM_TIMEZONE = _detect_timezone()

PAYLOAD_TEMPLATE = {
    "prompt": "",
    "model": DEFAULT_MODEL,
    "timezone": SYSTEM_TIMEZONE,
    "locale": "en-US",
    "rendering_mode": "messages",
    "turn_message_uuids": {
        "human_message_uuid": "",
        "assistant_message_uuid": ""
    },
    "attachments": [],
    "files": [],
    "sync_sources": []
}


# ═══════════════════════════════════════════════════════════
#  CREDENTIAL MANAGER
# ═══════════════════════════════════════════════════════════

class CredentialManager:
    """Manages Claude.ai session credentials (org_id, conv_id, cookies)."""

    def __init__(self):
        self.org_id = None
        self.conv_id = None
        self.cookies = {}
        self.session_key = None

    # ── Persistence ──────────────────────────────────────

    def load(self):
        if not os.path.exists(CRED_FILE):
            return False
        with open(CRED_FILE) as f:
            d = json.load(f)
        self.org_id      = d.get("org_id")
        self.conv_id     = d.get("conv_id")
        self.session_key = d.get("session_key")
        self.cookies     = d.get("cookies", {})
        return bool(self.org_id and self.session_key)

    def save(self):
        with open(CRED_FILE, "w") as f:
            json.dump({"org_id": self.org_id, "conv_id": self.conv_id,
                       "session_key": self.session_key,
                       "cookies": self.cookies}, f, indent=2)
        # Restrict file permissions (user-only read/write)
        try:
            if sys.platform != "win32":
                os.chmod(CRED_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 600
        except: pass
        print(f"[+] Credentials saved → {CRED_FILE}")

    def clear(self):
        """Wipe credentials from disk and memory."""
        self.org_id = None
        self.conv_id = None
        self.session_key = None
        self.cookies = {}
        if os.path.exists(CRED_FILE):
            os.remove(CRED_FILE)
            print(f"[+] Credentials deleted: {CRED_FILE}")
        else:
            print("[+] No credential file found.")

    # ── Manual input ─────────────────────────────────────

    def manual_input(self):
        print("\n" + "=" * 55)
        print("  Manual Credential Input")
        print("=" * 55)
        print("\n  Steps:")
        print("  1. Open https://claude.ai — send a message")
        print("  2. DevTools (F12) → Network → find 'completion' request")
        print("  3. URL has /organizations/{org_id}/chat_conversations/{conv_id}/")
        print("  4. Copy the Cookie header value\n")

        self.org_id = input("  org_id: ").strip()
        self.conv_id = input("  conv_id (or 'new'): ").strip()
        if self.conv_id.lower() == "new":
            self.conv_id = str(uuid.uuid4())
            print(f"  [+] Generated conv_id: {self.conv_id}")

        raw = input("  Cookie header: ").strip()
        self._parse_cookies(raw)
        self.save()

    def _parse_cookies(self, raw):
        self.cookies = {}
        for part in raw.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                self.cookies[k.strip()] = v.strip()
        self.session_key = self.cookies.get("sessionKey", "")
        if not self.session_key:
            print("[!] Warning: no sessionKey found in cookies")

    # ── Auto-fetch via real Chrome + CDP ───────────────────

    def auto_fetch(self):
        """Launch REAL Chrome → user passes CF & logs in → extract creds via CDP → close Chrome."""
        chrome = _find_chrome()
        if not chrome:
            print("[!] Chrome not found. Use --manual instead.")
            return False

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("[!] pip install playwright")
            return False

        print("\n  ⚠  WARNING: This uses your authenticated browser session.")
        print("     Extracted credentials are sensitive — treat as passwords.")

        print("\n" + "=" * 55)
        print("  AUTO-FETCH: Real Chrome will launch.")
        print("  1. Cloudflare will pass automatically (real browser)")
        print("  2. Log in to Claude.ai if needed")
        print("  3. Open any chat and send a message")
        print("  4. Press ENTER here when done (don't close Chrome yet)")
        print("=" * 55)
        input("\n  Press ENTER to launch Chrome...")

        proc, cdp_port = _launch_real_chrome(chrome, "https://claude.ai")
        if not proc:
            return False

        print("\n[*] Chrome is open. Complete these steps:")
        print("    1. Pass Cloudflare (automatic in real Chrome)")
        print("    2. Log in if needed")
        print("    3. Open a chat and send any message")
        print("    4. Copy the chat URL from address bar")
        input("\n  Press ENTER when done (keep Chrome open)...")

        url_input = input("  Paste the chat URL (or press Enter to skip): ").strip()
        if url_input:
            m = re.search(r'/chat/([a-f0-9\-]+)', url_input)
            if m:
                self.conv_id = m.group(1)
                print(f"[+] conv_id: {self.conv_id}")

        # Connect via CDP to extract cookies + org_id
        print("[*] Connecting to Chrome via CDP to extract cookies...")
        pw = sync_playwright().start()
        try:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            ctx = browser.contexts[0]

            # Extract cookies
            browser_cookies = ctx.cookies("https://claude.ai")
            self.cookies = {}
            for c in browser_cookies:
                self.cookies[c["name"]] = c["value"]
                if c["name"] == "sessionKey":
                    self.session_key = c["value"]

            # Extract org_id by calling Claude's API from the browser page
            for page in ctx.pages:
                if "claude.ai" not in page.url:
                    continue
                try:
                    orgs = page.evaluate("""
                        async () => {
                            try {
                                const r = await fetch('/api/organizations');
                                const data = await r.json();
                                return data;
                            } catch(e) { return null; }
                        }
                    """)
                    if orgs and isinstance(orgs, list) and len(orgs) > 0:
                        self.org_id = orgs[0].get("uuid") or orgs[0].get("id")
                        print(f"[+] org_id: {self.org_id}")
                        break
                except:
                    pass

            # Fallback conv_id from page URL
            if not self.conv_id:
                for page in ctx.pages:
                    m = re.search(r'/chat/([a-f0-9\-]+)', page.url)
                    if m:
                        self.conv_id = m.group(1)
                        break

            browser.close()
        except Exception as e:
            print(f"[!] CDP connection failed: {e}")
            print("    Make sure Chrome is still open.")
            pw.stop()
            proc.terminate()
            return False

        pw.stop()

        if not self.conv_id:
            self.conv_id = str(uuid.uuid4())

        # Done — close Chrome
        print("[*] Closing Chrome...")
        proc.terminate()

        if self.session_key:
            print(f"[+] Session key: {self.session_key[:25]}...")
            self.save()
            return True
        print("[!] No sessionKey cookie found")
        return False

    # ── Helpers ──────────────────────────────────────────

    def cookie_header(self):
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def is_valid(self):
        return bool(self.org_id and self.session_key)


# ═══════════════════════════════════════════════════════════
#  PAYLOAD BUILDER
# ═══════════════════════════════════════════════════════════

def build_payload(prompt, model=DEFAULT_MODEL):
    """Build a fresh payload with new UUIDs."""
    p = copy.deepcopy(PAYLOAD_TEMPLATE)
    p["prompt"] = prompt
    p["model"]  = model
    p["turn_message_uuids"]["human_message_uuid"]     = str(uuid.uuid4())
    p["turn_message_uuids"]["assistant_message_uuid"]  = str(uuid.uuid4())
    return p


# ═══════════════════════════════════════════════════════════
#  HTTP HELPERS
# ═══════════════════════════════════════════════════════════

def _make_headers(creds):
    return {
        "User-Agent":   UA,
        "Accept":       "text/event-stream",
        "Content-Type": "application/json",
        "Referer":      "https://claude.ai/",
        "Origin":       "https://claude.ai",
        "Cookie":       creds.cookie_header()
    }

def _delete_conversation(creds, conv_id):
    """Delete a conversation so it doesn't appear in browser sidebar."""
    url = f"{URL_BASE}/api/organizations/{creds.org_id}/chat_conversations/{conv_id}"
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Cookie": creds.cookie_header()
    }
    try:
        if HAS_CFFI:
            cffi_requests.delete(url, headers=headers, impersonate="chrome", timeout=10)
        elif std_requests:
            std_requests.delete(url, headers=headers, timeout=10)
    except:
        pass  # best-effort cleanup

def _create_conversation(creds, conv_id, model):
    """Create a new conversation on the server (required before posting completion)."""
    url = f"{URL_BASE}/api/organizations/{creds.org_id}/chat_conversations"
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Referer": "https://claude.ai/",
        "Origin": "https://claude.ai",
        "Cookie": creds.cookie_header()
    }
    payload = {"name": "", "model": model, "uuid": conv_id}
    try:
        if HAS_CFFI:
            resp = cffi_requests.post(url, json=payload, headers=headers,
                                      impersonate="chrome", timeout=15)
        else:
            resp = std_requests.post(url, json=payload, headers=headers, timeout=15)
        return resp.status_code in (200, 201)
    except:
        return False


# ═══════════════════════════════════════════════════════════
#  STREAMING SSE (content_callback for real-time output)
# ═══════════════════════════════════════════════════════════

def stream_prompt(creds, prompt, model=DEFAULT_MODEL, stealth=True,
                  session_state=None):
    """Send prompt with real-time streaming. Returns full response text.
    
    Session memory: uses ONE conversation for the entire session.
    If stealth=True, that conversation is deleted when the session ends (not per-prompt).
    session_state dict tracks: {'conv_id': str, 'created': bool}
    """

    # Determine conv_id: session-persistent or creds-based
    if session_state is not None:
        if not session_state.get("conv_id"):
            # First prompt in session — create a new conversation
            conv_id = str(uuid.uuid4())
            if not _create_conversation(creds, conv_id, model):
                print("\n[!] Failed to create conversation. Session may be expired.")
                return None
            session_state["conv_id"] = conv_id
            session_state["created"] = True
        conv_id = session_state["conv_id"]
    else:
        conv_id = creds.conv_id

    payload  = build_payload(prompt, model)
    endpoint = (f"{URL_BASE}/api/organizations/{creds.org_id}"
                f"/chat_conversations/{conv_id}/completion")
    headers  = _make_headers(creds)

    parts = []
    buffer = ""
    raw_body = []  # capture everything for error detection
    error_body = ""
    status_code = [0]  # mutable for callback scope

    def on_chunk(chunk: bytes):
        nonlocal buffer
        text = chunk.decode("utf-8", errors="replace")
        raw_body.append(text)
        buffer += text
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data.strip() == "[DONE]":
                return
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            t = obj.get("type", "")
            if t == "content_block_delta":
                delta = obj.get("delta", {})
                if delta.get("type") == "text_delta":
                    txt = delta.get("text", "")
                    parts.append(txt)
                    sys.stdout.write(txt)
                    sys.stdout.flush()
            elif t == "error":
                err = obj.get("error", {})
                print(f"\n[!] {err.get('message', str(obj))}")
            elif t == "message_stop":
                return

    # ── Send request ─────────────────────────────────────
    resp = None
    try:
        if HAS_CFFI:
            resp = cffi_requests.post(
                endpoint, json=payload, headers=headers,
                impersonate="chrome", content_callback=on_chunk, timeout=120)
        else:
            # Fallback: standard requests with full body parse
            resp = std_requests.post(
                endpoint, json=payload, headers=headers, timeout=120)
    except Exception as e:
        print(f"\n[!] Request error: {e}")

    # ── Handle non-streaming fallback ────────────────────
    if resp and not HAS_CFFI:
        if resp.status_code == 200:
            text = resp.text
            for line in text.split("\n"):
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except:
                    continue
                t = obj.get("type", "")
                if t == "content_block_delta":
                    delta = obj.get("delta", {})
                    if delta.get("type") == "text_delta":
                        txt = delta.get("text", "")
                        parts.append(txt)
                        sys.stdout.write(txt)
                        sys.stdout.flush()

    # ── Check status / detect errors ───────────────────────
    if resp:
        status_code[0] = resp.status_code

    # If callback got data but no SSE parts, check raw body for errors
    if not parts:
        full_raw = "".join(raw_body) + buffer
        if full_raw:
            # Try parsing as JSON error
            try:
                err_obj = json.loads(full_raw.strip())
                if err_obj.get("type") == "error":
                    msg = err_obj.get("error", {}).get("message", str(err_obj))
                    code = err_obj.get("error", {}).get("error_code", "")
                    if "model" in code or "model" in msg.lower():
                        print(f"\n[!] Model '{model}' not available: {msg}")
                    else:
                        print(f"\n[!] Error: {msg}")
                    return None
            except json.JSONDecodeError:
                pass
            error_body = full_raw[:500]
        elif resp and resp.status_code != 200:
            try: error_body = resp.text[:500]
            except: pass

    # ── Error handling ───────────────────────────────────
    if error_body and not parts:
        sc = status_code[0]
        if "Just a moment" in error_body or "cloudflare" in error_body.lower():
            print(f"\n[!] Cloudflare blocked — run --auto-fetch again.")
        elif sc == 401:
            print(f"\n[!] Session expired. Run --auto-fetch")
        elif sc == 403:
            if "model" in error_body.lower():
                print(f"\n[!] Model '{model}' not available on your account tier.")
                print(f"    Try: /model sonnet")
            else:
                print(f"\n[!] 403: {error_body[:200]}")
        elif sc == 429:
            return _handle_rate_limit(resp, creds, prompt, model, stealth)
        else:
            print(f"\n[!] HTTP {sc}: {error_body[:200]}")
        return None

    full = "".join(parts)
    print()

    # ── Save last response ───────────────────────────────
    if full:
        with open(os.path.join(DIR, "last_response.txt"), "w", encoding="utf-8") as f:
            f.write(full)
    return full


def _handle_rate_limit(resp, creds, prompt, model, stealth):
    """Handle 429: show wait time, auto-fallback to haiku if on heavier model."""
    retry = "unknown"
    try:
        retry = resp.headers.get("Retry-After", "")
        if not retry:
            body = resp.text[:500]
            m = re.search(r'"retry_after":\s*(\d+)', body)
            if m: retry = m.group(1)
    except: pass

    print(f"\n[!] Rate limited. Retry after: {retry}s")

    # Auto-fallback to haiku if not already on it
    if model != "claude-haiku-4-5" and model != MODEL_ALIASES.get("haiku"):
        print(f"[*] Falling back to haiku...")
        return stream_prompt(creds, prompt, "claude-haiku-4-5", stealth)

    # Already on haiku — wait and retry
    wait = 30
    try: wait = int(retry)
    except: pass
    wait = min(wait, 300)
    print(f"[*] Waiting {wait}s...")
    time.sleep(wait)
    return stream_prompt(creds, prompt, model, stealth)


# ═══════════════════════════════════════════════════════════
#  REAL CHROME HELPERS (for credential extraction only)
# ═══════════════════════════════════════════════════════════

def _find_chrome():
    """Find Chrome executable on Windows."""
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        shutil.which("chromium"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            print(f"[+] Found Chrome: {c}")
            return c
    return None


def _get_free_port():
    """Get a random free port from the OS."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _launch_real_chrome(chrome_path, url="https://claude.ai"):
    """Launch a real Chrome process with remote debugging.
    Security: bound to 127.0.0.1 only, random ephemeral port.
    This is a normal Chrome — NOT controlled by Playwright/CDP at launch.
    Cloudflare cannot distinguish it from a regular user session."""
    os.makedirs(PROFILE, exist_ok=True)
    cdp_port = _get_free_port()
    cmd = [
        chrome_path,
        f"--remote-debugging-port={cdp_port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        url
    ]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[+] Real Chrome launched (PID {proc.pid}, CDP 127.0.0.1:{cdp_port})")
        time.sleep(3)
        return proc, cdp_port
    except Exception as e:
        print(f"[!] Failed to launch Chrome: {e}")
        return None, 0


# ═══════════════════════════════════════════════════════════
#  LOGIN (real Chrome — for profile setup)
# ═══════════════════════════════════════════════════════════

def do_login():
    """Launch real Chrome for the user to log in. Session is saved to profile dir."""
    chrome = _find_chrome()
    if not chrome:
        print("[!] Chrome not found. Install Google Chrome or use --manual.")
        return

    print("=" * 55)
    print("  Real Chrome will open → log in to Claude.ai")
    print("  CF will pass automatically (real browser)")
    print("  Close Chrome when done.")
    print("=" * 55)
    input("  Press ENTER...")

    proc, _ = _launch_real_chrome(chrome)
    if not proc:
        return

    print("[*] Waiting for Chrome to close...")
    proc.wait()
    print("[+] Profile saved to claude_profile/\n")


# ═══════════════════════════════════════════════════════════
#  REPL COMMAND HANDLER
# ═══════════════════════════════════════════════════════════

def _print_help():
    print("""
  ╔══════════════════════════════════════════════════════╗
  ║                    COMMANDS                         ║
  ╠══════════════════════════════════════════════════════╣
  ║  /model <name>     Switch model                     ║
  ║  /models           List all models                  ║
  ║  /stealth on|off   Toggle cleanup on exit           ║
  ║  /new              Start fresh conversation         ║
  ║  /cleanup          Delete session conv NOW          ║
  ║  /clear-session    Wipe stored credentials          ║
  ║  /help             Show this help                   ║
  ║  exit              Quit (auto-cleans if stealth)    ║
  ╚══════════════════════════════════════════════════════╝
""")

def _print_models(current):
    print("\n  Available models:")
    for alias, full in MODEL_ALIASES.items():
        marker = " <--" if full == current else ""
        tier = "PRO" if "opus" in alias else "FREE"
        print(f"    {alias:14s}  {full:36s}  [{tier}]{marker}")
    print()


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════

def main():
    print()
    print("  ╔════════════════════════════════════════════════════╗")
    print("  ║  Claude.ai RE Client v4 — Secure + Stealth        ║")
    print("  ╚════════════════════════════════════════════════════╝")
    print()

    ap = argparse.ArgumentParser(description="Claude.ai Security Research Client v4")
    ap.add_argument("--login",         action="store_true", help="Browser login (save profile)")
    ap.add_argument("--auto-fetch",    action="store_true", help="Auto-extract creds via Chrome+CDP")
    ap.add_argument("--manual",        action="store_true", help="Manual credential input")
    ap.add_argument("--prompt",        type=str, help="Single prompt to send")
    ap.add_argument("--model",         type=str, default="sonnet",
                    help="Model: haiku/sonnet/opus (default: sonnet)")
    ap.add_argument("--org-id",        type=str, help="Organization ID")
    ap.add_argument("--conv-id",       type=str, help="Conversation ID")
    ap.add_argument("--cookie",        type=str, help="Full Cookie header string")
    ap.add_argument("--jailbreak",     type=str, help="Read prompt from file")
    ap.add_argument("--batch",         type=str, help="Send multiple prompts from file")
    ap.add_argument("--no-stealth",    action="store_true", help="Disable stealth mode")
    ap.add_argument("--clear-session", action="store_true", help="Delete stored credentials")
    args = ap.parse_args()

    # ── Clear session ────────────────────────────────────
    if args.clear_session:
        creds = CredentialManager()
        creds.clear()
        return

    # ── Login ────────────────────────────────────────────
    if args.login:
        do_login(); return

    # ── Credential resolution ────────────────────────────
    creds = CredentialManager()

    if args.auto_fetch:
        if not creds.auto_fetch():
            print("[!] Auto-fetch failed"); return
    elif args.manual:
        creds.manual_input()
    elif args.org_id and args.cookie:
        creds.org_id  = args.org_id
        creds.conv_id = args.conv_id or str(uuid.uuid4())
        creds._parse_cookies(args.cookie)
        creds.save()
    elif not creds.load():
        print("[!] No credentials. Use --manual, --auto-fetch, or --login")
        return

    if not creds.is_valid():
        print("[!] Invalid credentials"); return

    # ── State ────────────────────────────────────────────
    model   = resolve_model(args.model)
    stealth = not args.no_stealth

    # Session state: tracks the current conversation for memory
    # Created lazily on first prompt, deleted on exit if stealth
    session = {"conv_id": None, "created": False}

    def _cleanup_session():
        """Delete the session conversation if stealth is on."""
        if stealth and session.get("conv_id") and session.get("created"):
            print("\n[*] Cleaning up session conversation...")
            _delete_conversation(creds, session["conv_id"])
            print("[+] Session cleaned (invisible in browser)")
            session["conv_id"] = None
            session["created"] = False

    lib = "curl_cffi" if HAS_CFFI else "requests"
    mode = "stealth" if stealth else "visible"
    print(f"[+] model:   {model}")
    print(f"[+] tz:      {SYSTEM_TIMEZONE}")
    print(f"[+] http:    {lib}")
    print(f"[+] stealth: {mode}  (memory ON, cleanup on exit)")
    print(f"[+] creds:   {CRED_FILE}")
    print(f"[+] Type /help for commands\n")

    # ── Jailbreak mode ──────────────────────────────────
    if args.jailbreak:
        if not os.path.exists(args.jailbreak):
            print(f"[!] File not found: {args.jailbreak}"); return
        with open(args.jailbreak, "r", encoding="utf-8") as f:
            prompt = f.read().strip()
        stream_prompt(creds, prompt, model, stealth, session)
        _cleanup_session()
        return

    # ── Batch mode ──────────────────────────────────────
    if args.batch:
        if not os.path.exists(args.batch):
            print(f"[!] File not found: {args.batch}"); return
        with open(args.batch, "r", encoding="utf-8") as f:
            prompts = [l.strip() for l in f if l.strip()]
        results = []
        for i, p in enumerate(prompts):
            print(f"  [{i+1}/{len(prompts)}] {p[:60]}")
            r = stream_prompt(creds, p, model, stealth, session)
            results.append({"prompt": p, "response": r or ""})
            if i < len(prompts) - 1:
                time.sleep(2)
        out = os.path.join(DIR, "batch_results.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"[+] Saved -> {out}")
        _cleanup_session()
        return

    # ── Single prompt ───────────────────────────────────
    if args.prompt:
        stream_prompt(creds, args.prompt, model, stealth, session)
        _cleanup_session()
        return

    # ── Interactive REPL ────────────────────────────────
    try:
        while True:
            try:
                inp = input("  You> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not inp:
                continue
            if inp.lower() in ("exit", "quit", "q"):
                break

            # ── REPL commands ────────────────────────────
            if inp.startswith("/"):
                parts = inp.split(None, 1)
                cmd = parts[0].lower()
                arg = parts[1].strip() if len(parts) > 1 else ""

                if cmd == "/help":
                    _print_help()
                elif cmd == "/models":
                    _print_models(model)
                elif cmd == "/model":
                    if not arg:
                        print(f"  Current: {model}")
                        print(f"  Usage: /model haiku|sonnet|opus|sonnet-4-5")
                    else:
                        new = resolve_model(arg)
                        if new != model:
                            # Model change requires new conversation
                            _cleanup_session()
                            session["conv_id"] = None
                            session["created"] = False
                            model = new
                            print(f"  [+] Model -> {model} (new session)")
                        else:
                            print(f"  [+] Already on {model}")
                elif cmd == "/stealth":
                    if arg.lower() in ("on", "1", "true"):
                        stealth = True
                        print("  [+] Stealth ON (cleanup on exit)")
                    elif arg.lower() in ("off", "0", "false"):
                        stealth = False
                        print("  [+] Stealth OFF (conversations kept)")
                    else:
                        print(f"  Stealth: {'ON' if stealth else 'OFF'}")
                        print(f"  Usage: /stealth on|off")
                elif cmd == "/new":
                    _cleanup_session()
                    session["conv_id"] = None
                    session["created"] = False
                    print("  [+] Fresh conversation (next prompt starts new)")
                elif cmd == "/cleanup":
                    _cleanup_session()
                elif cmd == "/clear-session":
                    creds.clear()
                    print("  [!] Session wiped. Re-run --auto-fetch to continue.")
                    break
                else:
                    print(f"  [!] Unknown command: {cmd}. Try /help")
                continue

            # ── Send prompt ─────────────────────────────
            print()
            stream_prompt(creds, inp, model, stealth, session)
    finally:
        # Always cleanup on exit
        _cleanup_session()


if __name__ == "__main__":
    main()
