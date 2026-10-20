# Nicotine Web GUI — Design and Implementation Plan

Status: Draft for implementation
Date: 2026-10-20
Target: Nicotine+ 3.3.x (verified against 3.3.6)
Repository: `/Users/mitchel/dev/nicotine-webgui` (currently empty)

---

## 1. Summary

Build a browser-based remote control and live viewer for a running Nicotine+ client.

- Nicotine+ remains the Soulseek engine. It owns the protocol connection, shares, uploads, downloads, and port handling.
- A **Nicotine+ plugin** embeds an HTTP API and an event stream inside the Nicotine+ process.
- A **React single-page app** consumes that API.

The web app does not talk to Soulseek directly. If Nicotine+ is not running, the web app is offline and cannot function on its own.

### Goals

- Reach feature parity with the desktop client for the core workflows: search, downloads, uploads, chat rooms, and private chat.
- Feel like a desktop-class tool in the browser: dense tables, live progress, keyboard navigation, persistent tabs.
- Require no third-party Python packages inside Nicotine+.
- Ship as a **Docker image** with a `Dockerfile` and `compose.yaml`, so the whole stack runs as one service.
- Be installable in minutes from a single build artifact or a published image.
- Keep the web UI reachable only from the host loopback interface, including in the container deployment.

### Non-goals

- Reimplementing the Soulseek protocol.
- Multi-user accounts or per-user permissions.
- LAN, Internet, or mobile-remote deployment.
- Streaming completed files through the browser. Files remain on the Nicotine+ machine.
- Uploading files from the browser into shares. Shares are configured by server-side paths.
- A separate web-server container. The bridge must run inside the Nicotine+ process.
- Kubernetes, Helm charts, or multi-container orchestration beyond Docker Compose.
- Full settings parity in the first release.
- Modifying Nicotine+ itself.

---

## 2. Verified environment constraints

These findings were checked against the local installation and the Nicotine+ 3.3.6 source.

| Fact | Consequence |
|---|---|
| Nicotine+ 3.3.6 installed at `/Applications/Nicotine+.app` | Primary target for development |
| The app bundle runs Python **3.12** (PyInstaller, hardened runtime, not sandboxed) | Plugin code must work inside this interpreter |
| User data folder is `~/.local/share/nicotine`; user plugins load from `~/.local/share/nicotine/plugins` | Plugin install location |
| Config is `~/.config/nicotine/config`; logs are under `~/.local/share/nicotine/logs` | Settings and log backfill sources |
| `library.zip` includes `http.server`, `socketserver`, `ssl`, `secrets`, `mimetypes`, `wsgiref`, `hashlib`, `json`, `queue` | A stdlib-only HTTP server is viable |
| `library.zip` has no `websockets`, `flask`, `fastapi`, or `uvicorn`; Nicotine+ cannot install packages | Use REST + Server-Sent Events, not WebSocket |
| `pynicotine.events` exposes ~149 internal events and `events.invoke_main_thread()` | The plugin can observe all state and marshal commands to the main thread |
| `PluginHandler` calls `plugin.disable()` on unload/reload | The bridge can release its port deterministically |
| Search results, message history, browse trees, and profiles are held by the GTK UI, not core | The plugin must maintain its own state mirror |
| Chat messages are delivered to plugins once each via notification callbacks | Reliable source for message history |
| `--headless` and `--user-data` CLI flags exist | Same plugin runs headless; isolated dev/test instances |
| Headless startup imports **stdlib only**; PyGObject is not needed at runtime | The image can install Nicotine+ with `--no-deps`, keeping it small |
| `nicotine-plus` publishes wheels and sdists on PyPI (latest 3.3.11; 3.3.6 available) | Install a pinned wheel in the image; no build toolchain needed |
| `XDG_DATA_HOME` and `XDG_CONFIG_HOME` determine data and config paths | Container volumes can be mapped deterministically to `/data` and `/config` |
| Plugin settings are persisted in `config.sections["plugins"][name]` and editable in Preferences → Plugins | Host/port/token can live there |

---

## 3. Architecture

```
+------------------------------ Browser ------------------------------+
|  React SPA (Vite static build, served by the plugin)               |
|  REST client + TanStack Query        EventSource (SSE)              |
+--------------+--------------------------------+---------------------+
               | JSON /api/v1/*                 | /api/v1/events
+--------------v--------------------------------v---------------------+
|  Nicotine+ process                                                 |
|                                                                    |
|  +------------------- Plugin: nicotine_webui -------------------+  |
|  | HTTP server (ThreadingHTTPServer, stdlib)                    |  |
|  |   auth | router | static | SSE hub | rate limit              |  |
|  |                                                              |  |
|  | StateStore (mirror) <-- event handlers (main thread)         |  |
|  | Actions --> events.invoke_main_thread() --> core.*           |  |
|  +--------------------------------------------------------------+  |
|                                                                    |
|  pynicotine.core: users, chatrooms, privatechat, search,           |
|  downloads, uploads, shares, buddies, interests, userbrowse,       |
|  userinfo, config, pluginhandler                                   |
+--------------------------------------------------------------------+
```

In container deployment, the entire diagram below the browser is one Docker service. Nicotine+ runs with `--headless`; the plugin serves the SPA and API on port 8181. The container's only loopback-exposed port is the web UI. The Soulseek peer port is published separately for uploads.

