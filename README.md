# 🔬 Claude.ai Reverse-Engineered CLI Client

> **Security Research Tool** — A reverse-engineered command-line interface for Claude.ai, built through REST/SSE protocol analysis without using any official API keys.

⚠️ **Disclaimer**: This project is strictly for **educational and security research purposes**. It demonstrates reverse engineering techniques applied to a public-facing AI service. No API key required — uses browser session replay. Use responsibly.

---

## 📋 Overview

This tool captures Claude.ai browser session credentials (cookies, org ID) and replays them via direct HTTP calls to the internal REST API. It streams responses in real-time using Server-Sent Events (SSE) — exactly like the browser does, but from your terminal.

**No API key. No paid tier. No official SDK.**

### How It Works

```
┌──────────┐     ┌───────────────┐     ┌──────────────┐
│ Terminal  │────▶│  curl_cffi    │────▶│ claude.ai    │
│ (You>)   │     │  TLS Spoof    │     │ REST + SSE   │
│          │◀────│  SSE Stream   │◀────│              │
└──────────┘     └───────────────┘     └──────────────┘
```

1. **Credential Capture** — Launches real Chrome via CDP, user logs in, tool extracts `sessionKey`, `org_id`, and all cookies automatically
2. **TLS Fingerprinting** — Uses `curl_cffi` with Chrome impersonation to bypass Cloudflare's TLS fingerprint checks
3. **Session Replay** — Sends prompts to `/api/organizations/{org_id}/chat_conversations/{conv_id}/completion` with captured cookies
4. **SSE Streaming** — Parses `content_block_delta` events in real-time for word-by-word terminal output

### Key Features

| Feature | Description |
|---------|-------------|
| **Live Streaming** | Word-by-word response streaming via SSE `content_callback` |
| **Model Selection** | Switch between Haiku, Sonnet, Opus mid-conversation with `/model` |
| **Session Memory** | Multi-turn conversations within a single session |
| **Stealth Mode** | Auto-deletes conversations from Claude.ai history on exit |
| **Dynamic Timezone** | Auto-detects system timezone (IANA) — no hardcoded fingerprints |
| **Secure CDP** | DevTools bound to `127.0.0.1` with random ephemeral port |
| **Safe Credential Storage** | Session stored outside repo with restricted permissions |
| **Rate Limit Handler** | Auto-fallback to Haiku when rate-limited, with retry logic |
| **Batch Mode** | Process multiple prompts from a file |
| **Jailbreak Mode** | Load system prompts from external files |
| **TLS Bypass** | `curl_cffi` Chrome impersonation defeats Cloudflare |

---

## 🛠️ Installation

### Prerequisites

- Python 3.9+
- Google Chrome (for one-time credential extraction)
- A Claude.ai account (free tier works)

### Setup

```bash
# Clone the repository
git clone https://github.com/Adithyan-Defender/claude-ai-re-client.git
cd claude-ai-re-client
 
# Install dependencies
pip install -r requirements.txt
```

> **Note**:this tool uses your **real installed Chrome** for credential extraction, not Playwright's managed browser.

### Dependencies

| Package | Purpose |
|---------|---------|
| `curl_cffi` | HTTP client with Chrome TLS fingerprint impersonation |
| `playwright` | CDP connection to real Chrome for credential extraction (no browser download needed) |

---

## 🚀 Usage

### Step 1: Extract Credentials (one-time)

**Option A — Auto-Fetch (recommended)**

Launches your real Chrome, you log in, then credentials are extracted automatically via CDP:

```bash
python claude_ai_client.py --auto-fetch
```

1. Chrome opens → log into Claude.ai
2. Open any chat and send a message
3. Press ENTER in terminal → credentials extracted and saved

**Option B — Manual Input**

For advanced users who want to paste credentials directly from DevTools:

```bash
python claude_ai_client.py --manual
```

### Step 2: Chat

```bash
# Interactive REPL (default)
python claude_ai_client.py

# Single prompt
python claude_ai_client.py --prompt "explain quantum computing"

# Choose model
python claude_ai_client.py --model opus

# Disable stealth (keep conversations in browser history)
python claude_ai_client.py --no-stealth
```

### Interactive Session Example

```
  ╔════════════════════════════════════════════════════╗
  ║  Claude.ai RE Client v4 — Secure + Stealth        ║
  ╚════════════════════════════════════════════════════╝

  [+] model:   claude-sonnet-4-6
  [+] tz:      Asia/Kolkata
  [+] http:    curl_cffi
  [+] stealth: stealth  (memory ON, cleanup on exit)
  [+] creds:   C:\Users\you\AppData\Roaming\claude_re\claude_session.json
  [+] Type /help for commands

  You> what is reverse engineering?

  Reverse engineering is the process of analyzing a finished
  product to understand its design, internal workings, and
  functionality — essentially working backwards from the
  output to understand the input...

  You> /model opus
  [+] Model -> claude-opus-4-7 (new session)

  You> /models

  Available models:
    haiku           claude-haiku-4-5                      [FREE]
    sonnet          claude-sonnet-4-6                     [FREE] <--
    sonnet-4-5      claude-sonnet-4-5                     [FREE]
    haiku-snap      claude-haiku-4-5-20251001             [FREE]
    sonnet-snap     claude-sonnet-4-5-20250929            [FREE]
    opus            claude-opus-4-7                       [PRO]
    opus-3          claude-3-opus-20240229                [PRO]

  You> exit
  [*] Cleaning up session conversation...
  [+] Session cleaned (invisible in browser)
```

