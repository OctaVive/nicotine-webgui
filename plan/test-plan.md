# Nicotine Web GUI — Test Plan

| | |
|---|---|
| Version | 1.0 |
| Date | 2026-10-20 |
| Applies to | Nicotine Web GUI 0.2.0 (static UI container + browser SPA + in-process Nicotine+ plugin) |
| Related documents | [`nicotine-webgui.md`](nicotine-webgui.md) (design), [`execution.md`](execution.md) (execution checklist), [`../README.md`](../README.md) |
| Sources of truth | `openapi.yaml`, `plugin/webgui/router.py`, `web/src/**`, CI workflows in `.github/workflows/` |

---

## 1. Objective

Verify that the static Web GUI container, browser client, and in-process Nicotine+ plugin work together as a secure remote control for an existing Nicotine+ instance, across the supported Python/Nicotine+ versions, deployment modes, and failure conditions.

Primary quality goals:

1. No cross-origin, CSRF, Host-header, or credential-exposure weakness.
2. The bridge never destabilises Nicotine+ (bounded memory/threads, contained callbacks, clean unload/reload).
3. Core workflows work end-to-end: connect → search → download → transfer control → chat → browse → discover → share → administer.
4. Live updates survive interruption, replay, resync, plugin restart, and multi-tab use without duplicate or stale state.
5. The container is non-root, read-only, loopback-published, and deployable on amd64/arm64.

---

## 2. Scope

### In scope

- `plugin/webgui/*` (HTTP server, router, auth, store, ingest, adapter, history, schema) and `plugin/__init__.py` lifecycle.
- `web/src` SPA: login, shell, search, transfers, chat, people, browse, shares, plugins, settings, logs/notifications/statistics, live updates, keyboard/theme behaviour.
- `openapi.yaml` contract and generated `web/src/api/types.gen.ts`.
- `dev/scripts/install_plugin.py`, `docker/bootstrap.py`, Docker image, `compose.yaml`, health/static serving.
- Security posture of plugin and container.
- Compatibility with Nicotine+ 3.3.6–3.3.x, Python 3.9/3.12+, Node 22, Chromium (plus recommended Firefox/WebKit).

### Out of scope

- Soulseek protocol correctness (owned by Nicotine+).
- Real music download integrity/DRM/legal content validation beyond transfer state.
- Reverse-proxy vendor configuration matrices beyond the Nginx reference cases.
- Native mobile apps; PWA/mobile layout (not implemented).
- Load testing at internet scale; the target is a single user/household.

---

## 3. System under test

| Component | Runtime | Key interfaces |
|---|---|---|
| Static UI container | Python 3.12 slim, UID 10001, read-only FS, internal :8080 | `GET /health`, SPA fallback, published `${WEBUI_BIND_ADDRESS}:${WEBUI_PORT}` |
| Browser SPA | React 19 + Vite build | `https://<plugin>/api/v1`, SSE, `localStorage` (endpoint), `sessionStorage` (session) |
| Nicotine+ plugin | In-process, stdlib HTTP server, default `127.0.0.1:8181` | `/api/v1/*` (83 operations), `/api/v1/events` SSE |
| Reverse proxy | External (Nginx reference) | Terminates TLS, forwards Host/Origin/Authorization/X-CSRF-Token/Last-Event-ID |

### Limits and thresholds used by tests

| Limit | Value |
|---|---|
| JSON request body | 256 KiB |
| Concurrent HTTP requests | 48 |
| Concurrent SSE clients | 16 |
| Per-client event queue | 128 |
| SSE replay ring | 1000 events |
| SSE heartbeat | 20 s |
| Request timeout | 15 s |
| Client stream idle timeout | 45 s |
| Session lifetime / capacity | 12 h / 32 sessions |
| Login rate limit | 5 attempts / 60 s |
| Mutation rate limit | 60 / s |
| Messages per conversation | 500 |
| Conversations retained | 100 |
| Concurrent searches | 20 |
| Results retained per search | 10 000 |
| Logs retained | 2000 |