### Key decisions

| Decision | Choice | Rationale |
|---|---|---|
| Transport | REST + SSE | SSE needs no dependencies, reconnects automatically, and commands are ordinary HTTP |
| Web server location | Inside the plugin, `ThreadingHTTPServer` | No second process, no packaging, no dependency install |
| State ownership | Plugin-owned mirror, seeded from core, updated by events | Core discards search results and messages after the GTK UI consumes them |
| Static assets | SPA build copied into the plugin folder | One artifact, same origin, no CORS in production |
| Concurrency | Mutations marshaled to the main thread; reads from snapshots | Avoids GTK and protocol thread races |
| Auth | Generated token -> HttpOnly session cookie + CSRF header | Minimal friction on localhost, no account database |
| Binding | `127.0.0.1` natively; `0.0.0.0` inside the container with the host port published to `127.0.0.1` | Keeps the UI loopback-only on both deployment paths |
| Packaging | Single multi-stage Docker image (`web` build stage + `python:3.12-slim` runtime) with Compose | One service, reproducible install, works on a headless server or NAS |

### Rejected alternatives

- **Separate backend process:** adds a process to install and supervise, plus an IPC protocol, without adding capability. The plugin still has to serialize everything.
- **WebSocket:** requires vendoring a pure-Python implementation or writing RFC 6455 framing. SSE already covers server-to-client; commands are request/response.
- **Driving Nicotine+ through its CLI:** commands only, no state or events.
- **Patching Nicotine+:** violates the plugin requirement and complicates upgrades.

---

## 4. Bridge plugin design

### 4.1 Lifecycle

```python
class Plugin(BasePlugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = {
            "host": "127.0.0.1",
            "port": 8181,
            "token": "",
            "history_limit": 500,
            "result_limit": 10000,
            "log_limit": 2000,
        }
        self.metasettings = { ... }  # editable in Preferences -> Plugins

    def init(self):
        self.bridge = WebBridge(self)  # registers events, starts server thread
        self.bridge.start()

    def disable(self):
        self.bridge.stop()  # close listener, close SSE clients, join threads
```

- `init()` and all event callbacks run on the Nicotine+ main thread.
- `disable()` runs on unload/reload and must be idempotent.
- If the configured port is in use, log a clear error and do not crash Nicotine+.
- Generate a token on first start with `secrets.token_urlsafe(32)` and persist it through plugin settings.
- Environment variables `NICOTINE_WEBUI_HOST`, `NICOTINE_WEBUI_PORT`, `NICOTINE_WEBUI_TOKEN`, and `NICOTINE_WEBUI_TRUSTED_HOSTS` override persisted settings, which is how Compose configures the container.

### 4.2 Plugin module layout

```
plugin/
├── PLUGININFO
├── __init__.py            # Plugin class, settings, lifecycle
└── webgui/
    ├── server.py          # ThreadingHTTPServer, static files, SSE
    ├── router.py          # (method, path) -> handler table
    ├── auth.py            # token, sessions, CSRF, rate limiting
    ├── sse.py             # per-client queues, heartbeat, replay ring
    ├── store.py           # thread-safe state mirror and revisions
    ├── ingest.py          # internal event -> normalized state/event
    ├── actions.py         # main-thread command execution
    ├── serializers.py     # core objects -> JSON-safe models
    ├── adapter.py         # thin wrapper over core, version/feature flags
    └── static/            # built SPA (index.html, assets/)
```

`adapter.py` is the only module that imports `pynicotine` internals. Everything else depends on a small interface, which makes unit testing with a fake core possible.

### 4.3 Threading rules

1. Event handlers are the only writers to `StateStore`, and they run on the main thread.
2. HTTP threads read snapshots under a short-lived `RLock`. Serialization happens outside the lock.
3. All core mutations go through `events.invoke_main_thread(fn)` with a `Future` and a 5-second timeout.
4. If the main thread is busy, return `503 busy` with a retry hint rather than hanging.
5. SSE writers use bounded `queue.Queue` instances and never call core.
6. On queue overflow, send a `resync` event instead of blocking.
7. Plugin callbacks must be quick: copy primitives, update the mirror, enqueue. No disk I/O on the main thread.

### 4.4 State mirror

| Domain | Source |
|---|---|
| Session and connection | `core.users` (`login_status`, `login_username`, privileges, away), `server-login`, `server-disconnect`, `user-status` |
| Rooms | `core.chatrooms.joined_rooms`, `room-list`, `join-room`, `leave-room`, `user-joined-room`, `user-left-room` |
| Room messages | `incoming_public_chat_notification`, `outgoing_public_chat_notification` |
| Room tickers | `ticker-add`, `ticker-remove`, `ticker-state` |
| Private chats | `core.privatechat.users`, `incoming_private_chat_notification`, `outgoing_private_chat_notification`, `user-status` |
| Searches | own `SearchRequest` mirror plus `file-search-response` accumulation (same approach as `gtkgui/search.py`) |
| Downloads | `core.downloads.transfers`, `update-download`, `file-transfer-init`, `file-download-progress`, `abort-download`, `clear-download` |
| Uploads | `core.uploads.transfers`, `update-upload`, `upload-queued`, `upload-start`, `abort-upload`, `clear-upload` |
| Browse | `shared-file-list-response`, `core.userbrowse.users` |
| User info | `user-info-response`, `core.users.statuses`, `core.users.stats`, `core.users.countries` |
| Buddies | `core.buddies.users`, `add-buddy`, `remove-buddy`, `buddy-*` |
| Interests | `core.interests`, `add-interest`, `add-dislike`, `remove-interest`, `remove-dislike`, recommendations events |
| Shares | `core.shares`, `shares-scanning`, `shares-preparing`, `shares-ready`, `shares-unavailable` |
| Statistics | `update-stat` |
| Logs and notifications | `log-message`, `show-notification` |