---

## ⌨️ Interactive Commands

Use these commands during a chat session (type `/help` at any time):

| Command | Description |
|---------|-------------|
| `/help` | Show all available commands |
| `/model <name>` | Switch model (e.g., `/model haiku`, `/model opus`) |
| `/models` | List all available models with current selection |
| `/stealth on\|off` | Toggle stealth mode (auto-cleanup on exit) |
| `/new` | Start a fresh conversation (clears context) |
| `/cleanup` | Delete current session conversation immediately |
| `/clear-session` | Wipe stored credentials from disk and memory |
| `exit` / `quit` / `q` | Exit (auto-cleans if stealth is on) |

### Model Shortcuts

| Shortcut | Full Model Name | Tier |
|----------|----------------|------|
| `haiku` | `claude-haiku-4-5` | FREE |
| `sonnet` | `claude-sonnet-4-6` | FREE (default) |
| `sonnet-4-5` | `claude-sonnet-4-5` | FREE |
| `haiku-snap` | `claude-haiku-4-5-20251001` | FREE |
| `sonnet-snap` | `claude-sonnet-4-5-20250929` | FREE |
| `opus` | `claude-opus-4-7` | PRO |
| `opus-3` | `claude-3-opus-20240229` | PRO |

> **Note**: PRO models require a Claude Pro/Max subscription on your account. Free accounts can use all FREE tier models.

---

## 🔒 Stealth Mode

Stealth mode is **enabled by default**. It ensures your CLI conversations are invisible in the Claude.ai browser interface.

**How it works:**
1. Each session creates a new conversation via the REST API
2. All prompts in the session share context (multi-turn memory)
3. On exit (or Ctrl+C), the conversation is deleted via `DELETE /api/organizations/{org_id}/chat_conversations/{conv_id}`
4. The conversation never appears in the browser sidebar

**Control stealth:**
```bash
# Disable via CLI flag
python claude_ai_client.py --no-stealth

# Toggle during session
/stealth off
/stealth on
```

---

## 📦 Advanced Usage

### Batch Mode

Process multiple prompts from a file (one per line):

```bash
python claude_ai_client.py --batch prompts.txt
```

Results are saved to `batch_results.json`.

### Jailbreak Mode

Load a full prompt from an external file:

```bash
python claude_ai_client.py --jailbreak system_prompt.txt
```

### CLI Flags

Pass credentials directly (no saved file needed):

```bash
python claude_ai_client.py --org-id "YOUR_ORG" --cookie "sessionKey=sk-ant-..."
```

### Clear Session

Delete stored credentials from disk:

```bash
python claude_ai_client.py --clear-session
```

Or use `/clear-session` during an interactive session.

---

## 🧪 Technical Deep Dive

### Reverse Engineering Methodology

**Phase 1 — Session Analysis**
- Used Chrome DevTools to intercept REST calls to `claude.ai/api/`
- Identified the SSE-based completion endpoint structure: `/api/organizations/{org_id}/chat_conversations/{conv_id}/completion`
- Mapped required headers: `Cookie` (with `sessionKey`), `User-Agent`, `Content-Type`

**Phase 2 — TLS Fingerprint Bypass**
- Direct `requests` calls are blocked by Cloudflare's TLS fingerprint detection
- Solution: `curl_cffi` with `impersonate="chrome"` mimics Chrome's exact TLS handshake (cipher suites, ALPN, extensions)

**Phase 3 — Credential Extraction**
- Real Chrome launched with `--remote-debugging-port`
- CDP connection via Playwright extracts cookies and org_id from the authenticated session
- Cloudflare cannot distinguish this from a normal user session

**Phase 4 — Response Parsing**
- Responses arrive as SSE events: `data: {"type": "content_block_delta", "delta": {"text": "..."}}`
- `content_callback` in `curl_cffi` enables real-time streaming without waiting for full response
- `message_stop` event signals completion

### Architecture

```
claude_ai_client.py
├── Timezone Detector   — Auto-detects IANA timezone (stdlib + Windows registry + /etc/timezone)
├── CredentialManager   — Load/save/extract/clear session credentials
│   ├── auto_fetch()    — Real Chrome + secure CDP extraction
│   ├── manual_input()  — Manual DevTools input
│   ├── clear()         — Wipe credentials from disk + memory
│   └── load()/save()   — Stored outside repo (%APPDATA%/claude_re/)
├── Payload Builder     — Fresh UUIDs + dynamic timezone per request
├── HTTP Engine         — curl_cffi with Chrome TLS impersonation
├── SSE Stream Parser   — Real-time content_block_delta extraction
├── Rate Limit Handler  — Auto-fallback to Haiku + retry
├── Stealth Engine      — Conversation deletion on exit
└── REPL                — Interactive commands (/model, /new, /stealth, /clear-session)
```