---

## 4. Baseline status (repository inspection, 2026-10-20)

The checks that need no installs were run before writing this plan. **The tree is not currently runnable for the full suite**, so Phase 0 of this plan repairs the baseline.

| Check | Result |
|---|---|
| `python -m unittest discover -s tests/bridge -v` | 20 tests, 1 failure on Windows 11 / Python 3.13: `test_port_conflict_does_not_leave_event_callbacks_or_listener` (`OSError` not raised). Likely `allow_reuse_address` / Windows socket semantics; CI is Linux. |
| `python -m unittest discover -s tests/container -v` | 5 tests, 2 failures on Windows: POSIX `0600` mode assertions in `test_bootstrap.py` and `test_installer.py`. Environment-specific, not product logic. |
| `python dev/scripts/contracts.py --check` | Pass |
| `npm run build` / `npm test` | Not runnable: `web/src/api/sse.ts` is imported by `web/src/api/live.ts` but does not exist in the tree or in git. TS/Rollup build and `live.test.ts` will fail. |
| `npm run test:e2e` | Not runnable: `web/playwright.config.ts` launches `dev/remote_fixture.py`, which does not exist although the README documents it. |
| `docker build` | Not runnable: `Dockerfile` copies `docker/serve_ui.py`, which does not exist. The container smoke test therefore cannot pass. |
| Existing automated coverage | Bridge 20 unit tests; container 5; frontend 3 Vitest tests; Playwright 5 workflows; 2 standalone integration scripts. |
| Claimed vs actual | `plan/execution.md` claims 17 bridge + 4 container + 5 browser tests passed. The current tree has 20/5/5 but with missing runtime fixtures. Treat prior evidence as stale until re-run. |

### Portability notes

- `tests/e2e/workflows.spec.ts` writes a screenshot to `/tmp/...`; use a temp-directory API for Windows.
- Permission assertions should be skipped or marked POSIX-only rather than failing on Windows developers.
- The port-conflict test needs a platform-aware expectation or a fixed port held by a real listener.

### How to run the current suites

```sh
# Bridge + container units
python -m unittest discover -s tests/bridge -v
python -m unittest discover -s tests/container -v
python dev/scripts/contracts.py --check

# Frontend
cd web
npm ci
npm run format:check
npm run build
npm test
npx playwright install chromium
npm run test:e2e

# Real engine / frozen app / image
python tests/bridge/integration_nicotine.py
python tests/bridge/frozen_smoke.py
python tests/container/smoke.py nicotine-webgui:local
```

---

## 5. Test strategy

Risk-based, four automation layers plus a manual release matrix.

| Level | Tooling | Purpose | Gate |
|---|---|---|---|
| L1 Unit | `unittest`, Vitest | Pure logic: store, auth, actions, ingest, adapter boundary, client polling/abort, SSE parser | Every push |
| L2 Contract | `dev/scripts/contracts.py --check` | OpenAPI route/schema ↔ generated TS drift | Every push |
| L3 Integration | `tests/bridge/integration_nicotine.py`, `tests/bridge/frozen_smoke.py` | Real `pynicotine` core, isolated profile, load/unload/rebind, bearer + CORS | CI matrix + release |
| L4 System/UI | Playwright + demo bridge | Login, search/download/pause, chat escaping, session, reconnect, browse/buddy | Every push |
| L5 Deployment | Docker build + `tests/container/smoke.py`, Compose, proxies | Image hardening, health, SPA fallback, graceful shutdown | Every push/release |
| L6 Manual | Real accounts, proxies, soak, accessibility | Things automation cannot represent faithfully | Release |

Test design techniques:

- Equivalence partitioning on inputs (URLs, tokens, usernames, sort fields, limits).
- Boundary analysis on every cap in §3.
- State-transition testing for sessions, SSE, commands, transfers, and shares.
- Negative testing for every documented 4xx.
- Fault injection: abort stream, kill plugin, expire session, drop network, fill queues.

Coverage target: 100% of P0 cases, ≥95% of P1 cases, and every exported operation in `openapi.yaml` exercised at least once by automation or a documented manual case.

---

## 6. Environments and test data

| Env | Configuration |
|---|---|
| E1 Unit (CI) | Ubuntu, Python 3.9 + 3.12, Nicotine+ 3.3.6 + 3.3.11, Node 22 |
| E2 Local | Windows 11, Python 3.13, Node 24 — smoke only, POSIX tests skipped |
| E3 E2E | Chromium; UI `http://127.0.0.1:8181`, demo plugin `https://localhost:8443`, token `demo`, self-signed cert ignored only in Playwright |
| E4 Real plugin | Nicotine+ headless with isolated `--user-data`, no auto-connect, dedicated offline profile |
| E5 Deployment | Docker amd64 + arm64, Nginx TLS and `/nicotine/` prefix, loopback + LAN bind |
| E6 Frozen app | Installed macOS Nicotine+ app, offline profile, SSE soak |
| Browsers | Chromium required; Firefox/WebKit recommended; Safari iOS manual |

Test data:

- Deterministic `FakeAdapter`: 10 000-file search, room `music`, user `alice`, buddy flows.
- Two dedicated Soulseek test accounts for real chat (A↔B), one offline peer for browse/shares.
- Fixtures for oversized bodies (>256 KiB), invalid UTF-8, `+`/`%`/space names, 4096-char names, NUL, duplicate headers.
- Log fixtures with secrets, malformed timestamps, and pre-start messages for backfill.
- TLS: valid cert (proxy), expired/wrong-host cert, self-signed (negative browser test).

No production credentials or real user profiles are used. Every real-engine test runs against a temporary profile.

---

## 7. Test case catalog

Priorities: **P0** release blocker, **P1** required, **P2** desirable. Automation: **A** automated, **M** manual, **N** new test needed.

### 7.1 Baseline, build, and contracts

| ID | Scenario | Expected | Pri | Auto |
|---|---|---|---|---|
| BL-01 | Clean install: `npm ci && npm run build` | Build succeeds, `dist/` generated | P0 | A |
| BL-02 | `npm test` | All Vitest tests pass | P0 | A |
| BL-03 | `python -m unittest discover -s tests/bridge` | All pass on Linux 3.9/3.12 | P0 | A |
| BL-04 | `python -m unittest discover -s tests/container` | All pass on Linux | P0 | A |
| BL-05 | `contracts.py --check` after route/schema edits | No drift | P0 | A |
| BL-06 | Serve `/api/v1/openapi.json` | Valid 3.1 spec, 83 operations, auth schemes present | P1 | N |
| BL-07 | Windows developer run | POSIX-only assertions skipped, port test platform-aware | P2 | N |

### 7.2 Authentication and session

| ID | Scenario | Expected | Pri | Auto |
|---|---|---|---|---|
| AU-01 | Login with correct token, `mode=bearer` | 200, `session_token` + `csrf` + `expires`, no `Set-Cookie` | P0 | A |
| AU-02 | Login with wrong/empty/non-string token | 401 generic message; no token echo | P0 | A |
| AU-03 | 6th login attempt within 60 s | 429 + `Retry-After: 5` | P0 | A |
| AU-04 | Session with no/invalid/expired bearer | 401, UI returns to login | P0 | A |
| AU-05 | Cross-origin bearer session used from another Origin | 403, no data | P0 | A |
| AU-06 | Missing/incorrect CSRF on POST/PATCH/DELETE | 403 before mutation | P0 | A |
| AU-07 | Cookie session still works same-origin | 200 + `HttpOnly; SameSite=Strict` | P1 | A |
| AU-08 | Bearer token presented as cookie | 401 (modes are isolated) | P0 | A |
| AU-09 | Logout invalidates session and open SSE stream | Subsequent request 401; stream closes | P0 | A |
| AU-10 | 33rd concurrent session | 503 busy, no crash | P1 | N |
| AU-11 | Reload tab | Session restored from sessionStorage; no access token stored | P0 | A |
| AU-12 | Plugin restart | Old session invalid; UI offers reconnect | P1 | M |
| AU-13 | Endpoint normalisation: trailing `/`, `/api/v1`, credentials, query, fragment, `%2e` | Rejected or normalised per documented rules | P1 | A |
| AU-14 | HTTP endpoint other than same-origin native UI | Rejected with clear message | P0 | A |