Event subscriber names are registered in `ingest.py`; the adapter declares which events exist for the running Nicotine+ version.

### 4.5 Identifiers

| Resource | ID |
|---|---|
| Transfer | `sha1(username + "\0" + virtual_path)`, first 20 hex chars; server keeps a map to the live `Transfer` |
| Search | Nicotine+ numeric search token |
| Room or user | Raw name, URL-encoded in routes |
| Browse entry | Hashed `username|folder|filename`, plus the real virtual path for actions |
| Message | Monotonic server sequence number per conversation |

### 4.6 Bounds and persistence

- 10,000 search results per search (configurable).
- 500 messages per room or conversation.
- 2,000 log lines.
- Ring buffer of 1,000 SSE events for replay.
- On overflow: keep the newest entries, set `truncated=true`, inform the UI.
- Persistence is not required for the MVP. A later version may add SQLite in the plugin data folder and backfill from Nicotine+'s chat logs.

---

## 5. API

Base path: `/api/v1`

### 5.1 Envelope

```json
{ "ok": true, "data": {}, "revision": 1421 }
{ "ok": false, "error": { "code": "not_connected", "message": "Not connected to Soulseek" } }
```

- `revision` increases monotonically with each state change.
- HTTP status codes: 200 success, 202 accepted for async commands, 400 validation, 401 unauthenticated, 403 forbidden, 404 unknown resource, 409 state conflict, 429 rate limited, 503 busy or unavailable.

### 5.2 Authentication and security headers

- `POST /auth/login` with `{ "token": "..." }` creates an in-memory session and sets `npw_session` as HttpOnly, SameSite=Strict, Path=/.
- `POST /auth/logout` destroys the session.
- `GET /session` returns the CSRF token and session metadata.
- Mutating requests require `X-CSRF-Token`.
- Reject requests whose `Host` header is not `127.0.0.1:<port>` or `localhost:<port>`; this blocks DNS rebinding.
- Validate `Origin` on mutating requests.
- Rate-limit login attempts (5/min) and mutations (60/s burst).
- Compare tokens with `hmac.compare_digest`.

### 5.3 MVP endpoints

| Domain | Method and path | Purpose |
|---|---|---|
| Auth | `POST /auth/login` | Token login |
| Auth | `POST /auth/logout` | End session |
| Auth | `GET /session` | Session, CSRF token, capabilities |
| System | `GET /status` | Connection, username, away, privileges, speeds, shares state |
| System | `POST /connect`, `POST /disconnect` | Connection control |
| System | `POST /away` | Away toggle |
| Meta | `GET /health`, `GET /meta`, `GET /openapi.json`, `GET /diagnostics` | Liveness (unauthenticated), version, features, health |
| Events | `GET /events` | SSE stream with `Last-Event-ID` replay |
| Searches | `GET /searches` | List open searches |
| Searches | `POST /searches` | `{term, mode, room?, users?}` |
| Searches | `GET /searches/{token}?sort=&filter=&cursor=&limit=` | Paginated results |
| Searches | `DELETE /searches/{token}` | Close search |
| Searches | `POST /searches/{token}/downloads` | Download selected files |
| Searches | `POST /searches/{token}/folder-downloads` | Download folders |
| Downloads | `GET /downloads?status=&user=&q=` | List with summaries |
| Downloads | `POST /downloads` | Enqueue `{username, virtual_path, size?, folder_path?}` |
| Downloads | `POST /downloads/actions` | `{ids, action}`: pause, resume, retry, cancel, clear, ban |
| Uploads | `GET /uploads?status=&user=&q=` | List with summaries |
| Uploads | `POST /uploads/actions` | `{ids, action, message?}`: retry, cancel, clear, deny |
| Limits | `GET /transfers/limits`, `PATCH /transfers/limits` | Download/upload caps, slots, alternate limits |
| Rooms | `GET /rooms` | Joined rooms with unread counts |
| Rooms | `GET /rooms/available?q=` | Server room list |
| Rooms | `POST /rooms` | Join `{name}` |
| Rooms | `DELETE /rooms/{name}` | Leave |
| Rooms | `GET /rooms/{name}/messages?before=&limit=` | History |
| Rooms | `POST /rooms/{name}/messages` | Send message |
| Rooms | `GET /rooms/{name}/users` | Users with status |
| Rooms | `POST /rooms/{name}/commands` | Plugin command `{command, args}` |
| Private | `GET /private` | Conversations with unread |
| Private | `GET /private/{user}/messages?before=&limit=` | History |
| Private | `POST /private/{user}/messages` | Send message |
| Private | `POST /private/{user}/read` | Clear unread |
| Users | `POST /users/{user}/ignore`, `/unignore` | Ignore list |
| Notifications | `GET /notifications`, `POST /notifications/read` | Bell and toasts |
| Logs | `GET /logs?level=&limit=` | Ring buffer |

