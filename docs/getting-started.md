# Getting started

## 1. Get Sticklink

**Binaries (recommended).** Download the archive for your system from the repository's **Releases** page:

| System | File |
|---|---|
| Linux (x86-64) | `sticklink-<version>-linux-x86_64.tar.gz` |
| Windows (x86-64) | `sticklink-<version>-windows-x86_64.zip` |
| macOS, Apple Silicon | `sticklink-<version>-macos-arm64.tar.gz` |
| macOS, Intel | `sticklink-<version>-macos-x86_64.tar.gz` |

Each archive holds one program (`sticklink`, or `sticklink.exe` on Windows) plus `DDSTK.lua` (the radio script),
the README and the third-party notices. The program carries its own Python; nothing else needs installing.
`SHA256SUMS.txt` on the release page lets you check the downloads.

**Python package.** Every release also has `sticklink-<version>-py3-none-any.whl` and a source package (`.tar.gz`). With
Python 3.10 or newer: `uvx sticklink run --demo` runs it without installing (needs [uv](https://docs.astral.sh/uv/)); `pip install sticklink` installs it. Or `pip install sticklink-<version>-py3-none-any.whl`. From a checkout: `pip install .`.

### First start on macOS and Windows (unsigned builds)

The downloads are not code-signed, so your system will warn once:

- **macOS**: if the program is blocked ("cannot be opened because the developer cannot be verified"), clear the
  quarantine flag: `xattr -d com.apple.quarantine ./sticklink` (or right-click, *Open*, in Finder). Also `chmod +x sticklink` if needed.
- **Windows**: SmartScreen shows "Windows protected your PC": choose *More info*, then *Run anyway*.
- **Linux**: `chmod +x sticklink` if the executable bit was lost.

## 2. Try it without a radio

```bash
./sticklink run --demo
```

Open <http://127.0.0.1:47613/fx>: two gimbals move by themselves, with an ARM timer and telemetry. Stop with Ctrl+C.
The server only listens on your own computer (`127.0.0.1`).

## 3. Connect your radio

Follow [radio setup](radio-setup.md) once (script on the SD card, USB-VCP set to LUA, a Special Function). Then:

```bash
./sticklink list-ports
./sticklink run --port /dev/ttyACM0 --input-label sticks
```

Use the port name from `list-ports` (`COM5` on Windows, `/dev/cu.usbmodem...` on macOS, `/dev/ttyACM0` on Linux).
Leave the program running while you use the overlay, and close any other program that has the same serial port open.

## 4. Set up sticks and switches

Open <http://127.0.0.1:47613/setup>. Move your sticks: the quad and the bars must follow in the right direction. If
something is swapped or reversed, press **Learn** next to that function and move the control. Assign your ARM and
Crash Flip switches the same way (switch OFF first, press Learn, flip it ON). Details: [overlay guide](overlay-guide.md).

## 5. Show it in OBS

[OBS setup](obs-setup.md): Browser Source, URL `http://127.0.0.1:47613/fx`, 576 x 450, 60 fps.

## Where files go

| What | Where |
|---|---|
| Overlay settings and mapping | `~/.config/sticklink/fx.json` (Windows: `C:\Users\<you>\.config\sticklink\fx.json`; `--fx-config` to change) |
| Recordings made through the API | `~/.local/share/sticklink/recordings/` (`--recordings-dir` to change) |
| Recording started with `--log FILE` | exactly `FILE` |

`XDG_CONFIG_HOME` and `XDG_DATA_HOME` are respected if set.
