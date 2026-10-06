# Troubleshooting

## The radio sends nothing

Open `http://127.0.0.1:8765/api/v1/status`: `samples` stays 0 and the overlay says *RADIO DATA PAUSED*. Check, in this order:

1. **Is another program reading the same serial port?** A second Sticklink, a serial terminal, a flashing tool: two readers split the
   data and each sees (almost) nothing, and Sticklink may log "multiple access on port". Close the others. This is the
   most common cause when "it worked a minute ago".
2. **USB-VCP must be `LUA`** (SYS, PAGE to Hardware, Serial Port). `CLI` (the default) stays silent.
3. **The Special Function must be on the model that is selected**: `ON`, `Lua Script`, `DDSTK`. Check the model name on the
   radio's main screen.
4. **Restart the radio** after changing these, then reconnect USB and choose *USB Serial (VCP)*. The script only started
   after a power cycle in testing.
5. **Is the right mode active?** *USB Storage* and *Joystick* modes give no serial data. The port name changes between modes.
6. **A script error** shows on the radio as "Script error"; it appears when the model loads (switch to another model and back
   to see it). The script is guarded so that a failure in the optional channel report does not stop the sticks, and
   it sends a short note instead: `sticklink check-log` prints these as "Radio note".
7. **The script file.** `DDSTK.lua` must be in `/SCRIPTS/FUNCTIONS/` on the SD card; copy a fresh one with `sticklink radio-script`.

## "Could not open port" / permission denied

- Linux: add your user to `uucp` (Arch) or `dialout` (Debian/Ubuntu) and log in again.
- Another program has it open (see above).
- The port name changed after replugging or changing USB mode: run `sticklink list-ports` again.

## Sticks or switches are wrong

Use `/setup`: press **Learn** for the control and move it. A stick that moves the wrong way: tick *reverse*. Gimbals on the
wrong sides: change the *stick layout*. ARM or Crash Flip not reacting: assign the switch with Learn; the classic
`/overlay` lamps still show the radio's default channels 5 and 8.

## The overlay shows BRIDGE OFFLINE

Sticklink is not running, or runs on another port (`--http-port`). The page reconnects by itself.

## Trails look steppy

Use a 60 fps custom frame rate on the OBS Browser Source (the default is 30). The radio itself reports at about 20 Hz; the
overlay smooths between readings.

## No Browser source in OBS, or OBS crashes

See [OBS setup](obs-setup.md#no-browser-source-in-the-list).

## Windows or macOS refuse to run the download

See [getting started](getting-started.md#first-start-on-macos-and-windows-unsigned-builds).

## Missing records / low rate in `check-log`

The Pocket's script runs every 50 ms, so about 20 samples a second is normal. *Missing records* mean serial data was lost
(bad cable, or competing readers). *Stalls* (a large 95th-percentile gap) point at the radio being busy.

## Telemetry shows 0 or `-`

The receiver must be powered and linked; sensors only appear after the radio has discovered them. A battery voltage that
never changes usually means the flight controller is not sending battery telemetry.

## Still stuck

Run with a recording (`--log session.jsonl`), then `sticklink check-log session.jsonl`, and look at `/api/v1/status` (it
includes the radio's notes). Include both when asking for help.
