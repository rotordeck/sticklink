import asyncio
from contextlib import asynccontextmanager
import unittest

from aiohttp.test_utils import TestServer

try:
    from fake_obs import FakeObs
except ImportError:
    from tests.fake_obs import FakeObs

from sticklink import obs as obs_module
from sticklink.obs import ObsClient, ObsError, auth_string


async def until(predicate, timeout=5.0):
    end = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError('timed out waiting for the condition')
        await asyncio.sleep(0.01)


@asynccontextmanager
async def connected(fake, password='', **extra):
    server = TestServer(fake.app())
    await server.start_server()
    client = ObsClient()
    client.configure(dict(enabled=True, host='127.0.0.1', port=server.port, password=password, **extra))
    task = asyncio.ensure_future(client.run())
    try:
        yield client, server
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await server.close()


class ObsClientTests(unittest.TestCase):
    def setUp(self):
        self.old_retry = obs_module.RETRY_S
        obs_module.RETRY_S = 0.2

    def tearDown(self):
        obs_module.RETRY_S = self.old_retry

    def test_connects_lists_scenes_in_obs_order_and_reports_the_version(self):
        async def go():
            fake = FakeObs()
            async with connected(fake) as (client, _):
                await until(lambda: client.status == 'connected' and client.scenes)
                self.assertEqual(client.scenes, ['Intro', 'Drone', 'Room', 'Replay'])
                self.assertEqual((client.current, client.version['obsVersion']), ('Intro', '32.2.2'))
                self.assertEqual([r[0] for r in fake.requests], ['GetVersion', 'GetSceneList'])
        asyncio.run(go())

    def test_password_handshake(self):
        async def go():
            fake = FakeObs(password='hunter2')
            async with connected(fake, password='hunter2') as (client, _):
                await until(lambda: client.status == 'connected' and client.scenes)
        asyncio.run(go())

    def test_wrong_or_missing_password_stops_retrying_and_says_so(self):
        async def go():
            for given, expect in (('wrong', 'refused'), ('', 'asks for a password')):
                fake = FakeObs(password='hunter2')
                async with connected(fake, password=given) as (client, _):
                    await until(lambda: client.status == 'auth_failed')
                    self.assertIn(expect, client.error)
                    count = fake.connections
                    await asyncio.sleep(obs_module.RETRY_S * 4)
                    self.assertEqual(fake.connections, count, 'no retry loop with a password that cannot work')
        asyncio.run(go())

    def test_switching_scenes_and_following_obs_events(self):
        async def go():
            fake = FakeObs()
            async with connected(fake) as (client, _):
                await until(lambda: client.scenes)
                await client.set_scene('Drone')
                self.assertIn(('SetCurrentProgramScene', dict(sceneName='Drone')), fake.requests)
                await until(lambda: client.current == 'Drone')  # learned from OBS's own event
                with self.assertRaises(ObsError) as ctx:
                    await client.set_scene('Nope')
                self.assertEqual(ctx.exception.code, 600)
                self.assertIn('No scene', client.last_switch_error)
                await fake.add_scene('Credits')
                await until(lambda: 'Credits' in client.scenes)
        asyncio.run(go())

    def test_not_connected_requests_fail_cleanly(self):
        async def go():
            client = ObsClient()
            with self.assertRaises(ObsError):
                await client.set_scene('Drone')
        asyncio.run(go())

    def test_unreachable_then_reconnects_when_obs_appears(self):
        async def go():
            fake = FakeObs()
            server = TestServer(fake.app())
            await server.start_server()
            port = server.port
            await server.close()  # nothing listens now
            client = ObsClient()
            client.configure(dict(enabled=True, host='127.0.0.1', port=port, password=''))
            task = asyncio.ensure_future(client.run())
            try:
                await until(lambda: client.status == 'unreachable')
                self.assertIn('cannot reach OBS', client.error)
                server2 = TestServer(fake.app(), port=port)
                await server2.start_server()
                await until(lambda: client.status == 'connected' and client.scenes)
            finally:
                task.cancel()  # stop the client before its server, or the server waits for the open socket
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                await server2.close()
        asyncio.run(go())

    def test_reconnects_after_obs_drops_the_connection_and_counts_generations(self):
        async def go():
            fake = FakeObs()
            async with connected(fake) as (client, _):
                await until(lambda: client.scenes)
                first = client.generation
                for ws in fake.sockets:
                    await ws.close()
                await until(lambda: client.status != 'connected')
                await until(lambda: client.status == 'connected' and client.scenes)
                self.assertGreater(client.generation, first, 'a new connection is a new generation (the engine re-baselines)')
        asyncio.run(go())

    def test_disabling_disconnects_and_the_password_never_appears_in_the_snapshot(self):
        async def go():
            fake = FakeObs(password='hunter2')
            async with connected(fake, password='hunter2') as (client, server):
                await until(lambda: client.status == 'connected')
                snap = client.snapshot()
                self.assertTrue(snap['passwordSet'])
                self.assertNotIn('hunter2', repr(snap) + client.error)
                client.configure(dict(client.settings, enabled=False))
                await until(lambda: client.status == 'disabled')
                self.assertEqual((client.scenes, client.current), ([], None))
        asyncio.run(go())

    def test_auth_string_matches_the_protocol_definition(self):
        fake = FakeObs(password='supersecretpassword')
        self.assertEqual(auth_string('supersecretpassword', fake.salt, fake.challenge), fake.expected_auth())


if __name__ == '__main__':
    unittest.main()