---

## 📁 Project Structure

```
claude-ai-re-client/
├── claude_ai_client.py    # Main client (auth + streaming + stealth)
├── requirements.txt       # Python dependencies
├── .gitignore             # Excludes credentials and session data
└── README.md              # This file
```

### Generated at Runtime (git-ignored)

| File/Directory | Location | Contents | Sensitive |
|----------------|----------|----------|-----------|
| `claude_session.json` | `%APPDATA%/claude_re/` (Win) or `~/.config/claude_re/` (Linux/Mac) | Session key, org ID, cookies | **YES** |
| `claude_profile/` | Project directory | Chrome browser profile | **YES** |
| `last_response.txt` | Project directory | Last AI response cache | No |
| `batch_results.json` | Project directory | Batch mode output | No |

---

## 🛡️ Security Hardening (v4)

### DevTools (CDP) Protection
- Chrome DevTools is bound to **`127.0.0.1` only** — not accessible from the network
- Uses a **random ephemeral port** (not a fixed port like 9222)
- CDP connection is used only during credential extraction, then Chrome is terminated

### Credential Storage
- Session file is stored **outside the repository** (`%APPDATA%\claude_re\` on Windows, `~/.config/claude_re/` on Linux/Mac)
- File permissions are restricted to **user-only** (`chmod 600` on Unix)
- `.gitignore` blocks all sensitive files as a safety net
- Use `--clear-session` or `/clear-session` to wipe credentials at any time

### Request Fingerprint Consistency
- **Timezone** is auto-detected from the system (IANA format like `Asia/Kolkata`, `America/New_York`)
- No hardcoded locale or timezone that could create metadata anomalies
- TLS fingerprint matches real Chrome via `curl_cffi` impersonation

---

## ⚠️ Security Warnings

> **This tool uses your real authenticated session. All extracted credentials must be treated with the same sensitivity as your account password.**

### 🔴 Session Hijacking Risk
- The `claude_session.json` file contains your **full session key and cookies**. Anyone with this file can impersonate your Claude.ai account — send messages, read conversations, and access your data.
- **Never share, upload, or commit** this file. It is stored outside the repo at:
  - **Windows**: `%APPDATA%\claude_re\claude_session.json`
  - **Linux/Mac**: `~/.config/claude_re/claude_session.json`
- Run `--clear-session` or `/clear-session` to **wipe credentials immediately** when you're done.

### 🔴 DevTools Exposure Risk
- During `--auto-fetch` and `--login`, Chrome is launched with a remote debugging port for credential extraction.
- This client **binds DevTools to `127.0.0.1` only** (localhost) with a **random ephemeral port** — it is NOT accessible from the network.
- **Never manually launch Chrome** with `--remote-debugging-port` bound to `0.0.0.0` — this would expose your browser session to anyone on your network.
- The CDP connection is automatically closed after credential extraction.

### 🔴 Credential Storage
- Credentials are stored as **plaintext JSON** on disk (encrypted storage is not yet implemented).
- On Linux/Mac, file permissions are restricted to **owner-only** (`chmod 600`).
- On Windows, rely on NTFS user permissions — ensure no shared access to your `%APPDATA%` folder.
- If you suspect credential compromise, immediately:
  1. Run `python claude_ai_client.py --clear-session`
  2. Log out of Claude.ai in your browser to invalidate the session
  3. Re-authenticate with `--auto-fetch`

### 🟡 Git Safety
- `.gitignore` is pre-configured to block `claude_session.json`, `claude_profile/`, `last_response.txt`, and `batch_results.json`.
- **Before pushing**: always run `git status` to verify no sensitive files are staged.
- If you accidentally commit credentials, **do not just delete and re-commit** — the data persists in git history. You must rewrite history (`git filter-branch` or `git filter-repo`) or re-initialize the repo.

### 🟡 Session Expiry
- Session keys expire periodically. If you get `401` errors, run `--auto-fetch` again.
- Cloudflare may trigger additional verification — the real Chrome approach handles this automatically.

---

## 🔬 Research Context

This project demonstrates:
- **REST API reverse engineering** of a production AI service without official documentation
- **TLS fingerprint bypass** using `curl_cffi` Chrome impersonation to defeat Cloudflare
- **CDP-based credential extraction** from real browser sessions
- **SSE streaming protocol analysis** for real-time response reconstruction
- **Session management** via REST API calls (create/delete conversations)

Built as part of an AI security research initiative exploring the attack surface of commercial AI chat interfaces.

---

## 📄 License

This project is provided for educational and security research purposes only. No warranty is provided. Use at your own risk.
