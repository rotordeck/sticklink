"""Real-browser checks of the HUD pages and the map's tile behaviour.

Opt-in (needs Chrome and Node 22+, and takes about a minute): STICKLINK_BROWSER_TESTS=1 python -m unittest tests.test_hud_browser
CI runs it in its own job. Set CHROME to the browser executable if it is not on PATH as google-chrome-stable.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT/'tests'/'browser'/'check.mjs'
NODE = shutil.which('node')
CHROME = os.environ.get('CHROME') or next((shutil.which(n) for n in ('google-chrome-stable', 'google-chrome', 'chromium', 'chromium-browser') if shutil.which(n)), None)
ENABLED = os.environ.get('STICKLINK_BROWSER_TESTS') == '1' and NODE and CHROME


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def png_tile():
    import struct
    import zlib
    rows = b''.join(b'\x00' + bytes([225, 230, 220] * 256) for _ in range(256))
    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        return c + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 256, 256, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


class TileServer:
    """A fake tile server that records every request, answering with a tile or with 404."""
    def __init__(self, ok=True):
        self.requests, tile, outer = [], png_tile(), self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append(dict(path=self.path, referer=self.headers.get('Referer'), ua=self.headers.get('User-Agent')))
                if not ok:
                    self.send_response(404); self.end_headers(); return
                self.send_response(200); self.send_header('Content-Type', 'image/png'); self.send_header('Cache-Control', 'max-age=3600'); self.end_headers()
                self.wfile.write(tile)

            def log_message(self, *args):
                pass
        self.port = free_port()
        self.server = HTTPServer(('127.0.0.1', self.port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown(); self.server.server_close()


def api(base, path, method='GET', body=None):
    request = urllib.request.Request(base + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={'content-type': 'application/json'} if body is not None else {})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read() or b'null')


@unittest.skipUnless(ENABLED, 'set STICKLINK_BROWSER_TESTS=1 (needs Chrome and Node 22+)')
class HudBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        port = free_port()
        cls.base = f'http://127.0.0.1:{port}'
        cls.proc = subprocess.Popen([sys.executable, '-m', 'sticklink', 'run', '--demo', '--http-port', str(port),
                                     '--fx-config', str(Path(cls.tmp.name)/'fx.json'), '--recordings-dir', str(Path(cls.tmp.name)/'rec')],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                api(cls.base, '/api/v1/status')
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.2)
        else:
            raise RuntimeError('server did not start')
        time.sleep(2)  # let the demo produce a GPS track

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.tmp.cleanup()

    def check(self, path, width=1280, height=720, wait=3500):
        run = subprocess.run([NODE, str(CHECK), self.base + path, str(width), str(height), str(wait)], capture_output=True, text=True, timeout=90,
                             env={**os.environ, 'CHROME': CHROME})
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout.strip().splitlines()[-1])

    def test_every_hud_page_renders_without_errors(self):
        api(self.base, '/api/v1/settings', 'PATCH', dict(hud=dict(map=dict(provider='none'))))
        for path, minimum in (('/hud', 0.02), ('/hud/link', 0.08), ('/hud/battery', 0.08), ('/hud/gps', 0.08), ('/hud/status', 0.05)):
            result = self.check(path)
            self.assertEqual(result['errors'], [], path)
            self.assertIsNotNone(result['canvas'], path)
            self.assertGreater(result['litFraction'], minimum, f'{path} drew almost nothing')

    def test_every_style_and_layout_renders(self):
        for style, layout in (('hacker', 'corners'), ('synthwave', 'row'), ('unicorn', 'column'), ('clean', 'corners')):
            api(self.base, '/api/v1/settings', 'PATCH', dict(hud=dict(style=style, layout=layout, map=dict(provider='none'))))
            result = self.check('/hud', wait=2500)
            self.assertEqual(result['errors'], [], f'{style}/{layout}')
            self.assertGreater(result['litFraction'], 0.02, f'{style}/{layout}')

    def test_map_loads_only_visible_tiles_with_a_referer_and_draws_them(self):
        tiles = TileServer(ok=True)
        try:
            api(self.base, '/api/v1/settings', 'PATCH', dict(hud=dict(map=dict(
                provider='custom', customUrl=f'http://127.0.0.1:{tiles.port}/{{z}}/{{x}}/{{y}}.png', attribution='Test tiles'))))
            result = self.check('/hud/gps', width=760, height=560, wait=6000)
            self.assertEqual(result['errors'], [])
            paths = [r['path'] for r in tiles.requests]
            self.assertGreater(len(paths), 0, 'the map asked for tiles')
            self.assertEqual(len(paths), len(set(paths)), 'no tile is requested twice')
            self.assertLessEqual(len(paths), 24, f'only tiles in view are requested (no prefetch): {len(paths)}')
            self.assertTrue(all(r['referer'] == self.base + '/' for r in tiles.requests), 'the browser sends its normal Referer')
            self.assertTrue(all('Chrome' in (r['ua'] or '') for r in tiles.requests))
        finally:
            tiles.close()

    def test_failing_tiles_do_not_cause_a_retry_storm(self):
        tiles = TileServer(ok=False)
        try:
            api(self.base, '/api/v1/settings', 'PATCH', dict(hud=dict(map=dict(
                provider='custom', customUrl=f'http://127.0.0.1:{tiles.port}/{{z}}/{{x}}/{{y}}.png'))))
            result = self.check('/hud/gps', width=760, height=560, wait=7000)
            self.assertEqual(result['errors'], [])
            self.assertLessEqual(len(tiles.requests), 16, f'a failed tile is not retried every frame: {len(tiles.requests)} requests')
            self.assertGreater(result['litFraction'], 0.05, 'the tile-free fallback still draws the track and readouts')
        finally:
            tiles.close()


if __name__ == '__main__':
    unittest.main()
