import asyncio
import os
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

from sticklink.fxconfig import FxConfigStore, validate
from sticklink.pipeline import Pipeline
from sticklink.scenes import SceneStore
from sticklink.server import OverlayServer
from sticklink.sources.base import Source


class IdleSource(Source):
    async def run(self, pipeline):
        await asyncio.Event().wait()


class ValidateTests(unittest.TestCase):
    def test_accepts_known_keys_and_orders_invert(self):
        self.assertEqual(validate(dict(style='neon', chaos=1.5, mode=4, delay=120.0,
            invert=['yaw', 'roll'], size=720)),
            dict(style='neon', chaos=1.5, mode=4, delay=120,
                 invert=['roll', 'yaw'], size=720))

    def test_mapping(self):
        ok = dict(roll=dict(src='ch:3', rev=True), arm=dict(src='ch:8', thr=-512, dir=1), flip=None)
        self.assertEqual(validate(dict(mapping=ok))['mapping'],
                         dict(roll=dict(src='ch:3', rev=True), arm=dict(src='ch:8', thr=-512, dir=1), flip=None))
        for bad in [dict(roll=dict(src='ch:17')), dict(roll=dict(src='x')), dict(roll=dict(src='ch:1', rev='y')),
                    dict(arm=dict(src='ch:5', thr=0, dir=2)), dict(arm=dict(src='ch:5', thr=99999, dir=1)),
                    dict(arm='ch:5'), []]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate(dict(mapping=bad))

    def test_rejects_bad_values_and_ignores_unknown_keys(self):
        for bad in [dict(style='No Such Style!'), dict(chaos=3), dict(chaos='1'), dict(chaos=True),
                    dict(mode=5), dict(delay=-1), dict(invert=['bogus']),
                    dict(size=10), dict(chaos=float('nan')), [], 'x']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate(bad)
        self.assertEqual(validate(dict(evil='<script>')), {})


class StoreAndApiTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, 'sub', 'fx.json')

    def tearDown(self):
        self.dir.cleanup()

    def test_save_merges_and_survives_garbage_file(self):
        store = FxConfigStore(self.path)
        self.assertEqual(store.load(), {})
        store.save(dict(style='arcade'))
        self.assertEqual(store.save(dict(chaos=0.5)), dict(style='arcade', chaos=0.5))
        with open(self.path, 'w') as f:
            f.write('{not json')
        self.assertEqual(store.load(), {})

    def test_http_endpoints(self):
        async def go():
            server = OverlayServer(Pipeline(), IdleSource(), fx_config=FxConfigStore(self.path), scene_store=SceneStore(os.path.join(self.dir.name, 'scenes.json')))
            async with TestClient(TestServer(server.app())) as c:
                self.assertEqual((await (await c.get('/api/fx-config')).json()), {})
                r = await c.post('/api/fx-config', json=dict(style='hacker', chaos=2))
                self.assertEqual(r.status, 200)
                self.assertEqual(await (await c.get('/api/fx-config')).json(),
                                 dict(style='hacker', chaos=2.0))
                self.assertEqual((await c.post('/api/fx-config', json=dict(style='x'))).status, 400)
                # form posts (what a hostile web page could send without CORS preflight) are refused
                self.assertEqual((await c.post('/api/fx-config', data='style=neon')).status, 415)
                self.assertEqual((await c.get('/fx')).status, 200)
                self.assertEqual((await c.get('/assets/stickfx.js')).status, 200)
                self.assertEqual((await c.get('/assets/fonts/bungee-latin-400-normal.woff2')).status, 200)
        asyncio.run(go())


if __name__ == '__main__':
    unittest.main()
