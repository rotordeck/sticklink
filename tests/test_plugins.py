import asyncio
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from sticklink.pipeline import Pipeline
from sticklink.plugins import PluginError, PluginStore
from sticklink.recorder import Recorder
from sticklink.scenes import SceneStore
from sticklink.fxconfig import FxConfigStore
from sticklink.server import OverlayServer
from sticklink.sources.base import Source

MANIFEST = dict(name='My Viz', author='me', api=1)


class Idle(Source):
    label = 'test'

    async def run(self, pipeline):
        await asyncio.Event().wait()


def make_plugin(folder, manifest=MANIFEST, script='Sticklink.visualizer({draw(){}});', entry='main.js'):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'plugin.json').write_text(json.dumps(manifest))
    (folder/entry).write_text(script)
    return folder


def zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = PluginStore(self.dir/'user', self.dir/'builtin')

    def tearDown(self):
        self.tmp.cleanup()

    def test_discovery_lists_valid_and_broken_plugins_and_user_wins_over_builtin(self):
        make_plugin(self.dir/'builtin'/'a', dict(name='Built in A', api=1))
        make_plugin(self.dir/'user'/'a', dict(name='User A', api=1))
        make_plugin(self.dir/'user'/'b', dict(name='B', api=2))                    # needs a newer API
        (self.dir/'user'/'c').mkdir()                                              # no manifest
        make_plugin(self.dir/'user'/'Bad Name')                                    # not a valid id: ignored
        found = self.store.all()
        self.assertEqual(list(found), ['a', 'b', 'c'])
        self.assertEqual((found['a']['name'], found['a']['builtin'], found['a']['error']), ('User A', False, None))
        self.assertIn('API 2', found['b']['error'])
        self.assertIn('plugin.json is missing', found['c']['error'])
        self.assertTrue(all('root' not in item for item in self.store.listing()))

    def test_manifest_problems(self):
        for manifest, text in [(dict(api=1), 'name'), (dict(name='x', entry='../x.js'), 'entry'), (dict(name='x', entry='nope.js'), 'entry'),
                               (dict(name='x'*80), 'name'), (dict(name='x', entry='main.txt'), 'entry')]:
            make_plugin(self.dir/'user'/'p', manifest)
            self.assertIn(text, self.store.get('p')['error'], manifest)

    def test_install_folder_zip_and_single_js(self):
        src = make_plugin(self.dir/'src'/'thing', dict(name='Cool Thing', api=1))
        self.assertEqual(self.store.install(src), 'cool-thing')
        with self.assertRaises(PluginError) as ctx:
            self.store.install(src)
        self.assertIn('already installed', str(ctx.exception))
        self.assertEqual(self.store.install(src, replace=True), 'cool-thing')

        z = self.dir/'a.zip'
        z.write_bytes(zip_bytes({'plugin.json': json.dumps(dict(name='Zipped', api=1)), 'main.js': 'x', 'img/logo.png': 'p'}))
        self.assertEqual(self.store.install(z), 'zipped')
        self.assertTrue(self.store.file('zipped', 'img/logo.png'))

        z2 = self.dir/'b.zip'  # one top-level folder, as GitHub archives and most zip tools produce
        z2.write_bytes(zip_bytes({'inner/plugin.json': json.dumps(dict(name='Nested', api=1)), 'inner/main.js': 'x'}))
        self.assertEqual(self.store.install(z2), 'nested')

        js = self.dir/'my-cool_viz.js'
        js.write_text('Sticklink.visualizer({draw(){}})')
        self.assertEqual(self.store.install(js), 'my-cool_viz'.replace('_', '-'))
        self.assertEqual(self.store.get('my-cool-viz')['name'], 'My Cool Viz')
        self.assertEqual(sorted(self.store.all()), ['cool-thing', 'my-cool-viz', 'nested', 'zipped'])
        self.store.remove('nested')
        self.assertNotIn('nested', self.store.all())
        self.assertEqual(list(self.store.user_dir.glob('.install-*')), [])  # no staging leftovers

    def test_hostile_archives_are_refused(self):
        manifest = json.dumps(dict(name='Evil', api=1))
        cases = {
            'traversal': {'plugin.json': manifest, 'main.js': 'x', '../escape.js': 'x'},
            'absolute': {'plugin.json': manifest, 'main.js': 'x', '/etc/evil.js': 'x'},
            'executable': {'plugin.json': manifest, 'main.js': 'x', 'run.sh': 'x'},
            'dotfile': {'plugin.json': manifest, 'main.js': 'x', '.hidden.js': 'x'},
            'two folders': {'a/plugin.json': manifest, 'a/main.js': 'x', 'b/other.js': 'x'},
            'not a plugin': {'readme.txt': 'hello'},
        }
        for label, files in cases.items():
            z = self.dir/'evil.zip'
            z.write_bytes(zip_bytes(files))
            with self.assertRaises(PluginError, msg=label):
                self.store.install(z)
        self.assertFalse((self.dir/'escape.js').exists())
        self.assertEqual(self.store.all(), {})
        bad = self.dir/'bad.zip'
        bad.write_bytes(b'not a zip')
        with self.assertRaises(PluginError):
            self.store.install(bad)

    def test_symlinks_and_odd_sources_are_refused(self):
        src = make_plugin(self.dir/'src'/'linky', dict(name='Linky', api=1))
        (src/'secret.js').symlink_to('/etc/hostname')
        with self.assertRaises(PluginError):
            self.store.install(src)
        with self.assertRaises(PluginError):
            self.store.install(self.dir/'missing.txt')

    def test_file_lookup_stays_inside_the_plugin(self):
        make_plugin(self.dir/'user'/'p')
        (self.dir/'user'/'p'/'secret.txt').write_text('inside')
        (self.dir/'user'/'outside.js').write_text('outside')
        self.assertTrue(self.store.file('p', 'main.js'))
        for rel in ('../outside.js', '..\\outside.js', '/etc/passwd', 'sub/../../outside.js', 'nope.js', 'plugin.sh', '.x.js'):
            self.assertIsNone(self.store.file('p', rel), rel)
        self.assertIsNone(self.store.file('missing', 'main.js'))


