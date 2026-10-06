# Validation log

What has been tested, on what, and what has not. Dates are 2026-10-06 unless noted.

## Hardware test bench

| | |
|---|---|
| Radio | RadioMaster Pocket, EdgeTX 2.10.0, internal ExpressLRS module |
| Computer | Linux (CachyOS, Wayland), Python 3.14, Chrome, OBS Studio 32.2 with the browser component |
| Radio model | Special Function `ON -> Lua Script -> DDSTK`; USB-VCP set to `LUA` |

## Verified on the real radio

- **Stream**: sticks, telemetry and (after a script update) all 16 channels arrive. Typical `check-log` result for a 40 s
  session: 812 control records, **0 lost**, **20.4 Hz**, radio-clock gaps exactly 50 ms (EdgeTX calls function scripts every 50 ms).
- **ExpressLRS keeps working** while USB-VCP is on `LUA`: the radio stays linked to the powered quad (RQly 96-100 %), confirmed by the pilot.
- **Switches**: the pilot's ARM switch (radio channel 8) and Crash Flip (channel 9) were found and assigned with the Learn buttons;
  sticks reported full range; the layout selection fixed a "pitch on the wrong gimbal" report (the layout had been set to Mode 1; the radio is Mode 2).
- **OBS**: the Browser Source shows `/fx` with the radio live.

## Findings that shaped the code

- A port with **two readers** looks like a silent radio. One early "silent radio" result was caused by a second program holding the port.
- The first version of the all-channels report sent one ~100-byte line and could silence the **whole** script on the radio.
  It now sends 8 channels per line (no longer than the other lines), is wrapped in `pcall`, and reports failures as `D` notes
  so the sticks keep streaming.
- The script only started after a **radio restart** following the settings change.
- The Special Function is **per model**; it must be on the model that is selected.
- Raw, held 20 Hz readings drawn at 60 fps look like straight segments and produce bright "beads" and speed spikes at each
  reading. Measured on a recorded 20 Hz session (dot frozen while moving / jerkiness): raw 67 % / 29.6; a delay-based
  interpolation 15 % / 4.2 (rejected: adds lag); redrawing history after each reading, no delay, **11 % / 9.4**.
- OBS 32 on Wayland with an AMD GPU crashed when browser sources loaded with hardware acceleration on (see [OBS setup](obs-setup.md)).

## Telemetry HUD and the extended radio script (not yet run on the radio)

The HUD, the broader sensor list and the GPS record were developed against **simulated data** (the demo source) and a **mock EdgeTX**. On the real radio
only `RQly` has been seen live so far; battery reads were a stuck 3.7 V, and no GPS or attitude sensor has been received (the test quad has neither).
To close this gap: copy the current script, **Discover new sensors** on the radio, restart it, then check `check-log` and `/api/v1/telemetry`.
Open items: whether `getValue("GPS")` returns a table on this EdgeTX build (documented, unverified), whether attitude values are radians as
EdgeTX documents, and that the longer script keeps the 20 Hz control rate on the Pocket.

## Scene switching (`/modes`)

Checked against the real OBS (32.2.1, obs-websocket 5.7.4, no password) **read-only**: connection, version, current scene and the scene list, whose order matches
OBS's scene panel exactly. Scene *switching* was never run against your live OBS during development; it is covered by a fake obs-websocket server (handshake with and without a
password, wrong password, events, reconnects) and by end-to-end tests from radio channel records to the scene request. **The password handshake has not been tried against a real OBS
that requires one**, and the Learn button has only been tested as logic, not with a real switch.

## Automated tests

- **Python**: protocol and framing, state (resets, gaps, aging), recording and replay, `check-log`, settings storage and
  validation, the radio-script command, and the REST API: every route is in the OpenAPI document, real responses match
  the documented schemas, Host-header and path-traversal protections, recording lifecycle.
- **TypeScript**: live feed (events, smooth history, stick modes), mapping and the learn detector, settings cleaning.
- **Browser**: the classic overlay in jsdom; `/fx`, `/setup`, `/docs` rendered in headless Chrome (including a real double-click,
  Learn, and settings saved to the server).
- **HUD in headless Chrome**: all pages, four style/layout combinations and the map: only visible tiles requested (no duplicates), the browser's Referer sent, no retry storm when tiles fail, offline fallback drawn.
- **Modes page in headless Chrome**: add ranges, drag and keyboard-move handles, handles stopping at each other, sorting by buttons and by dragging, "Show in OBS", the master switch, removing ranges.
- **Scene engine**: range boundaries, priority, held button returning to the previous scene, debounce, stale radio data, reconnect without a surprise switch, failed switches.
- **Radio script**: syntax checked with `luac`; run against mocked EdgeTX functions (normal, failing reads, failing channel lookup)
  with every emitted line accepted by the real parser.
- **Frozen binary** (Linux): all pages, assets, API and a recording exercised against the PyInstaller build.
- **CI** runs the Python tests on Linux, Windows and macOS and smoke-tests every binary it builds.

## Not verified

- A radio on **Windows or macOS** (the builds are tested by CI, not with hardware).
- Radios other than the RadioMaster Pocket; EdgeTX versions other than 2.10.0.
- Video latency alignment with a real capture card, and sessions longer than a few minutes.
- Mode 3 and 4 layouts with a real radio configured that way (the layout logic is unit-tested).
- The Synthwave and Hacker text labels in stick modes 3 and 4 (written for modes 1 and 2).

## Re-running the hardware check

1. Install the script (`sticklink radio-script`), set USB-VCP to `LUA`, add the Special Function, restart the radio.
2. `sticklink run --port <port> --input-label sticks --log check.jsonl`, move all sticks and switches for a minute.
3. `sticklink check-log check.jsonl`: expect about 20 Hz, no missing records, and the channels you moved listed under
   *Output channels that moved*.
