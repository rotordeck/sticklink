# Sticklink

**Live stick and telemetry overlays for OBS, straight from your radio.**
Sticklink reads your sticks, switches and link telemetry from an EdgeTX radio (tested on a RadioMaster Pocket) over USB,
serves them as an OBS Browser Source with the same look as [stickcam](https://github.com/rotordeck/stickcam)'s after-the-fact
overlays, and records every session so you can check and reuse the data later.

<p align="center">
  <img src="docs/img/fx-neon.png" width="32%" alt="Neon style">
  <img src="docs/img/fx-arcade.png" width="32%" alt="Arcade style">
  <img src="docs/img/fx-hacker.png" width="32%" alt="Hacker style">
</p>
<p align="center">
  <img src="docs/img/hud-corners-neon.png" width="49%" alt="Telemetry HUD, neon">
  <img src="docs/img/hud-corners-hacker.png" width="49%" alt="Telemetry HUD, hacker">
</p>

## What you get

- **Effects overlay** (`/fx`): eight styles (Clean, Minimal, Neon, Arcade, Synthwave, Inferno, Unicorn, Hacker) with glowing
  trails, sparks, shockwaves and live throttle timers. Trails are smooth curves with no added delay.
- **Telemetry HUD** (`/hud`): **Link**, **Battery**, **GPS** and **Status** blocks as badges, in the same eight styles. GPS shows a live
  map with your track, home marker and distance. Each block is also its own page (`/hud/link`, `/hud/battery`, `/hud/gps`), so you can
  put them in OBS as separate sources. It shows what your radio really receives (see [limits](#status-and-honest-limits)).
- **Receiver setup page** (`/setup`): a live 3D quad, stick bars and a 16-channel monitor, like Betaflight Configurator's
  receiver tab. Press **Learn** and move a stick or switch to assign roll, pitch, yaw, throttle, ARM and Crash Flip, so a
  swapped or reversed stick is a ten-second fix.
- **Double-click to configure**: style, effect strength, stick layout (modes 1-4), size and video delay, saved on the
  server so an OBS source updates by itself. The panel also shows a **permanent link** for the current look: use it as a source's URL to pin
  that source to its own configuration.
- **Recordings**: one JSONL file per session, a `check-log` quality report (rate, gaps, lost records, channel ranges) and
  `replay` to play a session back through the overlay.
- **REST API + Swagger UI** (`/docs`, works offline) and a WebSocket stream for your own tools.
- **No dependencies to install**: downloads are single self-contained programs for Linux, Windows and macOS (they carry
  their own Python). A pip-installable Python package is available too.

## Quick start

1. **Download** the build for your system from the [Releases](../../releases) page, and unpack it.
2. **Try it without a radio**:
   ```bash
   ./sticklink run --demo          # Windows: sticklink.exe run --demo
   ```
   Open <http://127.0.0.1:8765/fx>. You should see two gimbals moving by themselves.
3. **Connect your radio**: install the script and set USB-VCP to LUA ([radio setup](docs/radio-setup.md)), then
   ```bash
   ./sticklink list-ports
   ./sticklink run --port /dev/ttyACM0 --input-label sticks     # Windows: --port COM5
   ```
4. **Assign your sticks and switches** at <http://127.0.0.1:8765/setup> (press *Learn*, move the control).
5. **Add it to OBS** as a Browser Source with the URL `http://127.0.0.1:8765/fx`, size 576x450, 60 fps
   ([OBS setup](docs/obs-setup.md)). Double-click the page (in OBS: right-click, *Interact*) to change the look.

Prefer Python? `pip install sticklink-<version>-py3-none-any.whl` (from the release page), or from a checkout
`pip install .`; then run `sticklink ...`.

## Pages and commands

| Address / command | What it does |
|---|---|
| `/fx` | Effects overlay for OBS (double-click for settings) |
| `/hud`, `/hud/link`, `/hud/battery`, `/hud/gps` | Telemetry HUD (combined, or one block per page) |
| `/setup` | Receiver screen: 3D quad, channel monitor, learn-by-moving assignment |
| `/overlay` | The plain panel with two sticks, ARM/flip lamps and telemetry |
| `/docs` | Swagger UI for the REST API (spec at `/api/v1/openapi.json`) |
| `sticklink run --port P \| --demo` | Serve the overlays from a radio or from synthetic data |
| `sticklink replay FILE` | Serve a recorded session as if it were live |
| `sticklink check-log FILE` | Quality report for a recording |
| `sticklink radio-script [DIR]` | Copy the EdgeTX Lua script `DDSTK.lua` (e.g. onto the radio's SD card) |
| `sticklink list-ports` | List serial ports |

More in [docs/cli.md](docs/cli.md).

## Documentation

| | |
|---|---|
| [Getting started](docs/getting-started.md) | Install, run, first checks |
| [Radio setup](docs/radio-setup.md) | EdgeTX script, USB-VCP, per-OS port names |
| [OBS setup](docs/obs-setup.md) | Browser source, Linux/Wayland notes |
| [Overlay guide](docs/overlay-guide.md) | `/fx`, `/setup`, the classic overlay, settings and URL options |
| [CLI reference](docs/cli.md) | All commands and options |
| [REST API](docs/api.md) | Endpoints, examples, security model |
| [Protocol and log format](docs/protocol.md) | DDLOG v1, the JSONL recording format |
| [Architecture](docs/architecture.md) | Modules and data flow |
| [Troubleshooting](docs/troubleshooting.md) | Silent port, crashes, wrong sticks, OBS |
| [Development](docs/development.md) | Tests, rebuilding the overlay, releases |
| [Validation log](docs/validation.md) | What was tested on real hardware, and what was not |

## Status and honest limits

- Verified on real hardware: a **RadioMaster Pocket (EdgeTX 2.10)** with ExpressLRS, on **Linux**, with OBS 32. The radio
  reports sticks at about **20 Hz** (EdgeTX runs function scripts every 50 ms); the overlay smooths between readings.
- The Windows and macOS builds are produced and smoke-tested by CI (unit tests, integration tests and a run of the frozen
  program), but they have **not been tried with a radio** on those systems yet.
- The **HUD shows only telemetry your radio actually receives**. Betaflight does not send motor outputs, RPM, PID or gyro over
  the radio link (those live in the blackbox on the quad), so there is no live motor screen. So far only **link quality (`RQly`) has been seen live on a real
  radio**; the other link sensors, battery, GPS and attitude were tested with simulated data until the radio script is updated and the quad sends them.
- The GPS map downloads tiles from the internet (OpenStreetMap by default); see [overlay guide](docs/overlay-guide.md#telemetry-hud).
- The effects overlay shows what sticks and switches can drive: trails, sparks, snaps, punch-outs, full-throttle and hang-time
  timers, arm/disarm. Flips, rolls and crash detection in stickcam need gyro and accelerometer data that the radio does not have.
- Sticklink only **reads** from the radio. It never writes to it and never changes ExpressLRS or model settings.
- Unsigned downloads: macOS Gatekeeper and Windows SmartScreen will warn once ([getting started](docs/getting-started.md)).

## Licence

No licence has been chosen yet, so all rights are reserved. Third-party components are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