class ServerTests(unittest.TestCase):
    def run_server(self, scenario):
        async def go():
            with tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                make_plugin(tmp/'user'/'mine', dict(name='Mine', api=1), script='/* mine */')
                make_plugin(tmp/'user'/'broken', dict(name='x', entry='gone.js'))
                (tmp/'user'/'mine'/'notes.sh').write_text('echo hi')
                (tmp/'user'/'secret.js').write_text('outside')
                pipe = Pipeline()
                server = OverlayServer(pipe, Idle(), fx_config=FxConfigStore(tmp/'fx.json'), recorder=Recorder(pipe, tmp/'rec', source='t'),
                                       scene_store=SceneStore(tmp/'scenes.json'), plugin_store=PluginStore(tmp/'user'))
                async with TestClient(TestServer(server.app())) as client:
                    await scenario(client)
        asyncio.run(go())

    def test_listing_pages_frame_and_files(self):
        async def scenario(client):
            data = await (await client.get('/api/v1/plugins')).json()
            ids = {p['id']: p for p in data['plugins']}
            self.assertTrue({'starfield', 'tunnel', 'scope', 'mine', 'broken'} <= set(ids))
            self.assertEqual((ids['mine']['builtin'], ids['mine']['url']), (False, '/viz/mine'))
            self.assertTrue(ids['broken']['error'])

            self.assertEqual((await client.get('/viz')).status, 200)
            self.assertEqual((await client.get('/viz/mine')).status, 200)
            self.assertEqual((await client.get('/viz/nope')).status, 404)

            frame = await client.get('/viz/mine/frame')
            self.assertEqual(frame.status, 200)
            csp = frame.headers['Content-Security-Policy']
            for needle in ("sandbox allow-scripts", "default-src 'none'", "connect-src 'none'", "script-src 'self'"):
                self.assertIn(needle, csp)
            body = await frame.text()
            self.assertIn('/assets/viz-runtime.js', body)
            self.assertIn('/viz/mine/file/main.js', body)
            self.assertEqual((await client.get('/viz/broken/frame')).status, 404)

            script = await client.get('/viz/mine/file/main.js')
            self.assertEqual((script.status, await script.text()), (200, '/* mine */'))
            for rel in ('notes.sh', 'missing.js', '%2e%2e/secret.js', '..%2fsecret.js'):
                self.assertEqual((await client.get(f'/viz/mine/file/{rel}')).status, 404, rel)
            self.assertEqual((await client.get('/viz/broken/file/plugin.json')).status, 404)
            # built-ins are served too
            self.assertEqual((await client.get('/viz/starfield/file/main.js')).status, 200)
            # still protected by the Host check like everything else
            self.assertEqual((await client.get('/viz/mine', headers={'Host': 'evil.example'})).status, 403)
        self.run_server(scenario)


if __name__ == '__main__':
    unittest.main()
