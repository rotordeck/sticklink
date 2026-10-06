# Command-line reference

`sticklink <command> [options]` (the downloaded binary, or `python -m sticklink`).

## `sticklink gui` (or no command)

A small window: radio picker (or Demo), **Start / Stop**, a status light (stopped, waiting for the radio, connected) and buttons that open the web pages. It serves on port 8765 and stops everything when closed. Needs tkinter (included in the downloads; on Linux with pip install `python3-tk`).

## `sticklink plugin ...`

`install SOURCE [--force]` (a folder, a `.zip` or a single `.js`), `remove NAME`, `list`, `path`. `--plugins-dir DIR` (before the action) uses another folder.
See [plugins](plugins.md). `run` and `replay` accept `--plugins-dir` too.

## `run` - serve the overlays

Exactly one of `--port` or `--demo`.

| Option | Default | Meaning |
|---|---|---|
| `--port NAME` | | Serial port of the radio (`COM5`, `/dev/ttyACM0`, `/dev/cu.usbmodem...`) |
| `--demo` | | Synthetic sticks, switches and telemetry; no radio needed |
| `--baud N` | 115200 | Serial baud rate (USB serial ignores it in practice) |
| `--http-port N` | 8765 | Port of the web server (it always binds to 127.0.0.1) |
| `--input-label sticks\|outputs\|unknown` | unknown | What the radio's control values represent; `sticks` for the bundled script |
| `--stale-ms N` | 500 | No control sample for this long means "paused" |
| `--scale N` | 1024 | Channel value that counts as full deflection |
| `--arm-threshold N`, `--crash-threshold N` | 0 | Value above which the default channels 5 / 8 count as on |
| `--log FILE` | | Start a recording to this file straight away (a path you choose) |
| `--recordings-dir DIR` | `~/.local/share/sticklink/recordings` | Folder for recordings started through the API |
| `--fx-config FILE` | `~/.config/sticklink/fx.json` | Overlay settings file |
| `--scenes-config FILE` | `~/.config/sticklink/scenes.json` | OBS connection (including its password) and the scene modes; readable only by you |

If the radio is unplugged, Sticklink keeps running and reconnects to the same port every two seconds.

## `replay FILE`

Plays a recording back through the overlays at its original speed. Takes the same options as `run` (except the source
ones), plus `--speed N` (default 1) and `--loop`.

## `check-log FILE`

Prints a quality report for a recording: duration, control rate, gaps on the radio's clock and the computer's clock, lost
records, resets, channel ranges, which output channels moved, telemetry rates, notes sent by the radio, and warnings
(low rate, stalls, lost records, sticks that never moved, no telemetry).

## `radio-script [DIR]`

Copies the EdgeTX Lua script `DDSTK.lua` into `DIR` (default: the current folder). See [radio setup](radio-setup.md).

## `list-ports`

Prints the serial ports your system knows, with their descriptions.

## Stopping

Press Ctrl+C. An active recording is closed properly. Background launches from some shells ignore Ctrl+C; use `kill` (SIGTERM).