Deliberately absent: any endpoint that reads or streams local files.

### 5.4 Post-MVP endpoints

| Domain | Endpoints |
|---|---|
| Wishlist | `GET/POST/DELETE /wishlist`, `PATCH /wishlist/settings` |
| Browse | `GET /users/{user}/browse`, `POST /users/{user}/browse`, `POST /users/{user}/downloads` |
| Profiles | `GET /users/{user}`, `POST /users/{user}/refresh`, `GET /users/{user}/picture` |
| Moderation | `POST /users/{user}/ban`, `/unban` |
| Buddies | `GET/POST /buddies`, `PATCH/DELETE /buddies/{user}` |
| Interests | `GET /interests`, `POST/DELETE /interests/{kind}`, `GET /recommendations` |
| Shares | `GET/POST /shares`, `DELETE /shares/{id}`, `POST /shares/rescan`, `POST /shares/rebuild`, `GET /shares/status` |
| Plugins | `GET /plugins`, `POST /plugins/{name}/enable|disable|reload`, `GET/PATCH /plugins/{name}/settings` |
| Settings | `GET/PATCH /settings` (curated, validated, secrets redacted) |
| Statistics | `GET /statistics` |

### 5.5 SSE event catalog

```
connection.changed     user.status             room.joined / room.left
room.message           room.users              room.ticker
private.message        private.unread          search.created
search.results         search.removed          transfer.download
transfer.upload        transfer.limits         browse.progress
browse.updated         user.info               buddies.updated
interests.updated      shares.scan             shares.ready
plugins.updated        notification            log
statistics.updated     resync
```

Event frame:

```
id: 1421
event: room.message
data: {"room":"music","user":"alice","message":"hi","ts":1729440000}
```

- Heartbeat comment every 20 seconds.
- `search.results` and transfer progress are batched every 200–300 ms per client.
- Progress events carry only the transfer ID and changed fields.
- If `Last-Event-ID` is older than the replay ring, send `resync` and require a snapshot refetch.

---

## 6. Web application

### 6.1 Stack

- React 19 + TypeScript + Vite
- TanStack Query for server state and SSE cache patching
- TanStack Table and TanStack Virtual for dense, virtualized lists
- Zustand for tabs, layout, filters, and unread counts, persisted to `localStorage`
- React Router
- Tailwind CSS with Radix primitives
- Vitest and Playwright

Node 22 LTS is required for development only. The shipped artifact is static files.

### 6.2 Routes

```
/login
/search
/search/:token
/downloads
/uploads
/rooms
/rooms/:name
/private
/private/:user
/notifications
/settings
/stats
```

Post-MVP routes:

```
/browse/:user
/users/:user
/buddies
/interests
/shares
/plugins
```

Each resource can be opened as a workspace tab. Tabs store IDs and UI preferences only; the URL is authoritative for the open resource.

### 6.3 Wireframe

```
+----------------------------------------------------------------------------+
| Menu  Nicotine Web   [ Search Soulseek...            ]  Online  down/up  bell |
+----------+-----------------------------------------------------------------+
| Search   |  aphex twin   [Global v]                      [New search]       |
| Transfers| +-------------------------------------------------------------+ |
|  down 12 | | File                 Folder       Size    Bitrate  User      | |
|  up 3    | | Selected Ambient...  /music/     42.1MB  320kbps  user1     | |
| Rooms 4  | | ...                                                         | |
| Private 2| +-------------------------------------------------------------+ |
| Buddies  |  1,284 results - 42 users - updating...    [Download] [Browse]   |
| Browse   |                                                                 |
| Interests|                                                                 |
| Shares   |                                                                 |
| Settings |                                                                 |
+----------+-----------------------------------------------------------------+
```

### 6.4 MVP screens

| Screen | Contents |
|---|---|
| Login | Token entry, error handling, session persistence |
| Search | Global/rooms/user/buddies modes, history, virtualized result table, multi-select, download file and folder, result counts, truncation indicator |
| Downloads | Summary cards, active/queued/completed/failed, progress, speed, ETA, pause/resume/retry/cancel/clear, ban user, limits |
| Uploads | Queue and active, per-user queue position, slots and bandwidth state, retry/cancel/clear, deny with message |
| Rooms | Discover/join/leave, message thread, user list, composer with command autocomplete, unread badges, read-only tickers |
| Private | Conversation list, unread, message thread, composer, add buddy, ignore |
| Status | Connection chip, own user, away toggle, connect/disconnect, live speeds |
| Notifications | Toasts and notification list |
| Settings | Bridge settings only (port, token, limits), read-only |

### 6.5 Post-MVP screens

- Browse tree with folder/file selection and downloads.
- User profile with picture, description, stats, interests, similar users.
- Buddy management with notes and notify/trusted/prioritized toggles.
- Interests and recommendations.
- Shares with permissions, add/remove, rescan/rebuild and live progress.
- Plugin management and curated settings.
- Statistics.
- Responsive/mobile layout and PWA install.

### 6.6 Design language

- Dark-first, neutral zinc/slate surfaces, one teal/cyan accent for primary actions and connection state.
- Amber for queue states, red for failures, green for online.
- Dense 12–14 px tables, tabular numerals, sticky headers, resizable columns.
- Clear loading, empty, and error states.
- Optimistic updates with event-driven reconciliation.
- Full keyboard navigation, visible focus, ARIA labels on icon buttons, reduced-motion support.
- Shortcuts: `/` focuses search, `Ctrl/Cmd+K` opens the command palette, `Ctrl/Cmd+Enter` sends, `Alt+1..9` switches sections.

