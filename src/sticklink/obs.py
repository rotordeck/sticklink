"""A small obs-websocket v5 client (OBS Studio 28+ has the server built in): lists scenes, follows the current one, switches scenes.

Protocol: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
It reconnects by itself, never blocks the radio pipeline, and never logs or returns the password.
"""
import asyncio
import base64
from contextlib import suppress
import hashlib
import json
import time
import uuid

import aiohttp

RPC_VERSION = 1
SUBSCRIBE = 1 | 4  # General + Scenes event categories
RETRY_S = 3.0
AUTH_FAILED = 4009  # websocket close code for a wrong password


class ObsError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def auth_string(password, salt, challenge):
    """The Identify.authentication value: base64(sha256(base64(sha256(password + salt)) + challenge))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


class ObsClient:
    def __init__(self):
        self.settings = dict(enabled=False, host='127.0.0.1', port=4455, password='')
        self.status = 'disabled'  # disabled | connecting | connected | unreachable | auth_failed | error
        self.error = ''
        self.version = None
        self.scenes = []  # names, in the order OBS lists them
        self.current = None
        self.generation = 0  # bumps on every (re)connect: the engine re-baselines
        self._ws = None
        self._pending = {}
        self._wake = asyncio.Event()
        self._loader = None
        self.last_switch_error = ''

    # ---------------------------------------------------------------- configuration
    def configure(self, settings):
        """Apply new connection settings; the connection is re-made if anything changed."""
        changed = settings != self.settings
        self.settings = dict(settings)
        if changed:
            self.error = ''
            self._wake.set()
            self._drop()

    def _drop(self):
        ws = self._ws
        if ws is not None and not ws.closed:
            asyncio.ensure_future(ws.close())

    def snapshot(self):
        s = self.settings
        return dict(status=self.status, error=self.error, enabled=s['enabled'], host=s['host'], port=s['port'],
                    passwordSet=bool(s['password']), version=self.version, currentScene=self.current, scenes=list(self.scenes))

    # ---------------------------------------------------------------- connection loop
    async def run(self):
        while True:
            self._wake.clear()
            if not self.settings['enabled']:
                self.status, self.error = 'disabled', ''
                await self._wake.wait()
                continue
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except aiohttp.ClientConnectorError as exc:
                self.status, self.error = 'unreachable', f'cannot reach OBS at {self.settings["host"]}:{self.settings["port"]}: {exc.os_error.strerror if exc.os_error else exc}'
            except ObsError as exc:
                self.status, self.error = ('auth_failed' if exc.code == AUTH_FAILED else 'error'), str(exc)
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, KeyError) as exc:
                self.status, self.error = 'error', f'{type(exc).__name__}: {exc}'
            finally:
                self._ws = None
                self._fail_pending()
                self.scenes, self.version = [], None
                self.current = None
            if self.status == 'auth_failed':  # retrying with the same password cannot work: wait for new settings
                await self._wake.wait()
            else:
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), RETRY_S)

    def _fail_pending(self):
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ObsError('connection to OBS closed'))
        self._pending.clear()

    async def _session(self):
        s = self.settings
        self.status, self.error = 'connecting', ''
        host = f'[{s["host"]}]' if ':' in s['host'] else s['host']
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, connect=5)) as http:
            async with http.ws_connect(f'ws://{host}:{s["port"]}', protocols=('obswebsocket.json',), heartbeat=15, max_msg_size=8*1024*1024) as ws:
                self._ws = ws
                hello = json.loads((await asyncio.wait_for(ws.receive(), 10)).data)
                if hello.get('op') != 0:
                    raise ObsError('not an obs-websocket server')
                identify = dict(rpcVersion=RPC_VERSION, eventSubscriptions=SUBSCRIBE)
                challenge = hello['d'].get('authentication')
                if challenge:
                    if not s['password']:
                        raise ObsError('OBS asks for a password but none is set', AUTH_FAILED)
                    identify['authentication'] = auth_string(s['password'], challenge['salt'], challenge['challenge'])
                await ws.send_json(dict(op=1, d=identify))
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    data = json.loads(msg.data)
                    op, d = data['op'], data['d']
                    if op == 2:  # Identified
                        self.status, self.error = 'connected', ''
                        self.generation += 1
                        self._loader = asyncio.ensure_future(self._load())
                    elif op == 5:
                        self._event(d)
                    elif op == 7:
                        future = self._pending.pop(d['requestId'], None)
                        if future and not future.done():
                            st = d['requestStatus']
                            future.set_result(d.get('responseData') or {}) if st['result'] else future.set_exception(ObsError(st.get('comment') or 'request failed', st.get('code')))
                if ws.close_code == AUTH_FAILED:
                    raise ObsError('OBS refused the password', AUTH_FAILED)
                if self._wake.is_set():  # we closed it on purpose (new settings)
                    return
                if True:
                    raise ObsError('connection to OBS closed' if self.status == 'connected' else 'OBS closed the connection during login', ws.close_code)

    # ---------------------------------------------------------------- requests and events
    async def request(self, kind, data=None, timeout=5.0):
        ws = self._ws
        if ws is None or ws.closed or self.status != 'connected':
            raise ObsError('not connected to OBS')
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await ws.send_json(dict(op=6, d=dict(requestType=kind, requestId=request_id, requestData=data or {})))
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise ObsError(f'OBS did not answer {kind}')

    async def _load(self):
        try:
            self.version = await self.request('GetVersion')
            await self.refresh_scenes()
        except ObsError as exc:
            self.error = str(exc)

    async def refresh_scenes(self):
        info = await self.request('GetSceneList')
        scenes = sorted(info.get('scenes', []), key=lambda sc: sc.get('sceneIndex', 0), reverse=True)  # OBS lists the highest index first
        self.scenes = [sc['sceneName'] for sc in scenes]
        self.current = info.get('currentProgramSceneName')

    def _event(self, d):
        kind, data = d.get('eventType'), d.get('eventData') or {}
        if kind == 'CurrentProgramSceneChanged':
            self.current = data.get('sceneName')
        elif kind in ('SceneListChanged', 'SceneCreated', 'SceneRemoved', 'SceneNameChanged'):
            asyncio.ensure_future(self._refresh_quietly())
        elif kind == 'ExitStarted':
            self.status = 'error'
            self.error = 'OBS is closing'

    async def _refresh_quietly(self):
        with suppress(ObsError):
            await self.refresh_scenes()

    async def set_scene(self, name):
        """Switch the program scene. Raises ObsError (also if the scene does not exist, or OBS is not connected)."""
        try:
            await self.request('SetCurrentProgramScene', dict(sceneName=name))
            self.last_switch_error = ''
        except ObsError as exc:
            self.last_switch_error = str(exc)
            raise