### 7.3 Live updates (SSE)

| ID | Scenario | Expected | Pri | Auto |
|---|---|---|---|---|
| LI-01 | Connect after login | `text/event-stream`, initial `: connected` frame, heartbeat ≤20 s | P0 | A |
| LI-02 | Replay from `Last-Event-ID`/cursor | Missed frames delivered exactly once | P0 | A |
| LI-03 | Cursor older than ring / wrong instance / malformed | `resync` event, client refetches | P0 | A |
| LI-04 | Slow client exceeds queue | Queue flushed, `resync` emitted, `dropped` incremented | P1 | A |
| LI-05 | 17th concurrent stream | 503 capacity, existing streams unaffected | P1 | N |
| LI-06 | Network abort / proxy drop | UI shows “Bridge connection interrupted”, auto-reconnect with same cursor | P0 | A |
| LI-07 | Event arrives during in-flight snapshot | Query refetched after settle; no stale value | P0 | A |
| LI-08 | Split UTF-8 byte and split SSE frame | Parser reassembles correctly (new `sse.ts` tests) | P0 | N |
| LI-09 | Multi-tab: two sessions | Each receives events; logout in one does not corrupt the other beyond its own session | P1 | M |
| LI-10 | 600 s soak (frozen runtime) | 30 heartbeats, no disconnect | P1 | M |
| LI-11 | Plugin process restart during stream | Resync on reconnect, no duplicate commands | P1 | M |

### 7.4 Search and result selection

| ID | Scenario | Expected | Pri | Auto |
|---|---|---|---|---|
| SE-01 | Global search “Ambient works” | 10 000 total reported | P0 | A |
| SE-02 | Virtualised table | <100 DOM rows for 10 000 results, smooth scroll, `aria-rowcount` correct | P0 | A |
| SE-03 | Filter + sort (`virtual_path`, `-size`, invalid field) | Correct rows; invalid sort → 400 | P1 | N |
| SE-04 | Cursor pagination | No gaps/duplicates; stale cursor → 409 `snapshot_changed` | P0 | A |
| SE-05 | Select 1 / 1000 / 1001 / expired IDs | Bounds enforced (400/409) | P1 | A |
| SE-06 | Folder download dedupe | One command per unique user+path | P1 | N |
| SE-07 | 21st active search | 409 “Close an existing search first” | P2 | N |
| SE-08 | Result cap exceeded | Oldest rows evicted, `truncated: true` | P1 | N |
| SE-09 | Delete search | Removed from list and store | P1 | A |
| SE-10 | Room/user-targeted search | Correct mode/target sent; invalid target rejected | P2 | N |

### 7.5 Downloads and uploads

| ID | Scenario | Expected | Pri | Auto |
|---|---|---|---|---|
| TR-01 | Download selected search files | Rows appear in Downloads with path/size | P0 | A |
| TR-02 | Pause / resume / retry / cancel / clear | State transitions reflected in UI and API | P0 | A |
| TR-03 | Upload controls and denial reason | Actions accepted; reason validated | P1 | N |
| TR-04 | Bandwidth limits PATCH/GET | Values persist and echo; invalid numbers rejected | P0 | A |
| TR-05 | Transfer ID stability across events | Same ID used for update/action | P0 | A |
| TR-06 | Large transfer (100 MB+) | Progress updates, pause/resume, no freeze | P1 | M |
| TR-07 | Queueing with multiple peers | Queue position/ETA sane; no duplicate transfers | P1 | M |
| TR-08 | Download while disconnected | Clear error, no phantom row | P1 | M |

