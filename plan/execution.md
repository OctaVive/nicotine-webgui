# Execution checklist

This file breaks down the design into implementation units and records validation separately from code completion. The original design remains in `nicotine-webgui.md`; its estimates and environmental claims are not release guarantees.

## 1. Compatibility spike

- [x] Inspect pinned 3.3.6 source and verify plugin lifecycle, events, search tokens, and action signatures.
- [x] Implement HTTP, session login, SSE, main-thread dispatch, and static serving.
- [x] Verify real plugin load/unload/reload and port rebind in isolated profiles.
- [x] Check baseline compatibility with 3.3.11.
- [x] Serve HTTP inside the installed macOS app’s frozen runtime, using an offline temporary profile.
- [x] Hold an authenticated SSE connection in the frozen macOS runtime for 600 seconds (30 heartbeats, no disconnect).
- [ ] Observe the desktop GUI for stalls during sustained activity.
- [ ] Build/run the Docker image locally; Docker is unavailable in this environment.

## 2. Bridge contracts and read model

- [x] Bound sessions, HTTP/SSE clients, replay, pending commands, searches, logs, and conversations.
- [x] Add process-instance/revision cursors, replay expiry, overflow resync, and snapshot refresh reconciliation.
- [x] Cancel commands before execution on timeout; expose status for commands already running.
- [x] Normalize core state and ingest chat/search/profile/browse events.
- [x] Generate OpenAPI, frontend route types, and drift checks.
- [x] Test security, replay, cancellation, unread acknowledgement, and selection actions.
- [x] Generate frontend domain models from the OpenAPI schemas.
- [ ] Run a 30-minute soak with real active transfers and chat.

## 3. Deployment baseline

- [x] Add multi-stage image, loopback-only Compose, named-volume smoke checks, and non-root/read-only configuration.
- [x] Add idempotent bootstrap, plugin refresh, config protection, and native installer.
- [x] Test bootstrap preservation of credentials and removal of stale plugin modules.
- [x] Add isolated development launchers and deterministic demo bridge.
- [ ] Validate image health, first-run prompts, persistence, permissions, and graceful shutdown on Docker.

## 4. Browser workflows

- [x] Implement login, shell, tabs, connection banner, live queries, themes, density, and keyboard navigation.
- [x] Implement search, virtualized results, selected file/folder downloads, transfer controls, and limits.
- [x] Implement rooms/private chat, unread acknowledgement, notifications, logs, and bridge settings.
- [x] Pass browser tests for 10,000 results → download → pause, chat text escaping, and session reload/logout.
- [x] Test event-during-snapshot reconciliation.
- [ ] Verify real search → download → completion and two-account chat with dedicated test accounts.
- [x] Exercise browser stream interruption and automatic recovery.
- [ ] Exercise reconnect across an actual process restart and additional multi-tab workflows.

## 5. People and administration

- [x] Add browse results, profiles/picture transport, buddies, interests, recommendations, wishlist, and moderation APIs.
- [x] Add bounded asynchronous history backfill with startup-time duplicate exclusion.
- [x] Add shares/scanning, curated settings, plugin controls/settings APIs, and statistics.
- [x] Protect the serving plugin from lifecycle commands and redact secret-bearing settings.
- [x] Exercise real offline transfers, buddies, interests, wishlist, and settings through the HTTP API.
- [x] Add hierarchical browse interaction, profile pictures/plugin-setting editors, and command autocomplete in the UI.
- [ ] Validate online profile/browse/moderation/share scan behavior with the real engine.

## 6. Hardening and release

- [x] Add compatibility CI, browser CI, container smoke checks, and multi-architecture publication workflow with SBOM/provenance/scanning.
- [x] Resolve the initial frontend dependency advisories.
- [x] Document installs, credentials, limits, protocol behavior, and validation boundaries.
- [ ] Run release checks on amd64 and arm64 and test image upgrades with existing volumes.
- [ ] Review performance, accessibility, security, first-install timing, and supply-chain pins before release.
- [ ] Publish a versioned artifact only after release gates pass.

## Validation evidence — 2026-10-20

- Bridge regression suite: 17 tests passed; bootstrap/native installer suite: 4 tests passed.
- Node 22.23.3: production build, formatting check, and 3 frontend tests passed.
- Chromium: 5 browser workflows passed, including 10,000-result virtualization, downloads/pause, chat escaping, sessions, stream recovery, browsing, and buddies.
- Nicotine+ 3.3.6 and 3.3.11: isolated offline lifecycle/API tests passed; transfer actions, buddies, interests, wishlist, curated settings, and port rebind were exercised.
- Installed macOS app: frozen-runtime HTTP startup and graceful shutdown passed; a separate authenticated SSE soak completed 600 seconds.
- Contract drift, Python/shell syntax, and npm dependency audit passed (zero reported advisories).
- No normal user profile was installed into or modified. No account credentials were supplied. No image was published.
- Docker runtime, real peer transfers/chat, 30-minute active soak, and architecture/upgrade release gates remain unverified.
