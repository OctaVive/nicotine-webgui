# Nicotine Web GUI

A local browser companion for Nicotine+ 3.3.6–3.3.x. Nicotine+ owns the Soulseek connection, transfers, and shares. A Python standard-library plugin serves a React application, REST API, and live SSE stream from the same process.

The application includes search, file and folder downloads, transfer actions and limits, rooms and private chat, notifications, logs, buddies, browsing, profiles, interests, wishlist, shares, plugin controls, curated settings, and statistics. This is an initial implementation; release validation is tracked in [the execution checklist](plan/execution.md).

## Try it without an account

Requires Python 3.9+ and Node 22 LTS (22.12+).

```sh
cd web
npm ci
npm run build
cd ..
python3 dev/mock_bridge.py
```

Open **http://127.0.0.1:8181**, token **`demo`**. The deterministic demo provides 10,000 search results, transfer actions, and chat replies. It does not connect to Soulseek or modify your Nicotine+ profile. Stop it with Ctrl+C. Demo actions beyond these workflows may return an explicit unsupported-action error.

## Docker installation

Requires Docker Engine and Compose v2. The image builds the web app and installs a pinned Nicotine+ wheel without GTK or other Python dependencies.

```sh
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
# Put the generated value in .env as WEBUI_TOKEN.
mkdir -p config data downloads shares
# Linux: make config, data, and downloads writable by PUID:PGID from .env.
# For the default IDs: sudo chown -R 1000:1000 config data downloads
docker compose build
docker compose run --rm -it nicotine
```

Follow Nicotine+’s username/password prompts, then exit with `/quit`. Start the service:

```sh
docker compose up -d
docker compose logs -f nicotine
```

Open **http://127.0.0.1:8181** and enter `WEBUI_TOKEN`. Alternatively, set both `NICOTINE_USERNAME` and `NICOTINE_PASSWORD` in `.env` before the first run and skip interactive setup. Environment bootstrap applies only when the config file does not exist; it never replaces an existing login. Credentials are stored in Nicotine+’s plaintext config, and environment bootstrap also exposes them to local container administrators.

The web port is published only to host loopback. TCP port 2234 is the peer listening port; forward it on your router for peer connectivity. Nicotine+’s peer listener uses TCP, so no UDP port is published. UPnP is disabled on first-run container profiles. When changing an existing profile’s peer port, change the Compose mapping to match.

| Host path | Container path | Purpose |
| --- | --- | --- |
| `./config` | `/config` | Nicotine+ config and persisted plugin settings |
| `./data` | `/data` | Transfer state, databases, logs, installed plugin |
| `./downloads` | `/data/nicotine/downloads` | Completed files |
| `./shares` | `/shares` | Read-only media to share |

Set `NICOTINE_SHARES=/shares` to seed a non-empty share on first run, or add it through the Shares page. Paths always refer to the server or container. The browser cannot upload media or stream local files.

The container runs without root, capabilities, or a writable root filesystem. Its entrypoint refreshes the dedicated plugin directory on startup. It preserves account settings and writes configuration with mode 0600. If startup reports a permission error, correct volume ownership rather than running the service as root.

Health means the HTTP bridge is running; being disconnected from Soulseek is healthy. `docker compose stop` allows up to 30 seconds for state to save. Back up `config` and `data` before upgrading. Published image consumers should pin a release digest; this repository does not assume a GHCR owner or claim an image has been published.

## Native plugin installation

Build the frontend, close Nicotine+, then run:

```sh
python3 dev/scripts/install_plugin.py
```

The installer detects the Nicotine+ data and config locations, backs up an existing config as `config.pre-webgui`, and enables `nicotine_webui`. `--data-dir` and `--config` override detected paths. It refuses to install when it detects a running Nicotine+ process. Start Nicotine+, open Preferences → Plugins → Nicotine Web GUI, and copy the generated token. Open **http://127.0.0.1:8181**.

