import asyncio
import os
import stat
import unittest

from aiohttp.test_utils import TestServer

try:
    from test_api import ApiCase
    from fake_obs import FakeObs
except ImportError:
    from tests.test_api import ApiCase
    from tests.fake_obs import FakeObs

from sticklink import obs as obs_module

MODES = dict(enabled=True, debounceMs=0, whenNone=dict(action='stay', scene=None), modes=[
    dict(scene='Drone', ranges=[dict(channel='ch:6', min=900, max=1300)]),
    dict(scene='Room', ranges=[dict(channel='ch:6', min=1300, max=1700)]),
    dict(scene='Replay', ranges=[dict(channel='ch:6', min=1700, max=2100)])])


def push(pipe, ch6_us, seq=[0]):
    """Two C records (channels 1-8, 9-16) as the radio sends them; channel 6 carries the switch."""
    raw = round((ch6_us - 1500) * 1024 / 500)
    low = [0, 0, -1024, 0, -1024, raw, -1024, -1024]
    seq[0] += 2
    pipe.accept(f'C,100,{seq[0] % 60000},1,' + ','.join(map(str, low)))
    pipe.accept(f'C,100,{seq[0] % 60000 + 1},9,' + ','.join(['0'] * 8))


class SceneApiTests(ApiCase):
    def setUp(self):
        self.old = obs_module.RETRY_S
        obs_module.RETRY_S = 0.2

    def tearDown(self):
        obs_module.RETRY_S = self.old

    async def until(self, predicate, timeout=5.0):
        end = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() > end:
                raise AssertionError('timed out')
            await asyncio.sleep(0.02)

    def with_fake(self, scenario, password=None):
        async def wrapped(client, server, tmp):
            server.pipeline.connection(True)  # a radio is attached (its channel records are pushed by the tests)
            fake = FakeObs(password=password)
            fake_server = TestServer(fake.app())
            await fake_server.start_server()
            try:
                await scenario(client, server, tmp, fake, fake_server)
            finally:
                await client.patch('/api/v1/obs/connection', json=dict(enabled=False))  # disconnect before the fake server stops
                await self.until(lambda: server.obs.status == 'disabled')
                await fake_server.close()
        self.run_api(wrapped, feed=False)

    def test_connect_list_scenes_and_never_expose_the_password(self):
        async def scenario(client, server, tmp, fake, fake_server):
            idle = await self.call(client, 'GET', '/api/v1/obs', '/api/v1/obs')
            self.assertEqual((idle['status'], idle['scenes'], idle['enabled']), ('disabled', [], False), 'off until the user turns it on')
            body = dict(enabled=True, host='127.0.0.1', port=fake_server.port, password='hunter2')
            r = await self.call(client, 'PATCH', '/api/v1/obs/connection', '/api/v1/obs/connection', json=body)
            self.assertTrue(r['passwordSet'])
            await self.until(lambda: server.obs.status == 'connected' and server.obs.scenes)
            st = await self.call(client, 'GET', '/api/v1/obs', '/api/v1/obs')
            self.assertEqual((st['status'], st['scenes'], st['currentScene']), ('connected', ['Intro', 'Drone', 'Room', 'Replay'], 'Intro'))
            self.assertEqual(st['version']['obsVersion'], '32.2.2')
            for text in (str(st), str(r), str(await self.call(client, 'GET', '/api/v1/scene-modes/state'))):
                self.assertNotIn('hunter2', text, 'the password is write-only')
            if os.name != 'nt':
                self.assertEqual(stat.S_IMODE(server.scene_store.path.stat().st_mode), 0o600)
            # a partial update keeps the stored password
            await self.call(client, 'PATCH', '/api/v1/obs/connection', json=dict(host='127.0.0.1'))
            self.assertEqual(server.scene_store.load()['obs']['password'], 'hunter2')
            for bad in (dict(host='http://x'), dict(port=0), dict(enabled='yes'), dict(nope=1)):
                err = await self.call(client, 'PATCH', '/api/v1/obs/connection', status=400, json=bad)
                self.assertEqual(err['error']['code'], 'invalid_obs_settings')
        self.with_fake(scenario, password='hunter2')

    def test_a_wrong_password_is_reported(self):
        async def scenario(client, server, tmp, fake, fake_server):
            await self.call(client, 'PATCH', '/api/v1/obs/connection', json=dict(enabled=True, host='127.0.0.1', port=fake_server.port, password='nope'))
            await self.until(lambda: server.obs.status == 'auth_failed')
            st = await self.call(client, 'GET', '/api/v1/obs', '/api/v1/obs')
            self.assertEqual(st['status'], 'auth_failed')
            self.assertNotIn('nope', st['error'])
        self.with_fake(scenario, password='hunter2')

    def test_scene_modes_validate_save_and_report_state(self):
        async def scenario(client, server, tmp, fake, fake_server):
            self.assertEqual((await self.call(client, 'GET', '/api/v1/scene-modes', '/api/v1/scene-modes'))['enabled'], False)
            for bad in (dict(modes=[dict(scene='A', ranges=[dict(channel='ch:5', min=1500, max=1000)])]), dict(debounceMs=99999), dict(whenNone=dict(action='x'))):
                err = await self.call(client, 'PUT', '/api/v1/scene-modes', status=400, json=bad)
                self.assertEqual(err['error']['code'], 'invalid_scene_modes')
            saved = await self.call(client, 'PUT', '/api/v1/scene-modes', '/api/v1/scene-modes', json=MODES)
            self.assertEqual(saved, MODES)
            self.assertEqual(server.scene_store.load()['modes'], MODES, 'persisted')
            st = await self.call(client, 'GET', '/api/v1/scene-modes/state', '/api/v1/scene-modes/state')
            self.assertEqual((st['enabled'], st['blocked']), (True, 'obs_not_connected'))
        self.with_fake(scenario)

    def test_the_radio_switches_the_scene_end_to_end(self):
        async def scenario(client, server, tmp, fake, fake_server):
            await self.call(client, 'PUT', '/api/v1/scene-modes', json=MODES)
            await self.call(client, 'PATCH', '/api/v1/obs/connection', json=dict(enabled=True, host='127.0.0.1', port=fake_server.port))
            await self.until(lambda: server.obs.status == 'connected' and server.obs.scenes)
            push(server.pipeline, 1000)
            async def feed(us):
                for _ in range(8):
                    push(server.pipeline, us)
                    await asyncio.sleep(0.05)
            await feed(1000)                         # switch in the first position: adopted, nothing happens
            self.assertEqual([r for r in fake.requests if r[0] == 'SetCurrentProgramScene'], [])
            st = await self.call(client, 'GET', '/api/v1/scene-modes/state', '/api/v1/scene-modes/state')
            self.assertEqual((st['blocked'], st['active'], st['channels']['ch:6']), (None, ['Drone'], 1000))
            await feed(1500)
            await self.until(lambda: fake.current == 'Room')
            await feed(2000)
            await self.until(lambda: fake.current == 'Replay')
            self.assertEqual([r[1]['sceneName'] for r in fake.requests if r[0] == 'SetCurrentProgramScene'], ['Room', 'Replay'])
            st = await self.call(client, 'GET', '/api/v1/scene-modes/state', '/api/v1/scene-modes/state')
            self.assertEqual([e['scene'] for e in st['recent']], ['Room', 'Replay'])
            self.assertTrue(all(e['ok'] and e['reason'] == 'radio' for e in st['recent']))
            # the radio goes quiet: no more switching
            await asyncio.sleep(1.4)
            st = await self.call(client, 'GET', '/api/v1/scene-modes/state')
            self.assertEqual(st['blocked'], 'no_radio_data')
        self.with_fake(scenario)

    def test_manual_switch_and_apply_now(self):
        async def scenario(client, server, tmp, fake, fake_server):
            err = await self.call(client, 'POST', '/api/v1/obs/scene', status=409, json=dict(scene='Drone'))
            self.assertEqual(err['error']['code'], 'obs_not_connected')
            await self.call(client, 'PUT', '/api/v1/scene-modes', json=MODES)
            await self.call(client, 'PATCH', '/api/v1/obs/connection', json=dict(enabled=True, host='127.0.0.1', port=fake_server.port))
            await self.until(lambda: server.obs.status == 'connected' and server.obs.scenes)
            ok = await self.call(client, 'POST', '/api/v1/obs/scene', '/api/v1/obs/scene', json=dict(scene='Drone'))
            self.assertEqual(ok, dict(scene='Drone'))
            self.assertEqual(fake.current, 'Drone')
            err = await self.call(client, 'POST', '/api/v1/obs/scene', status=400, json=dict(scene='Nope'))
            self.assertEqual(err['error']['code'], 'scene_not_found')
            for bad in (dict(), dict(scene=''), dict(scene='A', extra=1), dict(scene=5)):
                await self.call(client, 'POST', '/api/v1/obs/scene', status=400, json=bad)
            err = await self.call(client, 'POST', '/api/v1/scene-modes/apply', status=409, json={})
            self.assertEqual(err['error']['code'], 'nothing_to_apply')
            for _ in range(6):
                push(server.pipeline, 2000); await asyncio.sleep(0.05)
            applied = await self.call(client, 'POST', '/api/v1/scene-modes/apply', '/api/v1/scene-modes/apply', json={})
            self.assertEqual(applied, dict(scene='Replay'))
            await self.until(lambda: fake.current == 'Replay')
        self.with_fake(scenario)

    def test_post_actions_need_the_json_content_type_so_a_web_page_cannot_trigger_them(self):
        async def scenario(client, server, tmp, fake, fake_server):
            for path, data in (('/api/v1/obs/scene', 'scene=Drone'), ('/api/v1/scene-modes/apply', ''), ('/api/v1/recording', ''), ('/api/v1/obs/connection', 'enabled=true')):
                method = 'PATCH' if path.endswith('connection') else 'POST'
                resp = await client.request(method, path, data=data, headers={'content-type': 'application/x-www-form-urlencoded'})
                self.assertEqual(resp.status, 415, f'{method} {path}')
                resp = await client.request(method, path, data=data)  # no content type at all
                self.assertEqual(resp.status, 415, f'{method} {path} without a content type')
            self.assertEqual(fake.requests, [], 'nothing reached OBS')
        self.with_fake(scenario)

    def test_the_modes_page_is_served(self):
        async def scenario(client, server, tmp, fake, fake_server):
            self.assertEqual((await client.get('/modes')).status, 200)
        self.with_fake(scenario)


if __name__ == '__main__':
    unittest.main()