### 6.7 Client state model

- Query keys: `['status']`, `['searches']`, `['search', token, filters]`, `['downloads', filters]`, `['uploads', filters]`, `['rooms']`, `['room', name]`, `['private', user]`.
- SSE events patch caches or invalidate targeted queries.
- On `resync` or reconnect: invalidate everything, refetch snapshots, then resume deltas.
- UI state in Zustand; server data in TanStack Query. No duplication.

---

## 7. Repository layout

```
nicotine-webgui/
├── plugin/                      # installed into the Nicotine+ plugins folder
│   ├── PLUGININFO
│   ├── __init__.py
│   └── webgui/
│       ├── server.py router.py auth.py sse.py store.py
│       ├── ingest.py actions.py serializers.py adapter.py
│       └── static/              # build output
├── web/                         # SPA source
│   ├── src/
│   │   ├── api/                 # client, types.gen.ts, sse.ts, queries/
│   │   ├── app/                 # router, providers, layout
│   │   ├── components/          # ui/, DataTable, Chat, forms
│   │   ├── features/            # search/ transfers/ rooms/ private/
│   │   │                        # users/ buddies/ interests/ shares/
│   │   │                        # plugins/ settings/ stats/ notifications/
│   │   ├── stores/
│   │   └── styles/
│   ├── package.json
│   └── vite.config.ts
├── docker/
│   ├── entrypoint.sh            # plugin sync, config bootstrap, exec
│   └── bootstrap.py             # first-run config seeding
├── Dockerfile                   # multi-stage: SPA build + headless Nicotine+
├── compose.yaml                 # single-service deployment
├── .dockerignore
├── .env.example                 # WEBUI_TOKEN, PUID, PGID, TZ
├── dev/
│   ├── mock-bridge/             # fake API and scripted SSE fixtures
│   └── scripts/                 # build-and-install, run-headless-dev, docker-dev
├── docs/                        # ARCHITECTURE, API, PLUGIN, SECURITY, DEPLOYMENT
├── tests/
│   ├── plugin/                  # pytest with a fake adapter
│   ├── container/               # image build, health, permissions, first-run
│   └── e2e/                     # Playwright
└── README.md
```

## 8. Container deployment

The primary deliverable is a Docker image. The image contains headless Nicotine+, the bridge plugin, and the built SPA. Compose runs it as a single service.

### 8.1 Image design

Multi-stage build:

- **Web stage:** `node:22-alpine` builds the SPA.
- **Runtime stage:** `python:3.12-slim-bookworm` installs a pinned Nicotine+ wheel, copies the plugin and built assets, runs as a non-root user.

Headless Nicotine+ imports only the standard library, so `pip install --no-deps` is intentional: it avoids PyGObject and the GTK toolchain entirely.

```dockerfile
# syntax=docker/dockerfile:1.7

FROM node:22-alpine AS web
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime

ARG NICOTINE_VERSION=3.3.6
ARG UID=1000
ARG GID=1000

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    XDG_DATA_HOME=/data \
    XDG_CONFIG_HOME=/config \
    NICOTINE_WEBUI_HOST=0.0.0.0 \
    NICOTINE_WEBUI_PORT=8181

RUN groupadd --gid "${GID}" nicotine \
 && useradd --uid "${UID}" --gid nicotine --create-home nicotine

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

# Headless mode is stdlib-only; PyGObject is not required.
RUN pip install --no-deps "nicotine-plus==${NICOTINE_VERSION}"

COPY plugin/ /opt/nicotine-webgui/plugin/
COPY --from=web /build/dist /opt/nicotine-webgui/plugin/webgui/static
COPY docker/entrypoint.sh docker/bootstrap.py /usr/local/bin/

RUN chmod 0755 /usr/local/bin/entrypoint.sh \
 && mkdir -p /data /config /shares \
 && chown -R nicotine:nicotine /data /config

USER nicotine
EXPOSE 8181 2234/tcp 2234/udp

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8181/api/v1/health', timeout=3)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "-m", "pynicotine", "--headless"]
```

- `NICOTINE_VERSION` defaults to **3.3.6**, the version verified locally. CI also builds against the latest 3.3.x to catch drift.
- The SPA build is not present in the final image; only `dist/`.
- `.dockerignore` excludes `.git`, `node_modules`, `web/dist`, `config`, `data`, `downloads`, `shares`, and `.env`, keeping the build context and image small.
- Pin published images by tag and digest.
- Build for `linux/amd64` and `linux/arm64` (NAS and Raspberry Pi).

### 8.2 Compose

