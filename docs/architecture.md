# Architecture

```text
radio (DDSTK.lua) --USB serial--> Source --> Pipeline --> OverlayServer --WebSocket--> overlay pages (OBS)
                                              |  RadioState              \--> REST API (/api/v1)
                                              \--> JsonlLog (recording)
```

| Module (`src/sticklink/`) | Role |
|---|---|
| `protocol/ddlog.py` | Line framing and the parser for the DDLOG records |
| `state.py` | `RadioState`: sessions, sequence gaps, aging, GPS fix / home / track, the snapshot sent to overlays |
| `pipeline.py` | `Pipeline`: sources call `connection()` / `accept()`; state and recording hang off it |
| `sources/` | `Source.run(pipeline)`: `serial_port.py` (reconnects), `demo.py`, `replay.py`. New inputs go here |
| `sinks/jsonl_log.py`, `recorder.py` | The recording file format; start/stop and the recordings folder |
| `server.py`, `api.py`, `openapi.py` | aiohttp app: pages, WebSocket, REST API, Host guard, the OpenAPI document |
| `geo.py` | Distance and bearing for the GPS block |
| `obs.py` | A small obs-websocket v5 client: scenes, current scene, switching; reconnects by itself |
| `plugins.py` | Finds, validates and installs visualiser plugins (folders with `plugin.json` + a canvas script); safe zip extraction, file lookup that cannot leave the plugin folder |
| `service.py`, `gui.py` | The bridge in a background thread, and the small tkinter window around it |
| `scenes.py` | The scene-mode store (private file, validation) and `SceneEngine`: channel ranges to scene switches, with debounce, priority and safety rules |
| `fxconfig.py` | Validated, atomically written overlay settings and defaults (including the HUD and map settings) |
| `analysis.py` | `check-log` / report |
| `cli.py` | The command line |
| `web/` | Pages and scripts served to the browser: `fx.html`, `setup.html`, `overlay.html`, `docs.html`, bundles, fonts, Swagger UI |
| `radio/DDSTK.lua` | The EdgeTX script |

## The overlay (TypeScript, `fx/`)

| File | Role |
|---|---|
| `src/render/{draw,style,layout}.ts` | stickcam's canvas renderer, copied unchanged (`fx/VENDORED_FROM`) |
| `src/live.ts` | `LiveFeed`: builds the frame history the renderer reads, one 60 fps frame at a time. Redraws earlier frames as smooth curves when a reading arrives; detects snaps, punch-outs, full-throttle and hang-time spans, arm/disarm |
| `src/mapping.ts` | Which input drives which function, and the learn-by-moving detector |
| `src/element.ts`, `src/index.ts` | The `<stick-fx>` page element (canvas, settings panel, config sync) |
| `src/setup.ts`, `src/drone3d.ts` | The `/setup` page and its 3D quad |
| `src/modes/` | The `/modes` page: microsecond scale and handle maths (`scale.ts`), the card list and edits (`model.ts`), the DOM page (`modes-page.ts`) |
| `src/curve.ts` | Monotone cubic interpolation |
| `src/hud/catalog.ts` | Sensor names to labelled badges, units, bars and warning levels; builds the Link, Battery and GPS models (pure) |
| `src/hud/geo.ts`, `layout.ts`, `history.ts` | Map projection and tile maths, block placement for each layout, sparkline buffers (pure) |
| `src/hud/look.ts` | Turns a stickcam `Style` into badge plates, dials, bars and text for the HUD |
| `src/hud/blocks.ts`, `map.ts` | The four blocks, and the policy-conscious map tile loader |
| `src/hud/hud-element.ts` | The `<stick-hud>` page element: data, settings panel, GPS track upkeep, render loop |

`npm run build` (in `fx/`) bundles it with esbuild into `src/sticklink/web/stickfx.js` and `setup.js`. **The bundles are
committed**, so installing or running Sticklink never needs Node.

## Design decisions worth knowing

- **Receive-only and local.** The bridge never writes to the radio and only listens on `127.0.0.1`.
- **Snapshots, not events.** The server publishes the whole state about 30 times a second; pages do the rest. A page can
  reconnect at any time and is correct after one message.
- **One owner per serial port.** Two programs reading the same port split the data between them. Sticklink cannot detect this.
- **History is data.** The renderer is a pure function of the frame history, so smoothing is done by rewriting history
  (no lag) rather than by delaying the display.
- **Settings live on the server**, not in the browser, so the OBS source and a normal browser tab show the same thing.
