# Nicotine Web GUI

A browser remote control for an **existing Nicotine+ instance**, using the `nicotine_webui` plugin installed on that instance. The UI and Nicotine+ may run on different servers.

```text
Web GUI server ── serves the React app ──► Browser
                                           │ HTTPS REST + live events
                                           ▼
                              Nicotine+ host's HTTPS reverse proxy
                                           │ local HTTP
                                           ▼
                              nicotine_webui plugin → Nicotine+
```

The browser connects directly to the plugin URL you enter. The UI container does not run Nicotine+, proxy its API, access its plugin folder, mount its files, or need Soulseek credentials.

## 1. Install the plugin on the existing Nicotine+ host

Supports Nicotine+ 3.3.6–3.3.x. Run this step **on the Nicotine+ machine**, as the user who runs Nicotine+:

1. Close Nicotine+ before changing its plugin files/configuration.
2. Copy this repository to that machine and run:

   ```sh
   python3 dev/scripts/install_plugin.py
   ```

   This installs the bridge only; Node and a frontend build are not required. Existing account settings are preserved and the config is backed up as `config.pre-webgui`. `--data-dir` and `--config` override detected paths. Alternatively, copy the contents of `plugin/` into the existing client's `plugins/nicotine_webui/` folder and enable it in Nicotine+.
3. Start Nicotine+. Open Preferences → Plugins → Nicotine Web GUI and configure:

   | Setting | Example | Purpose |
   | --- | --- | --- |
   | `host` | `127.0.0.1` | Bind locally when the HTTPS proxy is on this machine |
   | `port` | `8181` | Plugin's local HTTP port |
   | `trusted_hosts` | `localhost,127.0.0.1,nicotine.example.com` | Allowed incoming Host names |
   | `allowed_origins` | `https://music.example.com` | Exact origin of the browser Web GUI |
   | `token` | generated automatically | Access token entered in the browser |

   Restart/reload the plugin after changing connection settings. Multiple allowed origins are comma-separated. Origins include the scheme and nonstandard port, with **no path or trailing slash**. Wildcards are not accepted. For a locally opened UI, the origin might be `http://127.0.0.1:8181` instead.

Headless users can supply `NICOTINE_WEBUI_HOST`, `NICOTINE_WEBUI_PORT`, `NICOTINE_WEBUI_TOKEN`, `NICOTINE_WEBUI_TRUSTED_HOSTS`, and `NICOTINE_WEBUI_ALLOWED_ORIGINS` in the existing Nicotine+ process environment. These override persisted plugin settings. These are settings for the **Nicotine+ process**, not the Web GUI container.

## 2. Give the plugin an HTTPS endpoint

The browser must be able to reach the plugin over HTTPS with a valid certificate. Terminate TLS at an existing reverse proxy on the Nicotine+ host and forward to the local plugin. For example, inside an Nginx HTTPS server for `nicotine.example.com`:

```nginx
# The containing server block supplies your TLS certificate and key.
location / {
    proxy_pass http://127.0.0.1:8181;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 75s;
}
```

Preserve `Origin`, `Authorization`, `X-CSRF-Token`, and `Last-Event-ID` request headers. Nginx normally forwards them; do not replace the browser's Origin. Let the plugin handle CORS rather than adding duplicate CORS headers in the proxy. SSE needs buffering and caching disabled and a timeout longer than the 20-second heartbeat.

For a path prefix, use a trailing slash to strip it when proxying:

```nginx
location /nicotine/ {
    proxy_pass http://127.0.0.1:8181/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 75s;
}
```

Then enter `https://nicotine.example.com/nicotine` in the connection screen. Use the final endpoint directly; API redirects are rejected to avoid forwarding credentials to an unexpected destination. TLS and CORS failures appear as connection errors in the UI; inspect the browser's Network panel and the proxy logs if needed.

## 3. Run the Web GUI container on its own server

```sh
# Optional; all values already have defaults in Compose.
cp .env.example .env

docker compose up -d --build webui
```

Open **http://127.0.0.1:8181**, or expose it through your Web GUI server's HTTPS reverse proxy, such as **https://music.example.com**. For LAN publishing without a local proxy, change `WEBUI_BIND_ADDRESS` in `.env`; the default `127.0.0.1` keeps the host port local.

If the UI and plugin run on the same host, choose a different host port for the UI, such as `WEBUI_PORT=8180`, so it does not conflict with the plugin's port 8181.

Enter:

- **Plugin URL:** `https://nicotine.example.com` (or the proxy prefix above).
- **Access token:** the token from the existing Nicotine+ plugin preferences.

The plugin's `allowed_origins` must match the origin of the page you actually opened. A browser on another computer cannot use a loopback plugin URL to reach the Nicotine+ server.