```yaml
name: nicotine-webgui

services:
  nicotine:
    image: ghcr.io/OWNER/nicotine-webgui:latest
    build:
      context: .
      args:
        NICOTINE_VERSION: "3.3.6"
    container_name: nicotine-webgui
    restart: unless-stopped
    environment:
      TZ: ${TZ:-UTC}
      NICOTINE_WEBUI_HOST: 0.0.0.0
      NICOTINE_WEBUI_PORT: "8181"
      NICOTINE_WEBUI_TOKEN: ${WEBUI_TOKEN:?set WEBUI_TOKEN in .env}
      NICOTINE_WEBUI_TRUSTED_HOSTS: localhost,127.0.0.1
      NICOTINE_USERNAME: ${NICOTINE_USERNAME:-}
      NICOTINE_PASSWORD: ${NICOTINE_PASSWORD:-}
      NICOTINE_SHARES: ${NICOTINE_SHARES:-}
    ports:
      - "127.0.0.1:8181:8181"   # web UI: host loopback only
      - "2234:2234/tcp"          # Soulseek peer connections (uploads)
      - "2234:2234/udp"          # Soulseek peer connections
    volumes:
      - ./config:/config
      - ./data:/data
      - ./downloads:/data/nicotine/downloads
      - ./shares:/shares:ro
    user: "${PUID:-1000}:${PGID:-1000}"
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8181/api/v1/health', timeout=3)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 90s
    stop_grace_period: 30s
```

`read_only: true` is the target. Validate it in M2; if Nicotine+ needs another writable path, add a narrow `tmpfs` or volume instead of disabling it.

### 8.3 Volumes

| Host | Container | Contents |
|---|---|---|
| `./config` | `/config` | `nicotine/config`, the INI file including plugin settings |
| `./data` | `/data` | `nicotine/` data: plugin, logs, transfers, share databases |
| `./downloads` | `/data/nicotine/downloads` | Completed downloads, for easy host access |
| `./shares` | `/shares` (read-only) | Music or media shared to Soulseek |

Because `XDG_DATA_HOME=/data`, Nicotine+ actually writes to `/data/nicotine`. The plugin is synced to `/data/nicotine/plugins/nicotine_webui` on every start.

On Linux, create the directories with matching ownership before first start:

```bash
mkdir -p config data downloads shares
sudo chown -R 1000:1000 config data downloads
```

### 8.4 Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `NICOTINE_WEBUI_HOST` | `0.0.0.0` in the image | Bind address inside the container |
| `NICOTINE_WEBUI_PORT` | `8181` | Web UI port |
| `NICOTINE_WEBUI_TOKEN` | required by Compose; generated and persisted natively | Login token |
| `NICOTINE_WEBUI_TRUSTED_HOSTS` | `localhost,127.0.0.1` | Host-header allowlist for DNS-rebinding protection |
| `TZ` | `UTC` | Log and message timestamps (tzdata is installed) |
| `PUID` / `PGID` | `1000` | Host UID/GID for volume permissions |
| `NICOTINE_USERNAME` / `NICOTINE_PASSWORD` | unset | Optional non-interactive first-run bootstrap |
| `NICOTINE_SHARES` | unset | Optional shared folder; seeded on first run only if non-empty |

Plugin settings resolve in this order: environment variable, then persisted plugin setting, then default.

### 8.5 Entrypoint behavior

`docker/entrypoint.sh` runs before Nicotine+ and must be idempotent:

1. Create `/data/nicotine/{plugins,downloads,incomplete,logs}` and `/config/nicotine`.
2. Sync the plugin and built SPA from `/opt/nicotine-webgui/plugin` into `/data/nicotine/plugins/nicotine_webui`, so image upgrades refresh static assets automatically.
3. If `/config/nicotine/config` is missing and `NICOTINE_USERNAME`/`NICOTINE_PASSWORD` are set, seed the server section and enable the plugin.
4. If the config exists, ensure `[plugins] enable = True` and `nicotine_webui` is in the `enabled` list. Never overwrite an existing login.
5. Seed `[transfers] shared` from `NICOTINE_SHARES` only on first run, and only when the directory exists and is not empty.
6. Set `upnp = False` by default in containers; bridge networking usually breaks UPnP.
7. Exec the container command so signals reach Nicotine+ and it can save state on shutdown.

Config edits use `configparser` with `interpolation=None` and must only run while Nicotine+ is stopped, which is guaranteed at entrypoint time.

### 8.6 First run

Three supported paths:

1. **Interactive (recommended)**
   ```bash
   docker compose run --rm -it nicotine
   ```
   Complete the headless username/password prompts, then exit and run `docker compose up -d`. The created `/config` is reused.

2. **Environment bootstrap**
   ```bash
   NICOTINE_USERNAME=me NICOTINE_PASSWORD=secret docker compose up -d
   ```
   Convenient for automation, but the password lives in the environment and in the plaintext Nicotine+ config. Document the trade-off.

3. **Existing installation**
   Mount an existing `config` and `data` directory from a previous Nicotine+ setup.

After startup, open `http://127.0.0.1:8181` and log in with `WEBUI_TOKEN`.

### 8.7 Networking and port forwarding

- The Soulseek **server** connection is outbound to `server.slsknet.org:2242`; no inbound mapping is needed for searching or downloading.
- **Uploads** need the peer listening port reachable. Map `2234/tcp` and `2234/udp` and forward the same port on the router.
- If `portrange` is changed, publish that range instead.
- Disable UPnP in the container and forward manually.
- On Linux, `network_mode: host` is a fallback if peer connectivity is unreliable behind bridge networking. It removes port isolation, so it is opt-in.
- Docker-published ports can bypass host firewall rules. Publishing to `127.0.0.1` is the control that keeps the web UI local.
- To reach the UI from another machine without exposing it, use an SSH tunnel:
  ```bash
  ssh -L 8181:127.0.0.1:8181 user@docker-host
  ```
