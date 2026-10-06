"""Smoke test for a built Sticklink program: python packaging/smoke_test.py PATH_TO_EXECUTABLE

Starts it in demo mode and checks the pages, assets and API a user depends on. Uses only the standard library so
it behaves the same on Linux, Windows and macOS.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PORT = 8899
BASE = f'http://127.0.0.1:{PORT}'
PAGES = ['/fx', '/setup', '/overlay', '/docs', '/hud', '/hud/link', '/hud/battery', '/hud/gps', '/hud/status',
         '/assets/stickfx.js', '/assets/setup.js', '/assets/hud.js', '/assets/components.js',
         '/assets/fonts/bungee-latin-400-normal.woff2', '/assets/swagger/swagger-ui-bundle.js',
         '/assets/swagger/swagger-ui.css']
API = ['/api/v1/openapi.json', '/api/v1/styles', '/api/v1/settings', '/api/v1/gps', '/api/v1/gps/track', '/api/v1/telemetry', '/api/v1/channels']


def get(path, method='GET', body=None):
    request = urllib.request.Request(BASE + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={'content-type': 'application/json'} if body is not None else {})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read()


def stop(process):
    if os.name == 'nt':  # a PyInstaller one-file program on Windows has a child process
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], capture_output=True)
    else:
        process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()


def main(exe):
    with tempfile.TemporaryDirectory() as tmp:
        quick = subprocess.run([exe, '--help'], capture_output=True, text=True, timeout=120)
        assert quick.returncode == 0 and 'radio-script' in quick.stdout, quick.stdout + quick.stderr
        script = subprocess.run([exe, 'radio-script', tmp], capture_output=True, text=True, timeout=60)
        assert script.returncode == 0, script.stderr
        lua = open(os.path.join(tmp, 'DDSTK.lua'), encoding='utf-8').read()
        assert 'return { init=init, run=run' in lua
        print('help and radio-script ok')

        process = subprocess.Popen([exe, 'run', '--demo', '--http-port', str(PORT), '--fx-config', os.path.join(tmp, 'fx.json'),
                                    '--recordings-dir', os.path.join(tmp, 'rec')], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            deadline = time.time() + 90  # a one-file program unpacks itself first
            while True:
                try:
                    get('/api/v1/status')
                    break
                except (urllib.error.URLError, ConnectionError):
                    if process.poll() is not None or time.time() > deadline:
                        raise SystemExit(f'server did not start (exit {process.poll()}):\n{process.stdout.read() if process.poll() is not None else ""}')
                    time.sleep(0.5)
            for path in PAGES:
                status, data = get(path)
                assert status == 200 and len(data) > 100, (path, status, len(data))
            for path in API:  # JSON, however small (a track is empty before the first fix)
                status, data = get(path)
                assert status == 200 and isinstance(json.loads(data), (dict, list)), (path, status, data[:80])
            time.sleep(1.5)
            state = json.loads(get('/api/v1/state')[1])
            assert state['status'] == 'demo' and state['controls'] is not None, state
            assert state['channels'] is not None and len(state['channels']) == 16, 'demo should report all 16 channels'
            assert state['gps']['fix'] and state['gps']['home'] and len(state['telemetry']) >= 20, 'demo should report GPS and the full sensor set'
            status = json.loads(get('/api/v1/status')[1])
            assert status['radio']['connected'] and status['diagnostics']['samples'] > 0, status
            code, data = get('/api/v1/recording', 'POST', {'label': 'smoke'})
            assert code == 201, code
            time.sleep(1)
            stopped = json.loads(get('/api/v1/recording', 'DELETE')[1])
            assert stopped['records'] > 0 and not stopped['active'], stopped
            name = json.loads(get('/api/v1/recordings')[1])[0]['name']
            report = json.loads(get(f'/api/v1/recordings/{name}/report')[1])
            assert report['counts']['samples'] > 10, report['counts']
            code, data = get('/api/v1/settings', 'PATCH', {'style': 'hacker'})
            assert json.loads(data)['style'] == 'hacker'
            print(f'server ok: {len(PAGES)} pages/assets, {len(API)} API endpoints, live demo state, recording ({report["counts"]["samples"]} samples), settings')
        finally:
            stop(process)
    print('SMOKE TEST PASSED')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(os.path.abspath(sys.argv[1]))