The UI image runs as UID/GID `10001:10001`, uses a read-only filesystem, and needs no persistent volumes or `.env` secrets. Its `/health` endpoint checks the UI server only, independently of Nicotine+. All downloads, shares, logs, and Soulseek peer port configuration remain on the existing Nicotine+ host.

### Migration from the earlier bundled image

The previous image tried to start its own Nicotine+ instance and install a plugin into `/data`. That architecture is retired. On the Web GUI server, stop the old Compose project's container and recreate it using the new configuration:

```sh
docker compose down --remove-orphans
docker compose up -d --build webui
```

This stops containers belonging to this Compose project. Leave your separately managed Nicotine+ instance running, except when installing/upgrading its plugin. Do not use `down -v`; old data/config/download/share directories are not deleted or migrated. Old `WEBUI_TOKEN`, `PUID`, `PGID`, `NICOTINE_USERNAME`, and `NICOTINE_PASSWORD` entries in the UI's `.env` are no longer used. The only UI settings are `WEBUI_BIND_ADDRESS` and `WEBUI_PORT`.

## Authentication and live updates

Remote login exchanges the long-lived plugin access token for a temporary bearer session and CSRF token. The access token is discarded after login, never embedded in the UI image, and never saved in browser storage. The selected endpoint is saved in local storage. The temporary session is saved only in tab-scoped session storage so reloads work. Sessions expire after 12 hours or plugin restart; reconnect with the access token then.

API requests omit cookies and use `Authorization: Bearer …`; mutations also require `X-CSRF-Token`. Cross-origin preflight is supported only for configured origins, methods, and headers. Native cookie authentication remains available for existing same-origin API clients. Install with `--with-ui` after building the SPA to retain optional native UI hosting; same-origin HTTP is allowed only for that local compatibility case.

When optionally hosting the native UI behind HTTPS, include that page's origin in `allowed_origins` too.

Live events use authenticated streaming fetch. The client handles split UTF-8/SSE frames, heartbeat comments, replay cursors, resync, and network reconnect. Logging out or changing the connection aborts old requests and clears instance-specific caches and workspace tabs. If a mutation has already started, the client polls its command ID rather than repeating it.

Ordinary API requests time out after 15 seconds. A stream with no data or heartbeat for 45 seconds is cancelled and reconnected; active streams have no overall time limit.

The authenticated API contract is available at `/api/v1/openapi.json` on the plugin. Run `python3 dev/scripts/contracts.py` to regenerate [openapi.yaml](openapi.yaml) and frontend domain/route types; CI checks for drift.

## Features

Search and virtualized results, file/folder downloads, download/upload controls and limits, rooms/private chat, unread state and bounded log backfill, notifications/logs, browsing/profiles, buddies, interests/recommendations, wishlist, shares, curated settings, plugin management, and statistics. Files stay on the Nicotine+ host; the browser does not stream or upload local media.

Shortcuts: `/` focuses search, Ctrl/Cmd+K opens navigation, Alt+1–9 switches sections, and Ctrl/Cmd+Enter sends messages. Theme, density, and layout preferences persist locally.

## Development and tests

Requires Python 3.9+ and Node 22.12+ LTS:

```sh
cd web
npm ci
npm run build
npm test
npx playwright install chromium
npm run test:e2e
cd ..
python3 -m unittest discover -s tests/bridge -v
python3 -m unittest discover -s tests/container -v
python3 dev/scripts/contracts.py --check
```

Browser tests launch a UI on `http://127.0.0.1:8181` and a separate demo plugin on `https://localhost:8443`. They use a temporary self-signed certificate and disable certificate verification **only in Playwright**. Production requests use normal browser certificate validation. Stop other servers on these ports before running tests. The deterministic demo does not touch the normal user profile or connect to Soulseek.

For manual demo use after building, run `python3 dev/remote_fixture.py`, trust its temporary test certificate in your development browser, and connect to `https://localhost:8443` using token `demo`. For frontend edits, `cd web && npm run dev` serves Vite; add its exact origin to the real plugin's allowlist and enter the plugin HTTPS URL. The frontend dev server does not proxy the API.

Real integration checks use isolated offline profiles:

```sh
# With nicotine-plus installed/importable in your development environment:
python3 tests/bridge/integration_nicotine.py
# Installed frozen macOS app, if available:
python3 tests/bridge/frozen_smoke.py
# Built UI image:
python3 tests/container/smoke.py nicotine-webgui:local
```

`docker/bootstrap.py` and the isolated headless launcher remain development/test tooling; the production UI image does not contain them. Docker runtime, actual public reverse-proxy deployments, and live-account workflows must still pass release validation; see [the execution checklist](plan/execution.md).

## License

GPL-3.0-or-later; see [LICENSE](LICENSE). This is an unofficial companion with no implied Nicotine+ endorsement.