- LAN access requires changing the port mapping to `8181:8181`, adding the host to `NICOTINE_WEBUI_TRUSTED_HOSTS`, and accepting that the UI is no longer loopback-only. It is not part of the supported default.

### 8.8 Health and lifecycle

- `GET /api/v1/health` is unauthenticated and returns `200` with `{status, version, uptime, connected}`.
- Health means the web server is alive. A logged-out Soulseek client is still healthy.
- `stop_grace_period: 30s` lets Nicotine+ save transfers, buddies, and config.
- `restart: unless-stopped` handles crashes and host reboots.
- Pin the image and back up `./config` and `./data` before upgrades.

### 8.9 Publishing

- GitHub Actions builds and pushes to GHCR on tags and `main`.
- Tags: `latest`, `vX.Y.Z`, `sha-<short>`.
- Build with `docker buildx` for `linux/amd64` and `linux/arm64`.
- Generate SBOM and provenance attestations; run a vulnerability scan before publishing.

## 9. Build, install, and development workflow

### Container install (primary)

```bash
git clone https://github.com/OWNER/nicotine-webgui.git
cd nicotine-webgui
cp .env.example .env
# set WEBUI_TOKEN to a long random value

# First run only: create the Soulseek login interactively
docker compose run --rm -it nicotine

docker compose up -d
docker compose logs -f nicotine
```

Then open `http://127.0.0.1:8181`.

For a published image, run `docker compose pull && docker compose up -d` instead of building locally. If the account is bootstrapped from environment variables, skip the interactive step; see section 8.6.

### Native plugin install (development and macOS app)

1. Build the SPA (`npm ci && npm run build`).
2. Copy `plugin/` to `~/.local/share/nicotine/plugins/nicotine_webui/`.
3. While Nicotine+ is closed, add `nicotine_webui` to `[plugins] enabled` in the config.
4. Start Nicotine+, read the token and URL from the plugin log or Preferences → Plugins.
5. Open `http://127.0.0.1:8181` and log in.

The install script detects macOS, Linux, and Windows paths and refuses to edit the config while Nicotine+ is running.

### Development

- `dev/scripts/run-headless-dev.sh` starts Nicotine+ headless with `--user-data` and `XDG_CONFIG_HOME` pointing at a temporary directory, so tests do not touch the real profile. (`--user-data` only changes the data folder, not the config folder.)
- `dev/scripts/docker-dev.sh` builds the image with a local tag and runs Compose with the current plugin mounted for fast iteration.
- Vite dev server proxies `/api` and `/events` to the plugin port.
- `dev/mock-bridge` provides deterministic fixtures and scripted events, enabling UI work without a Soulseek account.
- The plugin exposes `/api/v1/diagnostics` with client count, event counts, dropped events, and thread state.

---

## 10. Milestones

### M0 — Spike (3–4 days)

- Plugin skeleton with settings and lifecycle.
- Token auth, Host/Origin checks, HTTP server, static placeholder.
- SSE with heartbeat and replay.
- `/status`, `/meta`, `/health`.
- Verify `http.server` imports and socket binding inside the frozen macOS app.
- Verify `invoke_main_thread` round-trips.
- Build the first Docker image and run it with Compose using a mounted config.

Exit criteria:

- App loads the plugin and serves `/status`.
- The container starts, becomes healthy, and serves the same endpoints.
- A browser holds an SSE connection for 10 minutes.
- Plugin unload/reload releases the port.
- No visible UI stalls.

### M1 — Read model (4–5 days)

- State mirror for session, rooms, chats, searches, transfers.
- Event ingestion with batching and revisions.
- Snapshot endpoints for MVP resources.
- Bounded queues and `resync`.
- Debug page for inspecting state.
- Entrypoint, config bootstrap, and plugin sync in the image.

Exit criteria:

- 30-minute soak with active transfers, chat, and room joins.
- Memory remains bounded.
- No main-thread exceptions.
- Container restart preserves config, data, and downloads.

### M2 — MVP UI and image (8–11 days)

- App shell, login, navigation, tabs, connection banner.
- Search and results with downloads.
- Downloads and uploads with actions and limits.
- Rooms and private chat with unread.
- Notifications and logs.
- Reconnect/resync behavior and error states.
- Compose deployment with volumes, healthcheck, non-root user, and graceful shutdown.
- README with Docker and native install paths.

Exit criteria:

- Search -> download -> progress -> completion from the browser.
- Two-way chat verified with a second account.
- Pause/resume/retry/cancel/clear work and reconcile correctly.
- 10k search results remain responsive.
- Restarting Nicotine+ shows offline state and recovers automatically.
- `docker compose up -d` on a clean host reaches healthy without manual steps beyond first-run credentials.
- Uploads work with the peer port forwarded.
- Playwright happy paths pass against the container.
- Fresh install completes in under 5 minutes.

MVP estimate: 3–4 weeks.

### M3 — Communication extras (7–10 days)

- Browse tree, user profiles, buddies, interests.
- User actions: ignore, ban, add buddy.
- History backfill from Nicotine+ logs.

### M4 — Completeness (5–7 days)

- Shares management with scan progress.
- Plugin management and curated settings.
- Statistics, command palette, responsive layout.
- Themes and density options.

### M5 — Hardening and release (5–7 days)

