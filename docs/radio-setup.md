# Radio setup (EdgeTX)

Sticklink needs an **EdgeTX** radio that can send data over USB as a serial port from a Lua script. It was developed and
tested on a **RadioMaster Pocket** (EdgeTX 2.10.0, internal ExpressLRS module). Other EdgeTX radios with a *USB-VCP* option
set to *LUA* should work; they have not been tried.

The script only **reads** values and writes lines to the USB serial port. It does not change mixers, ExpressLRS or any
flight setting. With the quad powered, the radio kept its link to the drone while in this mode.

## 1. Put the script on the radio

1. Put the radio in **USB Storage** mode and mount its SD card (unplug and replug the cable if the card does not appear).
2. Copy the script into the `SCRIPTS/FUNCTIONS` folder of the SD card:
   ```bash
   sticklink radio-script /path/to/SDCARD/SCRIPTS/FUNCTIONS
   ```
   (or copy `DDSTK.lua` from the download by hand). The file name `DDSTK` must stay six characters or fewer: an EdgeTX limit.
3. Eject the card cleanly before unplugging.

## 2. Radio settings

1. **USB-VCP to LUA.** Press **SYS**, then use **PAGE** until you reach the **Hardware** page. In the *Serial Port*
   section set **USB-VCP** to **LUA**. (The default `CLI` is what ExpressLRS flashing over USB uses; set it back to `CLI` before
   updating the module, then to `LUA` again.)
2. **Special Function.** Press **MDL**, open the model you use, go to **Special Functions** and add a row:
   switch **ON**, function **Lua Script**, script **DDSTK**. This is per model: the script only runs while that model is selected.
3. **Restart the radio.** In practice the script only started after a power cycle following these changes.
4. Plug the radio into the computer and choose **USB Serial (VCP)** when it asks.

## 3. Check that it works

```bash
sticklink list-ports
sticklink run --port <your port> --input-label sticks --log first-test.jsonl
```

Open `/setup` and move the sticks. Then stop the program and run `sticklink check-log first-test.jsonl`: expect about 20
control records per second, no missing records, and the sensors you use (`RQly`, `RxBt`) once the receiver is powered.

## Port names and permissions

| System | Port looks like | Notes |
|---|---|---|
| Linux | `/dev/ttyACM0` | Your user needs access: add yourself to the `uucp` group (Arch/CachyOS) or `dialout` (Debian/Ubuntu), then log in again |
| Windows | `COM5` | No driver needed on current Windows 10/11 |
| macOS | `/dev/cu.usbmodem...` | Use the `cu.` device |

## What the script sends

Everything goes out as short ASCII lines ([protocol](protocol.md)): your four sticks, the two default command channels
(CH5 and CH8), all 16 mixer outputs, telemetry sensors and the GPS position ([below](#telemetry-sensors-and-gps)), and short diagnostic notes if
something goes wrong. Sticks are sent about every 50 ms (EdgeTX calls function scripts that often).

To change which sensors are sent or which channels count as the default ARM/flip, edit the settings at the top of
`DDSTK.lua` (`TELEMETRY`, `CHANNELS`, `STICKS`) and copy it to the radio again. Normally you do not need to: sticks and
switches are assigned on the `/setup` page without touching the script.

If the radio's sensor names differ (see the radio's *Telemetry* page), change `TELEMETRY` in the script, and the sensors
shown by the overlay with the `sensors` URL option ([overlay guide](overlay-guide.md#classic-overlay)).

## Telemetry sensors and GPS

The script forwards these sensors when the radio knows them: link (`RQly RSNR 1RSS 2RSS TPWR RFMD ANT TRSS TQly TSNR`), battery (`RxBt Curr Capa Bat%`),
GPS (`Sats GSpd GAlt Alt VSpd Hdg`) and attitude (`Ptch Roll Yaw`), plus the GPS position itself. It sends two sensors per call in rotation, so each
one is refreshed about twice a second. Sensors the radio has not discovered are skipped.

1. **Discover the sensors**: with the receiver (and the quad) powered, open the radio's *Telemetry* page for the model and run **Discover new sensors**.
   Without this the radio never creates them. Link statistics appear with any ExpressLRS receiver; battery, GPS and attitude only appear if the flight
   controller sends them (Betaflight: enable the matching telemetry sensors and the CRSF telemetry feature).
2. Copy the current script (`sticklink radio-script`) and restart the radio.
3. Check: `sticklink check-log` on a short recording lists the sensors that arrived, and `/api/v1/telemetry` shows them live.

What cannot be forwarded: **flight mode** (a text sensor) and anything the flight controller does not put on the radio link: motor outputs, RPM,
PID and gyro values only exist in the blackbox on the quad. Attitude values are forwarded and recorded but not drawn yet.

If something goes wrong inside the script, it keeps streaming the sticks and reports the reason as a short note (visible in `/api/v1/status` and
`check-log`): for example `sensor Curr ...` when one sensor misbehaves (that sensor is then skipped) or `lookup ...` when a name cannot be resolved.

## It is silent. Now what?

See [troubleshooting](troubleshooting.md#the-radio-sends-nothing). The usual reasons: USB-VCP is still `CLI`; the
Special Function is on a different model than the one selected; the radio was not restarted; or **another program is
reading the same port**.