### 7.6 Chat (rooms and private)

| ID | Scenario | Expected | Pri | Auto |
|---|---|---|---|---|
| CH-01 | Join room, send message | Message echoed once, input cleared | P0 | A |
| CH-02 | HTML/script payload | Rendered as text, no execution | P0 | A |
| CH-03 | Unread count and read acknowledgement through ID | Only messages ≤ ID read; newer stay unread | P0 | A |
| CH-04 | History paging (`before`, `limit`) | Boundary and max 500 enforced | P1 | N |
| CH-05 | History cap / truncation | Oldest dropped, `truncated: true` | P1 | N |
| CH-06 | Backfill from logs | Pre-start rows merged, duplicates excluded, live rows preserved | P1 | A |
| CH-07 | Malformed/unreadable log | Empty history, no crash | P1 | A |
| CH-08 | Private chat send/receive + unread | Correct conversation and unread badge | P0 | M |
| CH-09 | Room command autocomplete / slash command | Valid command executed; invalid rejected | P2 | M |
| CH-10 | Ctrl/Cmd+Enter sends; Enter behaviour | Matches documented shortcut | P2 | N |
| CH-11 | 101st conversation | Oldest evicted, bounded memory | P2 | N |
| CH-12 | Two-account live chat | A→B and B→A delivered, no duplicates | P1 | M |

### 7.7 People, browse, profiles, discovery

| ID | Scenario | Expected | Pri | Auto |
|---|---|---|---|---|
| PE-01 | Browser tree for `alice`, select file, download | File appears in Downloads | P0 | A |
| PE-02 | Folder filter and expansion | Correct subset; keyboard/ARIA tree behaviour | P1 | N |
| PE-03 | Browse expired IDs | 409 with actionable message | P1 | A |
| PE-04 | Add/update/remove buddy (note, trusted, notify, prioritized) | Persisted and reflected | P0 | A |
| PE-05 | Interests add/remove (likes/dislikes) | Persisted; duplicates handled | P1 | A |
| PE-06 | Wishlist add/remove | Persisted; names with spaces/`+` encoded correctly | P1 | A |
| PE-07 | Recommendations request and display | Results stored and rendered | P2 | N |
| PE-08 | Profile view + picture | Text and data-URL image correct; oversized/invalid picture rejected | P1 | N |
| PE-09 | Ignore / unignore / ban / unban | State change; banned user cannot browse/download | P1 | N |
| PE-10 | Username with `%`, `+`, spaces, slash, 4096 chars, NUL | Correct encoding; invalid rejected 400 | P1 | N |

### 7.8 Shares, plugins, settings, statistics, activity

| ID | Scenario | Expected | Pri | Auto |
|---|---|---|---|---|
| SH-01 | Add share, rescan, rebuild, remove | Correct state and `shares/status` transitions | P1 | A |
| SH-02 | Scan progress while browsing UI | Live status updates, no blocking | P2 | M |
| PL-01 | List plugins | Name/enabled/protected correct | P1 | A |
| PL-02 | Enable/disable non-protected plugin | Succeeds | P2 | N |
| PL-03 | Disable serving plugin `nicotine_webui` | Refused (409/403), bridge stays up | P0 | N |
| PL-04 | Plugin settings read/write | Only whitelisted non-secret fields; secrets/redaction enforced | P0 | A |
| ST-01 | Curated settings read/update | Only exposed sections/fields; invalid types rejected | P1 | A |
| ST-02 | Theme/density/layout persistence | Survives reload; applies on first paint | P2 | M |
| ST-03 | Statistics display | Values match `/statistics` | P2 | M |
| NF-01 | Notifications receive/mark read | Unread badge clears, bounded at 500 | P1 | N |
| NF-02 | Logs redact token and password | No secret substring in `/logs` or UI | P0 | A |
| NF-03 | Log rotation at 2000 entries | Oldest dropped, no unbounded growth | P1 | N |
| NF-04 | Diagnostics endpoint | Counts/revision only; no secrets/PII | P1 | N |

