"""aiohttp app: serves the overlay page and broadcasts snapshots over WebSocket."""
import asyncio
from contextlib import suppress
import json
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from . import api
from .fxconfig import FxConfigStore
from .obs import ObsClient
from .plugins import PluginStore
from .recorder import Recorder
from .scenes import SceneEngine, SceneStore

WEB = Path(__file__).resolve().parent/'web'


class OverlayServer:
    def __init__(self, pipeline, source, hz=30, fx_config=None, recorder=None, scene_store=None, plugin_store=None):
        self.pipeline, self.source, self.hz = pipeline, source, hz
        self.fx_config = fx_config or FxConfigStore()
        self.recorder = recorder or Recorder(pipeline, source=source.label)
        self.scene_store = scene_store or SceneStore()
        self.plugins = plugin_store or PluginStore()
        self.obs = ObsClient()
        self.scenes = SceneEngine(self.scene_store, self.obs, pipeline.state.channels_now)
        self.obs.configure(self.scene_store.load()['obs'])
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
                 asyncio.create_task(self.publisher()),
                 asyncio.create_task(self.obs.run()),
                 asyncio.create_task(self.scenes.run())]
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

        async def hud(request):
            return web.FileResponse(WEB/'hud.html')

        async def modes_page(request):
            return web.FileResponse(WEB/'modes.html')

        async def docs(request):
            return web.FileResponse(WEB/'docs.html')
        # Plugins: the host page is trusted; the plugin script runs in a frame that is sandboxed (no same-origin) and, by CSP,
        # cannot make any network request. It only ever receives data through postMessage.
        async def viz_gallery(request):
            return web.FileResponse(WEB/'viz-gallery.html')

        async def viz_host(request):
            if self.plugins.get(request.match_info['id']) is None:
                raise web.HTTPNotFound(text='no such visualiser')
            return web.FileResponse(WEB/'viz.html')

        async def viz_frame(request):
            plugin = self.plugins.get(request.match_info['id'])
            if plugin is None or plugin['error']:
                raise web.HTTPNotFound(text='no such visualiser')
            entry = quote(plugin['entry'])
            page = ('<!doctype html><meta charset="utf-8"><style>html,body{margin:0;height:100%;background:transparent;overflow:hidden}'
                    'canvas{display:block;width:100%;height:100%}</style><canvas id="c"></canvas>'
                    f'<script src="/assets/viz-runtime.js"></script><script src="/viz/{quote(plugin["id"])}/file/{entry}"></script>')
            return web.Response(text=page, content_type='text/html', headers={
                'Content-Security-Policy': ("sandbox allow-scripts; default-src 'none'; script-src 'self'; img-src 'self' data: blob:; "
                                            "font-src 'self' data:; style-src 'unsafe-inline'; connect-src 'none'; media-src 'none'; "
                                            "base-uri 'none'; form-action 'none'"),
                'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer'})

        async def viz_file(request):
            path = self.plugins.file(request.match_info['id'], request.match_info['rel'])
            if path is None:
                raise web.HTTPNotFound(text='no such file')
            return web.FileResponse(path, headers={'Cache-Control': 'no-cache', 'X-Content-Type-Options': 'nosniff'})
        api.register(app, self)
        app.router.add_get('/viz', viz_gallery)
        app.router.add_get('/viz/{id}', viz_host)
        app.router.add_get('/viz/{id}/frame', viz_frame)
        app.router.add_get('/viz/{id}/file/{rel:.+}', viz_file)
        app.router.add_get('/fx', fx)
        app.router.add_get('/setup', setup)
        app.router.add_get('/docs', docs)
        app.router.add_get('/modes', modes_page)
        for page in ('/hud', '/hud/link', '/hud/battery', '/hud/gps', '/hud/status'):
            app.router.add_get(page, hud)
        app.router.add_get('/', overlay)
        app.router.add_get('/overlay', overlay)
        app.router.add_static('/assets', WEB, show_index=False)
        return app
