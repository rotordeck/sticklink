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
- Self-contained binaries for Linux, Windows and macOS, plus a Python wheel and source package.