### 7.9 Security suite

| ID | Scenario | Expected | Pri |
|---|---|---|---|
| SEC-01 | `Host: evil.example`, duplicate Host, Host with `/\@?#`, bad port | 403 | P0 |
| SEC-02 | Unlisted Origin on GET/POST | 403; no ACAO header | P0 |
| SEC-03 | Mutation without Origin | 403 | P0 |
| SEC-04 | Preflight disallowed method/header | 403; allowed set is exactly Authorization, Content-Type, X-CSRF-Token, Last-Event-ID | P0 |
| SEC-05 | `Access-Control-Allow-Credentials` | Never emitted for cross-origin bearer flow | P0 |
| SEC-06 | Path traversal (`%2e%2e`, encoded slash/backslash) | 403; cannot escape static root | P0 |
| SEC-07 | Chunked body, duplicate Content-Length, wrong content type, invalid/non-finite JSON | 400/413/415 | P0 |
| SEC-08 | Security headers | `nosniff`, `no-referrer`, `DENY`, CSP, `no-store` on all responses | P1 |
| SEC-09 | Response body never includes access token, password, or secrets | Verified on all reads, errors, logs, diagnostics | P0 |
| SEC-10 | Login timing/constant-time comparison | No meaningful timing signal; no user enumeration | P1 |
| SEC-11 | Error messages | Generic for 500; no stack traces or request data | P0 |
| SEC-12 | Redirect following | `redirect: 'error'`; malicious 302 to attacker not followed | P0 |
| SEC-13 | Rate limit mutations (61/s) | 429; no state corruption | P1 |
| SEC-14 | No file-reading endpoint exists | Only media metadata and 1 MiB profile pictures; no arbitrary paths | P0 |
| SEC-15 | Reverse-proxy duplicate CORS headers | Browser still works; no wildcard/multiple ACAO | P1 |

### 7.10 Resilience, performance, compatibility

| ID | Scenario | Expected | Pri |
|---|---|---|---|
| RS-01 | Port already bound | Plugin start fails cleanly; no orphan thread/callbacks | P0 |
| RS-02 | Plugin disable/enable | Listener closed, port rebound, new instance ID | P0 |
| RS-03 | Event callback raises | Contained; `callback_errors` increments; Nicotine+ unaffected | P0 |
| RS-04 | Main-thread command timeout | Cancelled before run (503) or 202 + pollable ID; never repeated | P0 |
| RS-05 | 48 concurrent HTTP requests | Excess closed; no crash | P1 |
| RS-06 | 30-minute soak with transfers + chat | Stable memory/threads, SSE alive | P1 |
| RS-07 | 10 000-result load | Virtualised render, no jank or DOM blow-up | P0 |
| RS-08 | 12 h session boundary | Expiry handled without data leak | P2 |
| RS-09 | Network loss during mutation | Poll command ID; no duplicate submit | P1 |
| RS-10 | Nicotine+ 3.3.6 / 3.3.11 | Full suite passes | P0 |
| RS-11 | Python 3.9 / 3.12 | Full suite passes | P0 |
| RS-12 | Frozen macOS app | HTTP startup + 600 s SSE, graceful shutdown | P1 |
| RS-13 | Docker amd64 / arm64 | Smoke + upgrade tests pass | P1 |
| RS-14 | Nginx TLS and `/nicotine/` prefix | Login, SSE, mutations work; no redirect | P1 |
| RS-15 | Container upgrade with existing state | No data loss (now stateless UI) | P1 |

