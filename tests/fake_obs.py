"""A fake obs-websocket v5 server for tests. It implements the handshake (with optional password) and the few requests Sticklink uses,
and records every request, so tests can assert exactly what would have been sent to a real OBS."""
import base64
import hashlib
import json
import secrets

from aiohttp import WSMsgType, web


class FakeObs:
    def __init__(self, scenes=('Intro', 'Drone', 'Room', 'Replay'), current='Intro', password=None):
        self.scenes, self.current, self.password = list(scenes), current, password
        self.requests, self.connections = [], 0
        self.sockets = []
        self.salt, self.challenge = secrets.token_urlsafe(16), secrets.token_urlsafe(16)

    def expected_auth(self):
        # written independently of sticklink.obs.auth_string, following the protocol document
        secret = base64.b64encode(hashlib.sha256((self.password + self.salt).encode()).digest()).decode()
        return base64.b64encode(hashlib.sha256((secret + self.challenge).encode()).digest()).decode()

    async def handler(self, request):
        ws = web.WebSocketResponse(protocols=('obswebsocket.json',))
        await ws.prepare(request)
        self.connections += 1
        self.sockets.append(ws)
        hello = dict(obsWebSocketVersion='5.5.4', rpcVersion=1)
        if self.password is not None:
            hello['authentication'] = dict(challenge=self.challenge, salt=self.salt)
        await ws.send_json(dict(op=0, d=hello))
        identified = False
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            op, d = data['op'], data['d']
            if op == 1:
                if self.password is not None and d.get('authentication') != self.expected_auth():
                    await ws.close(code=4009, message=b'Authentication failed.')
                    return ws
                identified = True
                await ws.send_json(dict(op=2, d=dict(negotiatedRpcVersion=1)))
            elif op == 6 and identified:
                await self.answer(ws, d)
        return ws

    async def answer(self, ws, d):
        kind, data = d['requestType'], d.get('requestData') or {}
        self.requests.append((kind, data))
        ok, body, code, comment = True, {}, 100, None
        if kind == 'GetVersion':
            body = dict(obsVersion='32.2.2', obsWebSocketVersion='5.5.4', rpcVersion=1)
        elif kind == 'GetSceneList':
            # OBS reports the scenes with the highest sceneIndex first in its UI order; the list is in ascending index order here
            body = dict(currentProgramSceneName=self.current, scenes=[dict(sceneName=n, sceneIndex=i) for i, n in enumerate(reversed(self.scenes))])
        elif kind == 'SetCurrentProgramScene':
            if data.get('sceneName') in self.scenes:
                self.current = data['sceneName']
                await ws.send_json(dict(op=5, d=dict(eventType='CurrentProgramSceneChanged', eventIntent=4, eventData=dict(sceneName=self.current))))
            else:
                ok, code, comment = False, 600, 'No scene was found by that name.'
        else:
            ok, code, comment = False, 204, 'Unknown request type.'
        status = dict(result=ok, code=code if not ok else 100)
        if comment:
            status['comment'] = comment
        await ws.send_json(dict(op=7, d=dict(requestType=kind, requestId=d['requestId'], requestStatus=status, responseData=body)))

    async def add_scene(self, name):
        self.scenes.append(name)
        for ws in self.sockets:
            if not ws.closed:
                await ws.send_json(dict(op=5, d=dict(eventType='SceneListChanged', eventIntent=4, eventData={})))

    def app(self):
        app = web.Application()
        app.router.add_get('/', self.handler)
        return app


if __name__ == '__main__':  # python tests/fake_obs.py PORT [scene ...]: a stand-in OBS for trying the Modes page without touching a real one
    import sys
    port = int(sys.argv[1])
    scenes = sys.argv[2:] or ['Intro', 'Drone', 'Dronecontroller', 'Room', 'Instant replay', 'Crash replays']
    web.run_app(FakeObs(scenes=scenes, current=scenes[0]).app(), host='127.0.0.1', port=port, print=None)
