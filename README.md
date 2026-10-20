# Social Engagement Automation Lab

**English** · [繁體中文](./README.zh-TW.md)

> **Local research sandbox for social-style account automation and bulk interaction**
>
> Built to study session management, Playwright browser automation, HTTP request chains, batch likes, concurrent database writes, and rate limiting on a mock Instagram-like stack—entirely on your machine.

<p align="center">
  <a href="https://github.com/ReiKama414/social-engagement-lab">GitHub</a> ·
  <a href="https://reikama414.vercel.app/">Portfolio</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#license">License</a>
</p>

---

## Safety boundary (strict local sandbox)

This project is a **local lab only**. Research boundaries:

- **No connection to real Instagram servers** — all traffic stays on `localhost` (`127.0.0.1`).
- **No unofficial private APIs** — protocols are implemented on a local FastAPI mock server.
- **No real Instagram session cookies** collected or used.
- **No bypassing** of real-platform CAPTCHA, device fingerprinting, or IP proxy rotation.
- Virtual accounts (100–10,000) and posts live in a local SQLite database.

---

## Architecture and stack

| Layer | Stack | Role |
| :--- | :--- | :--- |
| **Frontend** | Next.js 16, TypeScript, Tailwind CSS v4 | Dev console, Instagram-style feed, network inspector, interactive flow diagram |
| **Backend** | FastAPI, Python 3.11, Uvicorn | REST API, inspector middleware, adaptive rate limiter, WebSocket broadcast |
| **Automation** | Playwright (Chromium headless / headed) | Isolated contexts, login, find posts, like clicks, HTTP intercept, SQLite verification |
| **Storage** | SQLite 3 (WAL + busy timeout) | Concurrent reads/writes, atomic transactions, lock protection |
| **Realtime** | WebSocket (`/ws`) | Task progress, live logs, like counts, benchmark metrics |

---

## Quick start

Windows 11 scripts and virtualenv are included.

### Option 1: Double-click (recommended)

Run `start.bat` in the repo root. It opens separate terminals for:

1. **Backend (FastAPI)** — [http://127.0.0.1:8000](http://127.0.0.1:8000)
2. **Frontend (Next.js)** — [http://localhost:3000](http://localhost:3000)
3. **Mock social UI** — [http://127.0.0.1:8000/mock-social](http://127.0.0.1:8000/mock-social)

### Option 2: PowerShell

```powershell
.\start.ps1
```

### Option 3: Manual

```powershell
# Backend
.\run_backend.bat

# Frontend
.\run_frontend.bat
```

---

## Automated verification

Run `run_tests.bat` or:

```powershell
# API and integration tests
.\backend\venv\Scripts\pytest -v backend\tests\test_api.py

# Playwright end-to-end
.\backend\venv\Scripts\pytest -v backend\tests\test_playwright.py
```

---

## Research modules

### 1. Mock social feed — `/feed`

- Instagram-style post wall.
- Register, password auth, per-account session tokens (Bearer / Cookie).
- Like / unlike with real SQLite writes and optimistic locking.
- **Simulate Expired Session** to force HTTP 401 handling.
- **Likers drawer** — see whether each like came from BROWSER or API mode.

### 2. Batch account fleet — `/accounts`

- One-click virtual accounts: `+100`, `+1,000`, `+5,000`, `+10,000`.
- Batch `executemany` inserts (~0.8s for 10,000 accounts).
- Per-account ID, avatar, group tag, status (ACTIVE / DISABLED / RATE_LIMITED), pre-issued sessions.
- Search, group filter, batch enable / disable / delete, session expiry.

### 3. Task control center — `/tasks`

- **Playwright fleet** — eight-step flow: launch browser → open page → login → find post → like → intercept API → verify SQLite → close context.
- **High-speed API** — async worker pool with sessions for fast bulk interaction.
- Worker pool concurrency (2–8 browser contexts).
- Delay / jitter (0–2000 ms).
- Start, pause, resume, cancel; per-task ID and millisecond live terminal logs.

### 4. Network inspector — `/inspector`

- HTTP audit: method, path, timestamp, latency (ms).
- Credential masking (e.g. `Bearer sess_****abcd`).
- Request / response JSON preview.
- Session validation (sessions table, expiry, account status).
- SQLite WAL change analysis (row counts, like count before/after).
- **Copy as cURL** and **export full trace JSON**.
- **Timing waterfall** — network, routing, auth, SQLite, serialization.
- **Interactive 7-layer flow** — click each stage:

  ```
  Browser → HTTP Request → FastAPI → Session Validation → SQLite → Response → UI Update
  ```

### 5. Stress benchmark — `/benchmark`

- High-throughput load on local API and DB locks (up to 10,000 virtual accounts).
- Live SVG RPS curve, success rate, latency percentiles (P50 / P90 / P95 / P99).
- DB writes/sec and contention buckets (RateLimit_429, Duplicate_Like_400, SessionExpired_401, DB_Locked_Timeout, etc.).

---

## In-app bilingual UI

The product UI follows **Traditional Chinese primary, English secondary** (front and back office):

- Top nav `[繁中 | EN]` toggles locale instantly.
- `/mock-social` and all dashboards share the same zh-TW / EN strings.
- Inspector lifecycle labels and log tags are bilingual.

---

## License

MIT © [ReiKama414](https://github.com/ReiKama414)

You may use, copy, modify, and distribute this software, including commercially, provided the copyright and license notice are preserved. The software is provided without warranty.

See [LICENSE](./LICENSE).

---

<sub>Author [ReiKama414](https://github.com/ReiKama414) · [Portfolio](https://reikama414.vercel.app/)</sub>