### 7.11 UX and accessibility

| ID | Scenario | Expected | Pri |
|---|---|---|---|
| UI-01 | `/` focus search; Ctrl/Cmd+K palette; Alt+1–9; Ctrl/Cmd+Enter | Documented behaviour | P1 |
| UI-02 | Keyboard-only operation of table, tabs, dialogs, login | No traps; visible focus; Esc closes palette | P1 |
| UI-03 | Screen-reader semantics | Landmarks, headings, `role=log/status/alert`, table row/count ARIA | P1 |
| UI-04 | Colour contrast and theme/density combinations | Meets WCAG 2.2 AA | P1 |
| UI-05 | Empty/loading/error states | Clear messages; no blank screens | P2 |
| UI-06 | Long names/paths and narrow viewport | Truncation/no horizontal breakage | P2 |
| UI-07 | Login error copy for TLS/CORS/proxy problems | Actionable, not misleading | P1 |

### 7.12 Install, deployment, and release

| ID | Scenario | Expected | Pri |
|---|---|---|---|
| CF-01 | `install_plugin.py` fresh install | Plugin + config installed, token generated | P0 |
| CF-02 | `--with-ui` install | Static assets copied; bridge-only omits them | P1 |
| CF-03 | Existing account preserved | Credentials unchanged, config backed up `config.pre-webgui` | P0 |
| CF-04 | Idempotent upgrade | No duplicate plugin entries; stale modules removed | P0 |
| CF-05 | Running engine detected | Refuses before writing | P0 |
| CF-06 | `bootstrap.py` first run / missing credentials | Bridge enabled, UPnP off, no credentials invented | P1 |
| CF-07 | Docker image | Non-root, read-only root, `/tmp` tmpfs only, no `pynicotine`, no `/data` or `/config` | P0 |
| CF-08 | Container health | `/health` returns `service: web-ui`; SPA fallback serves `index.html` | P0 |
| CF-09 | Graceful shutdown | Exit code 0 within grace period | P1 |
| CF-10 | Compose loopback publishing | Bound to `127.0.0.1` by default; no Docker socket/volumes | P0 |
| CF-11 | Release pipeline | Build → smoke → Trivy → multi-arch push with SBOM/provenance | P1 |
| CF-12 | Dependency audit | No high/critical advisories | P1 |

---

## 8. Entry and exit criteria

### Entry

1. Missing `web/src/api/sse.ts`, `dev/remote_fixture.py`, and `docker/serve_ui.py` resolved or explicitly declared out of scope.
2. Linux CI baseline green (L1–L5) on the supported matrix.
3. Dedicated offline profiles and test accounts available; no production credentials.
4. Test data and TLS fixtures provisioned.

### Exit (release gate)

1. 100% of P0 cases pass; ≥95% of P1; P2 defects triaged.
2. No open critical/high severity defects; no known security bypass.
3. Contract check and formatting clean; no dependency high/critical advisories.
4. 30-minute soak and 600 s SSE soak pass.
5. Container smoke + amd64/arm64 build pass; upgrade path verified.
6. Manual matrix signed off for macOS frozen app, Linux headless, Nginx TLS/prefix, two-account chat, and accessibility review.

### Suspension

Any P0 security bypass, bridge crash affecting Nicotine+, or data-loss defect suspends the cycle until fixed and re-verified.

---

## 9. Execution phases

| Phase | Focus | Output |
|---|---|---|
| 0. Baseline repair (P0) | Restore/build missing modules; make Windows suite platform-aware; confirm CI | Green L1–L5 baseline |
| 1. Security and auth | SEC, AU suites; proxy/CORS/preflight | Security sign-off |
| 2. Core workflows | SE, TR, CH, PE, BR, SH, ST, NF | Automated regression + E2E expansion |
| 3. Resilience | LI, RS fault injection, soak | Stability report |
| 4. Deployment | CF, Docker, Compose, Nginx, upgrade | Deployment sign-off |
| 5. Compatibility and UX | Compatibility matrix, accessibility, manual matrix | Release recommendation |

