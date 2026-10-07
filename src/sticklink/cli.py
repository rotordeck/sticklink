import argparse
import asyncio
from pathlib import Path
import math
import shutil
import sys

from aiohttp import web

from .analysis import analyze, format_report
from .config import Config
from .fxconfig import FxConfigStore
from .pipeline import Pipeline
from .themes import ThemeError, ThemeStore
from .server import OverlayServer
from .service import PAGES, describe_status
from .recorder import Recorder
from .scenes import SceneStore
from .sources.demo import DemoSource
from .sources.replay import ReplaySource
from .sources.serial_port import SerialSource


def parser():
    p = argparse.ArgumentParser(prog='sticklink', description='Live stick and telemetry overlays for OBS, from an EdgeTX radio.')
    sub = p.add_subparsers(dest='command', required=True)

    def serving(sp):
        sp.add_argument('--http-port', type=int, default=47613)
        sp.add_argument('--stale-ms', type=int, default=500)
        sp.add_argument('--scale', type=float, default=1024)
        sp.add_argument('--arm-threshold', type=int, default=0)
        sp.add_argument('--crash-threshold', type=int, default=0)
        sp.add_argument('--race-double-tap-ms', type=int, default=500, help='two crash-flip taps this close together stop the race timer')
        sp.add_argument('--input-label', choices=['sticks', 'outputs', 'unknown'],
                        default='unknown')
        sp.add_argument('--log', help='start recording a JSONL session log to this file right away')
        sp.add_argument('--recordings-dir', help='folder for recordings made through the API (default ~/.local/share/sticklink/recordings)')
        sp.add_argument('--fx-config', help='overlay settings file (default ~/.config/sticklink/fx.json)')
        sp.add_argument('--themes-dir', help='folder with your overlay themes (default ~/.config/sticklink/themes)')
        sp.add_argument('--scenes-config', help='OBS connection and scene-mode settings, incl. the OBS password (default ~/.config/sticklink/scenes.json)')

    run = sub.add_parser('run', help='serve the overlay from a radio or the demo')
    run.add_argument('--port', help='COM5, /dev/ttyACM0, /dev/cu.usbmodem…')
    run.add_argument('--demo', action='store_true', help='synthetic data; no radio')
    run.add_argument('--baud', type=int, default=115200)
    serving(run)

    replay = sub.add_parser('replay', help='serve a recorded log as if it were live')
    replay.add_argument('file')
    replay.add_argument('--speed', type=float, default=1.0)
    replay.add_argument('--loop', action='store_true')
    serving(replay)

    check = sub.add_parser('check-log', help='report on the quality of a recorded log')
    check.add_argument('file')

    script = sub.add_parser('radio-script', help='copy the EdgeTX Lua script (DDSTK.lua) to a folder, e.g. the radio SD card')
    script.add_argument('dest', nargs='?', default='.',
                        help='folder to copy into (default: here). Use <SD card>/SCRIPTS/FUNCTIONS for the radio')

    theme = sub.add_parser('theme', help='manage overlay themes (see docs/themes.md)')
    theme.add_argument('--themes-dir', help='themes folder (default ~/.config/sticklink/themes)')
    psub = theme.add_subparsers(dest='action', required=True)
    install = psub.add_parser('install', help='install a theme from a folder, a .zip or a single theme .json file')
    install.add_argument('source')
    install.add_argument('--force', action='store_true', help='replace an installed theme with the same name')
    remove = psub.add_parser('remove', help='remove one of your themes')
    remove.add_argument('id')
    psub.add_parser('list', help='list the installed themes')
    psub.add_parser('path', help='print the themes folder')

    lp = sub.add_parser('list-ports', help='list serial ports (radios only, like the window)')
    lp.add_argument('--all', action='store_true', help='also list built-in serial ports with no hardware id')
    gui_p = sub.add_parser('gui', help='a small window with Start / Stop, status and links (also what you get with no command)')
    gui_p.add_argument('--http-port', type=int, default=47613)
    return p


