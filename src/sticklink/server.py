"""aiohttp app: serves the overlay page and broadcasts snapshots over WebSocket."""
import asyncio
from contextlib import suppress
import json
from pathlib import Path

from aiohttp import web

from . import api
from .fxconfig import FxConfigStore
from .recorder import Recorder

WEB = Path(__file__).resolve().parent/'web'


class OverlayServer:
    def __init__(self, pipeline, source, hz=30, fx_config=None, recorder=None):
        self.pipeline, self.source, self.hz = pipeline, source, hz
        self.fx_config = fx_config or FxConfigStore()
        self.recorder = recorder or Recorder(pipeline, source=source.label)
        self.clients = set()

    async def publisher(self):
        while True:
            payload = json.dumps(self.pipeline.snapshot(), allow_nan=False)

            async def send(client):
                try:
                    await asyncio.wait_for(client.send_str(payload), timeout=0.15)
                except (TimeoutError, ConnectionError, RuntimeError):
                    self.clients.discard(client)
                    await client.close()
            # Independent browser clients never block the source.
            await asyncio.gather(*(send(c) for c in tuple(self.clients)))
            await asyncio.sleep(1/self.hz)

    async def websocket(self, request):
        ws = web.WebSocketResponse(heartbeat=10, max_msg_size=1024)
        await ws.prepare(request)
        self.clients.add(ws)
        try:
            await ws.send_json(self.pipeline.snapshot())
            async for _ in ws:
                pass  # receive-only stream
        finally:
            self.clients.discard(ws)
        return ws

    async def lifecycle(self, app):
        tasks = [asyncio.create_task(self.source.run(self.pipeline)),
                 asyncio.create_task(self.publisher())]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            for client in tuple(self.clients):
                await client.close()
            self.recorder.close()

    def app(self):
        app = web.Application(middlewares=[api.guard], client_max_size=64*1024)
        app.cleanup_ctx.append(self.lifecycle)
        app.router.add_get('/ws', self.websocket)

        async def overlay(request):
            return web.FileResponse(WEB/'overlay.html')

        async def fx(request):
            return web.FileResponse(WEB/'fx.html')

        async def setup(request):
            return web.FileResponse(WEB/'setup.html')

        async def docs(request):
            return web.FileResponse(WEB/'docs.html')
        api.register(app, self)
        app.router.add_get('/fx', fx)
        app.router.add_get('/setup', setup)
        app.router.add_get('/docs', docs)
        app.router.add_get('/', overlay)
        app.router.add_get('/overlay', overlay)
        app.router.add_static('/assets', WEB, show_index=False)
        return app
