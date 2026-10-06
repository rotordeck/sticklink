# Development

## Set up

```bash
git clone git@github.com:rotordeck/sticklink.git && cd sticklink
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
(cd fx && npm ci)                                    # only needed to change the overlay code
```

## Tests

| What | Command |
|---|---|
| Python (protocol, state, log/replay, settings, REST API contract, security) | `python -m unittest discover -s tests` |
| Overlay logic (live feed, mapping, learn detector, config) | `cd fx && npm test` |
| Overlay type check | `cd fx && npm run typecheck` |
| HUD in a real browser: every page, style and layout, the permanent links, and the map's tile requests (needs Chrome and Node 22+) | `STICKLINK_BROWSER_TESTS=1 python -m unittest tests.test_hud_browser` |
| Radio script under a desktop Lua with a mocked EdgeTX (needs `lua`) | `python -m unittest tests.test_radio_script` |
| DOM test of the classic overlay (optional, needs jsdom) | `JSDOM_PATH=/path/to/node_modules/jsdom node tests/test_components.cjs` |

The API contract test needs the `dev` extra (`openapi-spec-validator`); it is skipped without it. It checks that the
OpenAPI document is valid, that every route is documented (and vice versa), and that real responses match the documented schemas.

Without a radio: `sticklink run --demo`, or `sticklink replay some-recording.jsonl --loop`.

## Changing the overlay (`fx/`)

Edit `fx/src`, then `cd fx && npm run build`. This writes `src/sticklink/web/stickfx.js` and `setup.js`; **commit them**
(CI fails if the committed bundles differ from a fresh build). Rules to remember:

- `fx/src/render/{draw,style,layout}.ts` are stickcam's, copied unchanged. Fix bugs upstream in `rotordeck/stickcam`, then re-copy and update `fx/VENDORED_FROM`.
- Node runs the TypeScript tests with type stripping: no enums, no constructor parameter properties, `.ts` extensions in imports.

## Changing the radio script

`src/sticklink/radio/DDSTK.lua` runs on EdgeTX's Lua runtime, which is stricter and smaller than desktop Lua. Check the syntax
with `luac -p`, and keep lines short (the longest line it sends is about 58 bytes). Anything optional is wrapped in `pcall`
so it cannot stop the stick stream. Test on a radio: see [validation log](validation.md).

## Building the binaries locally

```bash
pip install ".[binary]"          # non-editable install: the spec collects the package's data files from it
cd packaging && pyinstaller --noconfirm --clean --distpath ../dist --workpath ../build sticklink.spec
../dist/sticklink run --demo
```

The result is one self-contained program (Python included). PyInstaller builds for the system it runs on, so each
platform is built on its own CI runner. After building, reinstall the editable copy: `pip install -e .`.

## Continuous integration

| Workflow | Runs on | Does |
|---|---|---|
| `.github/workflows/ci.yml` | every push and pull request | Python tests on Linux, Windows and macOS (Python 3.10 and 3.13); overlay tests, type check and a check that the committed bundles are up to date |
| `.github/workflows/release.yml` | tags `v*`, or run by hand | builds the wheel and source package, and the PyInstaller binaries for Linux (x86-64), Windows (x86-64), macOS (Apple Silicon and Intel); smoke-tests each binary; on a tag, attaches everything with `SHA256SUMS.txt` to a GitHub Release, then uploads the wheel and source package to PyPI (so `uvx sticklink` works) |

## Releasing

1. Update `__version__` in `src/sticklink/__init__.py` and `CHANGELOG.md`; commit to `main`.
2. `git tag v0.1.0 && git push origin v0.1.0` (the tag must equal `v` + `__version__`; the workflow checks it).
3. The release workflow builds, tests the binaries and publishes the release. Tags with a `-` (`v0.2.0-rc1`) are marked pre-release.

**One-time PyPI setup** (the first upload fails until this is done): on pypi.org, *Your projects, Publishing, Add a pending publisher*:
project `sticklink`, owner `rotordeck`, repository `sticklink`, workflow `release.yml`, environment `pypi`. In GitHub, *Settings, Environments*,
create `pypi` (optionally with required reviewers). No API token is stored anywhere. Pre-release tags are not uploaded.

To try the pipeline without releasing: *Actions, Release, Run workflow*. Builds are attached to the run as artifacts.

## Code map

[Architecture](architecture.md), [protocol](protocol.md), [REST API](api.md).
