"""Run the bridge in a background thread, so a window (or a test) can start and stop it."""
import asyncio
import threading

from aiohttp import web

from .config import Config
from .pipeline import Pipeline
from .server import OverlayServer
from .sources.demo import DemoSource
from .sources.serial_port import SerialSource

HOST = '127.0.0.1'


class Service:
    """start(port=None) serves demo data, start('COM5') reads that radio. Never raises from the UI thread's view
    except for start(): it raises OSError when the HTTP port is taken."""

    def __init__(self, http_port=8765, **server_options):
        self.http_port = http_port
        self.server_options = server_options  # e.g. fx_config=, scene_store= (tests keep them out of the real config)
        self.pipeline = None
        self._thread = None
        self._loop = None
        self._stop = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def url(self, path=''):
        return f'http://{HOST}:{self.http_port}{path}'

    def start(self, port=None, baud=115200):
        if self.running:
            return
        demo = port is None
        self.pipeline = Pipeline(Config(input_label='sticks', demo=demo))
        source = DemoSource() if demo else SerialSource(port, baud)
        started = threading.Event()
        failure = []

        async def main():
            self._loop, self._stop = asyncio.get_running_loop(), asyncio.Event()
            runner = web.AppRunner(OverlayServer(self.pipeline, source, **self.server_options).app())
            try:
                await runner.setup()
                await web.TCPSite(runner, HOST, self.http_port).start()
            except OSError as exc:
                failure.append(exc)
                started.set()
                await runner.cleanup()
                return
            started.set()
            await self._stop.wait()
            await runner.cleanup()

        self._thread = threading.Thread(target=lambda: asyncio.run(main()), name='sticklink-service', daemon=True)
        self._thread.start()
        started.wait(10)
        if failure:
            self._thread.join(5)
            raise failure[0]

    def stop(self):
        if self.running:
            self._loop.call_soon_threadsafe(self._stop.set)
            self._thread.join(10)

    def status(self):
        """(level, text): level is 'off', 'wait', 'ok' or 'bad'."""
        if not self.running:
            return 'off', 'Stopped'
        snap = self.pipeline.snapshot()
        state = snap['status']
        if state == 'demo':
            return 'ok', 'Running with demo data (no radio)'
        if state == 'live':
            return 'ok', 'Radio connected: sticks are live'
        if state == 'paused':
            return 'wait', 'Radio connected, but no data. Is the DDSTK script running? (see Radio setup)'
        return 'wait', 'Waiting for the radio' + (f' ({snap["error"]})' if snap.get('error') else '')
