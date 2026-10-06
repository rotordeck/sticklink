# Protocol and log format

## DDLOG v1 (radio to computer)

`DDSTK.lua` writes ASCII lines, newline-terminated, over the USB serial port. Fields are comma separated. A line over 512
characters is discarded. `tick` is the radio's clock in **10 ms** units; `seq` is a 16-bit counter over all records.

| Record | Fields | Meaning |
|---|---|---|
| `H` | `H,1,<logger>,<tick>` | Hello at script start. `DDRAW` = physical sticks, `DDOUT` = mixer outputs |
| `S` | `S,tick,seq,roll,pitch,yaw,throttle,arm,crash` | Control sample (about every 50 ms). Integers, normally -1024..1024, up to +-2048 |
| `E` | `E,tick,seq,ARM\|CRASH,0\|1` | The default channel 5 / 8 changed state |
| `T` | `T,tick,seq,sensor,value,current,fresh` | A telemetry sensor; `current`/`fresh` are 0/1 (0,0 means "lost") |
| `C` | `C,tick,seq,first,v1,...,v8` | Mixer outputs `first`..`first+7`; `first` is 1 or 9, so all 16 channels take two lines |
| `D` | `D,tick,seq,text` | A diagnostic note from the script (up to 60 characters of `A-Za-z0-9 _.:-`) |

Examples:

```text
H,1,DDRAW,100
S,103,1,120,-47,-1024,83,-1018,1024
E,103,2,ARM,0
T,120,3,RQly,100,1,1
C,125,4,1,1,3,-867,7,-1024,-1024,-1024,-1024
D,5,5,channels resolved 16
```

How the computer treats it:

- Malformed, oversized or out-of-range lines are counted as invalid and skipped; partial lines are buffered.
- A clock going backwards, a new `H`, or a large backwards jump in `seq` counts as a radio restart (a new *session*).
- Gaps in `seq` are counted as lost records. A repeated `seq` is ignored.
- No control sample for 500 ms (`--stale-ms`) means *paused*; the serial port closing means *disconnected*.
- Sticks and switches are normalised by `--scale` (default 1024).

The protocol is receive-only: nothing is ever sent to the radio.

## Recordings (JSONL)

One JSON object per line. The first line is a header:

```json
{"format": "sticklink-log", "version": 1, "sticklink": "0.1.0", "source": "serial:/dev/ttyACM0",
 "config": {"scale": 1024, "stale_ms": 500, "...": "..."}, "started_unix_ns": 1791290463414000000}
```

After it, either a parsed record or a connection event, each stamped with both clocks:

```json
{"received_monotonic_ns": 1117056369337138, "received_unix_ns": 1791281833702207517, "session": 1,
 "record": {"type": "S", "tick": 22872, "seq": 6323, "channels": {"roll": 12, "pitch": -4, "yaw": 0, "throttle": -1024, "arm": -1024, "crash": -1024}}}
{"received_monotonic_ns": 1117056369999999, "received_unix_ns": 1791281833999999999, "session": 1,
 "connection": {"connected": false, "message": "device disconnected"}}
```

The parsed record has the same fields as the line, with names (`channels`, `outputs`, `sensor`, `message`, ...).
`received_monotonic_ns` is for measuring gaps on the computer; `received_unix_ns` is wall-clock time; `tick` is the
radio's clock. Sensor names are stored as sent, so logs do not depend on `RQly`/`RxBt`. Logs open in append mode and are
flushed line by line; a torn last line (after a crash) is ignored by `replay` and `check-log`.
