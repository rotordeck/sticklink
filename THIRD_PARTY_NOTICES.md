# Third-party notices

Sticklink bundles or builds on the following. Licence texts are shipped next to the files they cover.

## Bundled in the app

| Component | Licence | Where |
|---|---|---|
| [Swagger UI](https://github.com/swagger-api/swagger-ui) 5.33.1 (`swagger-ui-dist`, unmodified) | Apache-2.0 | `src/sticklink/web/swagger/` (`LICENSE`, `NOTICE`) |
| Fonts: Bungee, Orbitron (900), Fredoka (700), VT323, via [Fontsource](https://fontsource.org) | SIL Open Font License 1.1 | `src/sticklink/web/fonts/`, texts in `fonts/LICENSES/` |
| Stick overlay renderer (`draw.ts`, `style.ts`, `layout.ts`) | Own code, copied unchanged from [rotordeck/stickcam](https://github.com/rotordeck/stickcam) @ `ca82bf34` | `fx/src/render/`, see `fx/VENDORED_FROM` |

## Map tiles (loaded at runtime, not bundled)

The GPS block can show map tiles. Map data is (c) OpenStreetMap contributors, available under the [Open Database Licence](https://www.openstreetmap.org/copyright).
Tiles are requested from the provider the user selects: the OpenStreetMap standard tile servers (subject to the
[OSMF Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/)), CARTO basemaps (free for non-commercial use only; see CARTO's terms), or a
custom server. Each provider's credit is always drawn on the map.

## Python dependencies (installed or frozen into the binaries)

| Package | Licence |
|---|---|
| [aiohttp](https://github.com/aio-libs/aiohttp) and its dependencies | Apache-2.0 (and permissive licences of its dependencies) |
| [pyserial](https://github.com/pyserial/pyserial) | BSD-3-Clause |
| [PyInstaller](https://pyinstaller.org) (only used to build the binaries) | GPL-2.0 with a special exception that permits distributing the frozen programs it creates under any licence |
| Python itself (embedded in the binaries) | PSF License |

## Build-time only (not shipped)

TypeScript, esbuild, Node.js test tooling, openapi-spec-validator, build.

## This project

No licence has been chosen yet; until one is added, all rights are reserved by the authors.
