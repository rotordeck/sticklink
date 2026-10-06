# Changelog

## Unreleased

- Visualiser plugins: a gallery at `/viz`, one page per plugin (`/viz/<id>`) for OBS, `sticklink plugin install|list|remove|path`, an "Add visualiser plugin" button in the window, `GET /api/v1/plugins`. Plugins are small canvas scripts that receive sticks, switches and telemetry; they run in a sandboxed frame with no network access. Starfield, Neon tunnel and Phosphor scope are included. See `docs/plugins.md`.
- The window no longer lists the built-in serial ports (`ttyS0`...) as radios.

## 0.1.1 (2026-10-06)

- A small window (`sticklink gui`, also what you get when you start the program without arguments): pick the radio or Demo, Start / Stop, status light, buttons for the web pages.
- Released on PyPI: `uvx sticklink run --demo`, `pip install sticklink`.
- README links and images are absolute, so the PyPI page renders.

## 0.1.0 (2026-10-06)

First packaged version.

- Live stick, switch and telemetry capture from an EdgeTX radio over USB serial (`DDSTK.lua`, DDLOG protocol v1).
- Overlay pages for OBS browser sources: classic panel (`/overlay`) and the effects overlay (`/fx`, stickcam renderer, 8 styles).
- Double-click settings panel; receiver-style setup page (`/setup`) with a 3D quad, channel monitor and learn-by-moving mapping.
- Smooth, lag-free trails from 20 Hz radio data.
- Session recordings (JSONL), `replay`, `check-log` quality reports.
- REST API with OpenAPI spec and offline Swagger UI (`/docs`).
- The effects overlay fills any Browser Source size and keeps the gimbals centered in it.
- Permanent links: the settings panel shows a copyable `?cfg=` link for the current configuration (the address bar never changes). A link page uses exactly
  that configuration and does not write to the server; plain URLs keep using the saved settings.
- Scene switching: `/modes` page (Betaflight Modes style) to switch OBS scenes from radio switches, with ranges per scene, priority sorting, learn-by-flipping,
  safe defaults (off until enabled, adopts the current positions, never acts on stale data); OBS WebSocket client; new API under `/api/v1/obs` and `/api/v1/scene-modes`.
- Every POST now requires `Content-Type: application/json`, even with an empty body (closes cross-site form triggers).
- Telemetry HUD (`/hud`, `/hud/link`, `/hud/battery`, `/hud/gps`): Link, Battery, GPS and Status blocks in the stickcam styles, three layouts, and a GPS map
  with live track, home marker and distance (OpenStreetMap tiles by default, switchable, with a track-only fallback).
- The radio script forwards a broad sensor list (round-robin, per-sensor failure isolation) and the GPS position; new `G` protocol record; sensor names may contain `%`.
- New API: `GET /api/v1/gps`, `GET`/`DELETE /api/v1/gps/track`; `hud` settings.
- Self-contained binaries for Linux, Windows and macOS, plus a Python wheel and source package.
