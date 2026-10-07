# Changelog

## 0.1.3 (2026-10-07)

- The web pages (`/setup`, `/modes`, `/docs`, the overlay panels) now share the Rotordeck look of the window: olive-black and lime, logo in the header. Shared styles live in `web/brand.css`.
- Stopping no longer hangs while a browser or OBS source is connected: the window closes at once instead of waiting up to 10 seconds.
- `start.sh` in the source tree opens the window.

## 0.1.2 (2026-10-07)

- Race timer: tap the crash-flip switch while armed to start a timer, tap again for each lap, double-tap to stop. Big timer with the last laps under it (`/hud/race`, also a block on `/hud`; how many laps are shown is a setting). The timing runs in the bridge on the radio's clock, so it survives OBS reloading the source. `race` in `GET /api/v1/state`, `POST /api/v1/race/reset`, `--race-double-tap-ms`. See `docs/overlay-guide.md`.
- Race timer follows the arm and flip switches chosen on `/setup`, and `DDSTK.lua` now reports a switch on an AUX channel immediately (it used to miss quick taps on channels 9 to 16). Update the script on the radio: **Radio script...** in the window.
- The window (`sticklink gui`) has a new look that matches OBS (customtkinter, Yami colours), and `--http-port`. The default port is now 47613 (was 8765).
- Starting while another Sticklink already runs on the port now says so (and offers its web portal) instead of showing a raw error.
- Ctrl-C in the terminal closes the window.
- The window uses the Rotordeck look (olive-black and lime, logo in the header) and the program has the Rotordeck icon. **Radio script...** in the window installs `DDSTK.lua` on the radio's SD card, and the radio is picked automatically when plugged in.
- Licence: AGPL-3.0-or-later.

- Themes: add your own looks to the stick overlay and the HUD with a data-only `.json` (or folder/zip with fonts). `sticklink theme install|list|remove|path`, an "Add theme" button in the window, `GET /api/v1/themes`. Gold Rush and Blueprint are included. See `docs/themes.md`.
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