- Full e2e suite, contract tests, packaging, docs, security review.
- Performance tuning for large rooms and result sets.
- Multi-arch image publishing (amd64/arm64), SBOM, vulnerability scan.
- Upgrade test from the previous image tag with existing volumes.
- Verify non-root permissions and read-only root filesystem.

Full v1 estimate: 6–8 weeks.

---

## 11. Testing strategy

- **Bridge unit tests** with a fake adapter: routing, auth/CSRF, Host/Origin checks, SSE replay, serializers, store reducers, transfer ID stability.
- **Contract-first API**: author `openapi.yaml`, generate `web/src/api/types.gen.ts`, fail CI on drift. Serve the spec at `/api/v1/openapi.json`.
- **Integration**: headless Nicotine+ with an isolated `--user-data` directory; pytest drives the HTTP API. Use a dedicated test account.
- **Frontend**: Vitest for hooks and stores; mock bridge for component and flow tests; Playwright for search, download, chat, and reconnect.
- **Container tests**: build the image, start Compose with a fixture config, assert health, verify non-root UID, confirm `/data` and `/config` persistence across restarts, check graceful shutdown saves state, and validate first-run both interactively and via env bootstrap.
- **Manual matrix**: macOS GUI app, Linux headless, container on amd64 and arm64, plugin reload, port conflict, network loss, 100 MB+ transfers, multiple tabs, 30-minute soak.

---

## 12. Security

- Native installs bind `127.0.0.1`. The container binds `0.0.0.0` internally but must publish only to host loopback: `127.0.0.1:8181:8181`.
- Docker-published ports can bypass host firewall rules; the loopback port mapping is the primary control, not the firewall.
- Validate the `Host` header to prevent DNS rebinding, using an explicit allowlist; compare the hostname and ignore the port.
- Token generated with `secrets`; constant-time comparison.
- HttpOnly, SameSite=Strict session cookie; CSRF header on mutations.
- Rate-limit login and mutations; lock out repeated failures.
- Never return Soulseek credentials or other secrets; redact settings.
- Do not expose user IP addresses in the MVP.
- No file-reading endpoints at all.
- Sanitize all names and paths in logs and errors.
- The plugin runs in-process: wrap the server in a catch-all boundary so a bug cannot take down Nicotine+.
- The container runs as non-root with `cap_drop: ALL`, `no-new-privileges`, and a read-only root filesystem.
- Mount shared media read-only; never mount the Docker socket or host root.
- Keep secrets out of the image; use `.env` (gitignored) or Docker secrets. Do not bake `WEBUI_TOKEN` or Soulseek credentials into a layer.
- Pin image digests and scan published images before release.

---

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| In-process server affects Nicotine+ stability | Daemon threads, exception boundary, no blocking calls on the main thread, watchdog, diagnostics |
| Internal events are not a stable public API | `adapter.py` with version checks and feature flags; pin and test 3.3.x; degrade gracefully |
| Mirror drift | Seed on connect/start, reconcile on reconnect, `resync` and snapshot refetch |
| Memory growth from results and messages | Hard caps, truncation flags, batching, virtualization |
| SSE backpressure | Bounded per-client queues, batching, `resync` on overflow |
| Frozen bundle missing a stdlib module | Verified for the server stack; still add a startup import check and clear error |
| Plugin reload leaves a port bound | `disable()` closes listener and clients; integration test |
| Container cannot receive peer connections behind bridge networking | Disable UPnP, publish `2234/tcp` and `2234/udp`, document router forwarding; offer `network_mode: host` as a Linux fallback |
| Bind-mount permission errors on Linux | Run as `PUID:PGID`, document `chown` for `config`, `data`, and `downloads`, and fail fast with a clear message |
| First headless run blocks waiting for credentials | Interactive `docker compose run --rm -it`, env bootstrap, or an existing mounted config |
| Image Nicotine+ version drifts from the verified local version | Pin `NICOTINE_VERSION`, default to 3.3.6, and run a CI matrix against the latest 3.3.x |
| Read-only root filesystem breaks an unexpected write | Validate in M2; add narrow `tmpfs` or volumes instead of disabling hardening |
| Secrets leak through Compose or image layers | `.env` is gitignored, no secrets in build args or image, interactive setup recommended |
| Users expect remote file access | Explicit non-goal; document that files stay on the server |
| GPLv3 obligations | Nicotine+ is GPLv3; the plugin imports `pynicotine`, so license the plugin as GPLv3. Confirm frontend licensing separately |

---

## 14. Future work

- SQLite persistence for message and search history.
- Backfill chat history from Nicotine+ log files.
- Now Playing integration.
- PWA install and mobile layout.
- Optional LAN mode with TLS and a hardened auth flow, only if requirements change.
- Command palette with fuzzy actions.
- Saved searches and filters.

---

## 15. Assumptions

- One Nicotine+ instance per machine or container.
- One web user per instance.
- The browser runs on the same machine as Nicotine+, or reaches it through an SSH tunnel.
- Docker Engine with Compose v2 is available. Docker Desktop or Colima works on macOS; a Linux host is the reference deployment.
- The Docker host can forward the Soulseek peer port when uploads are required.
- Nicotine+ is version 3.3.x during initial development.
- Node 22 LTS is installed for development only.
- The web UI is an unofficial companion and does not use Nicotine+ branding in a way that implies endorsement.
