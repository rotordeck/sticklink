# Changelog

## 0.1.0 (unreleased)

First packaged version.

- Live stick, switch and telemetry capture from an EdgeTX radio over USB serial (`DDSTK.lua`, DDLOG protocol v1).
- Overlay pages for OBS browser sources: classic panel (`/overlay`) and the effects overlay (`/fx`, stickcam renderer, 8 styles).
- Double-click settings panel; receiver-style setup page (`/setup`) with a 3D quad, channel monitor and learn-by-moving mapping.
- Smooth, lag-free trails from 20 Hz radio data.
- Session recordings (JSONL), `replay`, `check-log` quality reports.
- REST API with OpenAPI spec and offline Swagger UI (`/docs`).
- The effects overlay fills any Browser Source size and keeps the gimbals centered in it.
- Telemetry HUD (`/hud`, `/hud/link`, `/hud/battery`, `/hud/gps`): Link, Battery, GPS and Status blocks in the stickcam styles, three layouts, and a GPS map
  with live track, home marker and distance (OpenStreetMap tiles by default, switchable, with a track-only fallback).
- The radio script forwards a broad sensor list (round-robin, per-sensor failure isolation) and the GPS position; new `G` protocol record; sensor names may contain `%`.
- New API: `GET /api/v1/gps`, `GET`/`DELETE /api/v1/gps/track`; `hud` settings.
- Self-contained binaries for Linux, Windows and macOS, plus a Python wheel and source package.
