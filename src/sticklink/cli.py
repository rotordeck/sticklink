import argparse
from pathlib import Path
import math
import shutil
import sys

from aiohttp import web

from .analysis import analyze, format_report
from .config import Config
from .fxconfig import FxConfigStore
from .pipeline import Pipeline
from .server import OverlayServer
from .recorder import Recorder
from .scenes import SceneStore
from .sources.demo import DemoSource
from .sources.replay import ReplaySource
from .sources.serial_port import SerialSource


def parser():
    p = argparse.ArgumentParser(prog='sticklink', description='Live stick and telemetry overlays for OBS, from an EdgeTX radio.')
    sub = p.add_subparsers(dest='command', required=True)

    def serving(sp):
        sp.add_argument('--http-port', type=int, default=8765)
        sp.add_argument('--stale-ms', type=int, default=500)
        sp.add_argument('--scale', type=float, default=1024)
        sp.add_argument('--arm-threshold', type=int, default=0)
        sp.add_argument('--crash-threshold', type=int, default=0)
        sp.add_argument('--input-label', choices=['sticks', 'outputs', 'unknown'],
                        default='unknown')
        sp.add_argument('--log', help='start recording a JSONL session log to this file right away')
        sp.add_argument('--recordings-dir', help='folder for recordings made through the API (default ~/.local/share/sticklink/recordings)')
        sp.add_argument('--fx-config', help='overlay settings file (default ~/.config/sticklink/fx.json)')
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

    sub.add_parser('list-ports', help='list serial ports')
    sub.add_parser('gui', help='a small window with Start / Stop, status and links (also what you get with no command)')
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
        return gui.main()
    if args.command == 'list-ports':
        from serial.tools.list_ports import comports
        for port in comports():
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
        input_label=args.input_label, demo=args.command == 'run' and args.demo)
    pipeline = Pipeline(config)
    recorder = Recorder(pipeline, args.recordings_dir, source=source.label)
    if args.log:
        recorder.start_path(args.log)
    print(f'OBS browser source: http://127.0.0.1:{args.http_port}/overlay   API docs: http://127.0.0.1:{args.http_port}/docs', flush=True)
    web.run_app(OverlayServer(pipeline, source, fx_config=FxConfigStore(args.fx_config), recorder=recorder,
                              scene_store=SceneStore(args.scenes_config)).app(),
                host='127.0.0.1', port=args.http_port)