The plugin supports `NICOTINE_WEBUI_HOST`, `NICOTINE_WEBUI_PORT`, `NICOTINE_WEBUI_TOKEN`, and `NICOTINE_WEBUI_TRUSTED_HOSTS`. Environment values override plugin preferences. Native defaults bind to `127.0.0.1`; the container binds internally to `0.0.0.0` with a loopback-only host mapping. Use `ssh -L 8181:127.0.0.1:8181 user@host` for access through a tunnel. LAN exposure is outside the supported deployment.

## Development and checks

```sh
python3 -m unittest discover -s tests/bridge -v
python3 -m unittest discover -s tests/container -v
python3 dev/scripts/contracts.py --check
cd web
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

The HTTP tests need permission to bind temporary loopback sockets. Browser tests start their own demo bridge on port 8181; stop other instances before running them.

For development against the real engine, install `nicotine-plus==3.3.6` with `pip install --no-deps` in a virtual environment, then run `python dev/scripts/run_headless_dev.py`. This creates a disposable config/data directory and uses token `development-only` unless `NICOTINE_WEBUI_TOKEN` is set. It does not reuse the normal profile. The Vite development server (`cd web && npm run dev`) proxies `/api` to the bridge and rewrites Host/Origin consistently for local development.

Real integration tests use disposable offline profiles:

```sh
python3 tests/bridge/integration_nicotine.py
# macOS frozen app, if installed:
python3 tests/bridge/frozen_smoke.py
# After building an image:
python3 tests/container/smoke.py nicotine-webgui:local
```

CI covers Python 3.9/3.12 and Nicotine+ 3.3.6/3.3.11, frontend checks, browser workflows, and a container smoke test. The release workflow validates a local image before publishing multi-architecture images with SBOM and provenance on version tags or manual dispatch. No image publication is performed by local development scripts.

## API and behavior

The authenticated contract is served at `/api/v1/openapi.json`; [openapi.yaml](openapi.yaml), frontend route types, and domain model types are generated with `python3 dev/scripts/contracts.py`. CI checks these artifacts for drift.

Login exchanges a token for an HttpOnly, SameSite=Strict cookie. Mutations require a matching Origin and `X-CSRF-Token` from `/api/v1/session`. Sessions last 12 hours and are cleared on plugin restart. Host validation rejects untrusted names; login attempts, mutations, sessions, connections, commands, and event queues are bounded. Diagnostics and settings never return the bridge token or account password.

Snapshots include `instance`, `revision`, and a composite `cursor`. Pass the cursor to `/api/v1/events?cursor=…`; reconnecting clients can also use `Last-Event-ID`. Events invalidate affected resources in batches. A `resync` requires fresh snapshots. A new process has a new instance ID. Pending commands that time out are cancelled; already-running commands return 202 with a command ID and can be polled through `/api/v1/commands/{id}`. Do not automatically repeat such mutations.

Messages and results are bounded in memory. Search results retain the newest 10,000 per search, up to 20 retained searches; conversations retain 500 messages across up to 100 conversations. Truncation is shown in the UI. Chat pages request bounded background backfill from the matching Nicotine+ log; lines with unrecognized timestamps are skipped, and entries received since bridge startup are excluded to avoid duplicates. History depends on Nicotine+ logging and is not a durable bridge database.

Transfers use stable IDs derived from user and virtual path. Browser download destinations use Nicotine+ defaults. Administrative operations are explicit APIs; the serving plugin cannot disable/reload itself or expose its own secret-bearing settings. Other plugin settings expose numeric, boolean, and enumerated fields, excluding secret-bearing metadata. Free-form strings are edited on the host. Changes may require reloading that plugin.

Shortcuts: `/` focuses search, Ctrl/Cmd+K opens navigation, Alt+1–9 switches sections, Ctrl/Cmd+Enter sends a message. Tables support sorting, column resizing, virtualization, arrow-key navigation, and Space to select a focused row. Theme, density, and resource tabs persist locally.

## License

GPL-3.0-or-later; see [LICENSE](LICENSE). This is an unofficial companion with no implied Nicotine+ endorsement. Nicotine+ is distributed under its own GPL terms.