def main(argv=None):
    p = parser()
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        argv = ['gui']  # double-clicked program: open the window
    args = p.parse_args(argv)
    if args.command == 'gui':
        try:
            from . import gui
        except ImportError:  # Python without tkinter (some Linux distributions package it separately)
            p.error('the window needs tkinter (Linux: install python3-tk). The other commands work without it.')
        return gui.main(args.http_port)
    if args.command == 'list-ports':
        from serial.tools.list_ports import comports
        for port in comports():
            if not args.all and (not port.hwid or port.hwid == 'n/a'):
                continue
            print(f'{port.device}\t{port.description}')
        return
    if args.command == 'radio-script':
        source = Path(__file__).resolve().parent/'radio'/'DDSTK.lua'
        dest = Path(args.dest)
        if not dest.is_dir():
            p.error(f'{dest} is not a folder')
        shutil.copyfile(source, dest/'DDSTK.lua')
        print(f'Copied DDSTK.lua to {dest/"DDSTK.lua"}')
        print('On the radio it belongs in /SCRIPTS/FUNCTIONS/ (see docs/radio-setup.md).')
        return
    if args.command == 'theme':
        store = ThemeStore(args.themes_dir)
        try:
            if args.action == 'install':
                print(f'Installed "{store.install(args.source, args.force)}" in {store.user_dir}. It shows up in the style list (double-click the overlay) without a restart.')
            elif args.action == 'remove':
                store.remove(args.id)
                print(f'Removed "{args.id}".')
            elif args.action == 'path':
                print(store.user_dir)
            else:
                for item in store.all().values():
                    print(f'{item["id"]}\t{item["source"]}\t{item["name"]}' + (f'\tERROR: {item["error"]}' if item['error'] else ''))
        except ThemeError as exc:
            p.error(str(exc))
        return
    if args.command == 'check-log':
        print(format_report(analyze(args.file)))
        return
    if not math.isfinite(args.scale) or args.scale <= 0 or args.stale_ms <= 0:
        p.error('scale and stale-ms must be positive finite values')
    if not 1 <= args.http_port <= 65535:
        p.error('invalid http port')
    if args.command == 'run':
        if bool(args.port) == args.demo:
            p.error('choose exactly one of --port COM5 or --demo')
        if args.baud <= 0:
            p.error('invalid baud rate')
        source = DemoSource() if args.demo else SerialSource(args.port, args.baud)
    else:
        if args.speed <= 0:
            p.error('speed must be positive')
        source = ReplaySource(args.file, args.speed, args.loop)
    config = Config(scale=args.scale, stale_ms=args.stale_ms,
        arm_threshold=args.arm_threshold, crash_threshold=args.crash_threshold,
        race_double_tap_ms=args.race_double_tap_ms,
        input_label=args.input_label, demo=args.command == 'run' and args.demo)
    pipeline = Pipeline(config)
    recorder = Recorder(pipeline, args.recordings_dir, source=source.label)
    if args.log:
        recorder.start_path(args.log)
    port = args.http_port
    import socket
    with socket.socket() as probe:  # a second Sticklink (or anything else) on the port: say so instead of a traceback
        if probe.connect_ex(('127.0.0.1', port)) == 0:
            from .service import running_sticklink
            other = running_sticklink(port)
            p.exit(1, (f'Sticklink {other} is already running on port {port} (another terminal or the window). Close it first, '
                       f'or open http://127.0.0.1:{port}/ for its web portal.\n') if other else
                   f'Port {port} is used by another program. Close it, or pick another port with --http-port.\n')
    for label, path in PAGES:
        print(f'{label + ":":<18}http://127.0.0.1:{port}{path}')
    print(flush=True)
    app = OverlayServer(pipeline, source, fx_config=FxConfigStore(args.fx_config), recorder=recorder,
                        scene_store=SceneStore(args.scenes_config), theme_store=ThemeStore(args.themes_dir)).app()

    async def report_status(app):
        async def watch():
            last = None
            while True:
                text = describe_status(pipeline.snapshot(), getattr(args, 'port', None))[1]
                if text != last:
                    print(f'Status: {text}', flush=True)
                    last = text
                await asyncio.sleep(0.5)
        task = asyncio.create_task(watch())
        yield
        task.cancel()
    app.cleanup_ctx.append(report_status)
    web.run_app(app, host='127.0.0.1', port=port, print=None)