Cadence: L1–L5 on every PR; L6 and soak matrices per release candidate and before publishing a versioned artifact.

---

## 10. Automation backlog (highest value first)

1. Recreate `web/src/api/sse.ts` plus unit tests for split UTF-8/frames, heartbeat, and abort (LI-08).
2. Recreate `dev/remote_fixture.py` so the existing 5 Playwright workflows can run again; remove the `/tmp` screenshot path.
3. Add Docker `serve_ui.py` or correct the Dockerfile; then run container smoke in CI.
4. Expand Playwright: session expiry, reconnect/resync, room unread, folder download, limits, notifications, log redaction, keyboard shortcuts.
5. Add API cases for the ~60 untested operations (shares, plugins, private chat, notifications, moderation, picture, diagnostics, openapi).
6. Make POSIX permission and port-conflict tests platform-aware; add a Windows CI lane if Windows is supported.
7. Add a real two-account integration scenario, gated on secrets and scheduled (not per-PR).
8. Add accessibility automation (`@axe-core/playwright`) and a 30-minute soak job.

---

## 11. Defect severity

| Severity | Definition | Example |
|---|---|---|
| Critical | Security bypass, credential leak, bridge takes down Nicotine+, data loss | Cross-origin token theft; callback exception kills client |
| High | Core workflow broken, no workaround | Cannot download; login fails on supported proxy |
| Medium | Workflow degraded or inconsistent state with workaround | Unread count wrong; reconnect requires reload |
| Low | Cosmetic/usability/documentation | Misaligned column; unclear error copy |

Triage SLA: Critical same day, High before release, Medium next cycle, Low backlog.

---

## 12. Traceability

| Feature | Primary cases |
|---|---|
| Container / static serving | CF-07…CF-10, BL-01 |
| Login, sessions, endpoint validation | AU-01…AU-14, SEC-01…SEC-05 |
| Live updates / SSE | LI-01…LI-11, RS-06 |
| Search and virtualization | SE-01…SE-10, RS-07 |
| Downloads / uploads / limits | TR-01…TR-08, RS-01, RS-04 |
| Rooms / private chat / unread / backfill | CH-01…CH-12, NF-02 |
| Browse / profiles / people / discovery | PE-01…PE-10 |
| Shares / plugins / settings / statistics | SH-01…SH-02, PL-01…PL-04, ST-01…ST-03 |
| Notifications / logs / diagnostics | NF-01…NF-04 |
| Security posture | SEC-01…SEC-15 |
| Compatibility / release | RS-10…RS-15, CF-11, CF-12 |
| Accessibility / shortcuts | UI-01…UI-07 |

---

## 13. Assumptions and open questions

1. The three missing files (`sse.ts`, `remote_fixture.py`, `serve_ui.py`) are treated as accidental omissions until confirmed; Phase 0 is blocked without them.
2. Windows is currently a developer convenience, not a supported server platform; POSIX-only assertions are expected to be skipped there.
3. Real-engine chat/download/proxy cases require dedicated test accounts and a reachable Nicotine+ host; without them those cases remain documented manual prerequisites.
4. Nginx is the only proxy with a reference configuration; other proxies are validated against the same header/streaming requirements rather than vendor-specific configs.
5. The UI container is stateless, so upgrade tests assert configuration/asset replacement rather than data migration.

---

## 14. Test summary report template

At the end of each cycle, record:

- Build/tag, commit, environment matrix, and date.
- Cases executed/passed/failed/skipped by suite and priority.
- Defects by severity, with links and status.
- Contract, dependency audit, image scan, and soak results.
- Deviations from this plan and their justification.
- Release recommendation: pass / conditional pass / fail, with named approvers.
