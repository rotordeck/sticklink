import asyncio
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from sticklink.fxconfig import FxConfigStore
from sticklink.pipeline import Pipeline
from sticklink.recorder import Recorder
from sticklink.scenes import SceneStore
from sticklink.server import OverlayServer
from sticklink.sources.base import Source
from sticklink.themes import ThemeError, ThemeStore, clean_style

THEME = dict(name='Cool Thing', api=1, base='neon', style=dict(ring='#ff8800', glow=0.5))


class Idle(Source):
    label = 'test'

    async def run(self, pipeline):
        await asyncio.Event().wait()


def make_theme(folder, theme=THEME, fonts=()):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'theme.json').write_text(json.dumps(theme))
    for name in fonts:
        (folder/name).write_bytes(b'wOF2 fake font')
    return folder


def zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class StyleValidationTests(unittest.TestCase):
    def test_accepts_real_settings_and_the_shipped_examples(self):
        out = clean_style(dict(frame='brackets', ring='rainbow', plate=None, dot='rgba(1,2,3,0.5)', glow=1, grid=4, popups=True,
                               font="bold {px}px 'My Font', sans-serif", sparkColors=['#fff', 'gold'], labelMap={'WASTED': 'BOOM!'}))
        self.assertEqual(out['ring'], 'rainbow')
        store = ThemeStore(tempfile.mkdtemp())
        self.assertEqual([t['error'] for t in store.listing()], [None, None])

    def test_every_kind_of_mistake_is_named(self):
        bad = [dict(nope=1), dict(frame='triangle'), dict(ring='url(http://evil/x)'), dict(ring='javascript:1'), dict(plate=5), dict(dot=None),
               dict(glow=9), dict(glow='1'), dict(glow=True), dict(grid=2.5), dict(popups='yes'), dict(font='bold sans-serif'),
               dict(font='{px}px x; background:url(x)'), dict(sparkColors=[]), dict(sparkColors=['#fff']*9), dict(labelMap={'<b>': 'x'}),
               dict(labelMap={'A': 'x' * 50}), 'text']
        for style in bad:
            with self.assertRaises(ThemeError, msg=str(style)):
                clean_style(style)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = ThemeStore(self.dir/'user', self.dir/'shipped')

    def tearDown(self):
        self.tmp.cleanup()

    def test_discovery_user_wins_over_shipped_and_broken_ones_explain_themselves(self):
        make_theme(self.dir/'shipped'/'a', dict(name='Shipped A'))
        make_theme(self.dir/'user'/'a', dict(name='User A'))
        make_theme(self.dir/'user'/'b', dict(name='B', api=2))
        make_theme(self.dir/'user'/'c', dict(name='C', style=dict(glow=99)))
        make_theme(self.dir/'user'/'neon', dict(name='Fake neon'))                 # a built-in id
        make_theme(self.dir/'user'/'d', dict(name='D', base='nonsense'))
        make_theme(self.dir/'user'/'Bad Name')                                     # not an id: ignored
        (self.dir/'user'/'e').mkdir()
        (self.dir/'user'/'single.json').write_text(json.dumps(dict(name='Single')))
        found = self.store.all()
        self.assertEqual(sorted(found), ['a', 'b', 'c', 'd', 'e', 'neon', 'single'])
        self.assertEqual((found['a']['name'], found['a']['source'], found['a']['error']), ('User A', 'yours', None))
        self.assertEqual(found['single']['error'], None)
        self.assertIn('format 2', found['b']['error'])
        self.assertIn('glow', found['c']['error'])
        self.assertIn('built-in style', found['neon']['error'])
        self.assertIn('base', found['d']['error'])
        self.assertIn('theme.json is missing', found['e']['error'])
        listing = {t['id']: t for t in self.store.listing()}
        self.assertTrue(all('root' not in t for t in listing.values()))
        self.assertEqual(listing['c']['style'], {})

    def test_install_folder_zip_and_single_json_then_remove(self):
        src = make_theme(self.dir/'src'/'thing', THEME, fonts=['f.woff2'])
        theme = json.loads((src/'theme.json').read_text())
        theme['fonts'] = [dict(family='My Font', file='f.woff2')]
        (src/'theme.json').write_text(json.dumps(theme))
        self.assertEqual(self.store.install(src), 'cool-thing')
        with self.assertRaises(ThemeError) as ctx:
            self.store.install(src)
        self.assertIn('already installed', str(ctx.exception))
        self.assertEqual(self.store.install(src, replace=True), 'cool-thing')
        self.assertEqual(self.store.listing()[0]['fonts'], [dict(family='My Font', url='/themes/cool-thing/file/f.woff2')])
        self.assertTrue(self.store.font_file('cool-thing', 'f.woff2'))

        z = self.dir/'a.zip'
        z.write_bytes(zip_bytes({'theme.json': json.dumps(dict(name='Zipped'))}))
        self.assertEqual(self.store.install(z), 'zipped')
        z2 = self.dir/'b.zip'  # one top-level folder, as GitHub archives and most zip tools make
        z2.write_bytes(zip_bytes({'inner/theme.json': json.dumps(dict(name='Nested'))}))
        self.assertEqual(self.store.install(z2), 'nested')

        one = self.dir/'My_Theme.json'
        one.write_text(json.dumps(dict(name='Whatever', style=dict(dot='#0f0'))))
        self.assertEqual(self.store.install(one), 'my-theme')
        self.assertEqual(self.store.all()['my-theme']['style'], dict(dot='#0f0'))
        self.assertEqual(sorted(self.store.all()), ['cool-thing', 'my-theme', 'nested', 'zipped'])
        for theme_id in ('nested', 'my-theme'):
            self.store.remove(theme_id)
        self.assertEqual(sorted(self.store.all()), ['cool-thing', 'zipped'])
        self.assertEqual(list(self.store.user_dir.glob('.install-*')), [])  # no staging leftovers
        with self.assertRaises(ThemeError):
            self.store.remove('nested')

    def test_hostile_or_wrong_input_is_refused(self):
        ok = json.dumps(dict(name='Evil'))
        cases = {
            'traversal': {'theme.json': ok, '../escape.json': 'x'},
            'absolute': {'theme.json': ok, '/etc/evil.woff2': 'x'},
            'script': {'theme.json': ok, 'run.js': 'alert(1)'},
            'shell': {'theme.json': ok, 'run.sh': 'x'},
            'hidden font': {'theme.json': ok, '.x.woff2': 'x'},
            'two folders': {'a/theme.json': ok, 'b/other.woff2': 'x'},
            'not a theme': {'readme.txt': 'hello'},
            'bad style': {'theme.json': json.dumps(dict(name='x', style=dict(ring='url(//evil)')))},
            'missing font': {'theme.json': json.dumps(dict(name='x', fonts=[dict(family='F', file='f.woff2')]))},
        }
        for label, files in cases.items():
            z = self.dir/'evil.zip'
            z.write_bytes(zip_bytes(files))
            with self.assertRaises(ThemeError, msg=label):
                self.store.install(z)
        self.assertFalse((self.dir/'escape.json').exists())
        self.assertEqual(self.store.all(), {})
        bad = self.dir/'bad.zip'
        bad.write_bytes(b'not a zip')
        for source in (bad, self.dir/'missing.txt', self.dir/'x.txt'):
            with self.assertRaises(ThemeError):
                self.store.install(source)
        neon = self.dir/'neon.json'
        neon.write_text(ok)
        with self.assertRaises(ThemeError):
            self.store.install(neon)  # would shadow a built-in style

    def test_symlinks_and_scripts_in_a_folder_are_refused(self):
        src = make_theme(self.dir/'src'/'linky', dict(name='Linky'))
        (src/'secret.woff2').symlink_to('/etc/hostname')
        with self.assertRaises(ThemeError):
            self.store.install(src)
        (src/'secret.woff2').unlink()
        (src/'x.js').write_text('1')
        with self.assertRaises(ThemeError):
            self.store.install(src)

    def test_only_declared_font_files_of_working_themes_are_served(self):
        theme = dict(name='F', fonts=[dict(family='F', file='f.woff2')])
        make_theme(self.dir/'user'/'f', theme, fonts=['f.woff2', 'other.woff2'])
        (self.dir/'user'/'secret.woff2').write_bytes(b'outside')
        self.assertTrue(self.store.font_file('f', 'f.woff2'))
        for rel in ('other.woff2', 'theme.json', '../secret.woff2', '..\\secret.woff2', '/etc/passwd', 'nope.woff2'):
            self.assertIsNone(self.store.font_file('f', rel), rel)
        self.assertIsNone(self.store.font_file('missing', 'f.woff2'))


class ServerTests(unittest.TestCase):
    def test_api_styles_fonts_and_settings_choose_themes(self):
        async def go():
            with tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                make_theme(tmp/'user'/'mine', dict(name='Mine', fonts=[dict(family='Mine Font', file='m.woff2')]), fonts=['m.woff2'])
                make_theme(tmp/'user'/'broken', dict(name='x', style=dict(glow=99)))
                pipe = Pipeline()
                server = OverlayServer(pipe, Idle(), fx_config=FxConfigStore(tmp/'fx.json'), recorder=Recorder(pipe, tmp/'rec', source='t'),
                                       scene_store=SceneStore(tmp/'scenes.json'), theme_store=ThemeStore(tmp/'user'))
                async with TestClient(TestServer(server.app())) as client:
                    themes = {t['id']: t for t in (await (await client.get('/api/v1/themes')).json())['themes']}
                    self.assertTrue({'mine', 'broken', 'gold-rush', 'blueprint'} <= set(themes))
                    self.assertEqual(themes['mine']['fonts'][0]['url'], '/themes/mine/file/m.woff2')
                    self.assertTrue(themes['broken']['error'])
                    styles = [s['id'] for s in await (await client.get('/api/v1/styles')).json()]
                    self.assertIn('mine', styles)
                    self.assertNotIn('broken', styles)

                    font = await client.get('/themes/mine/file/m.woff2')
                    self.assertEqual((font.status, await font.read()), (200, b'wOF2 fake font'))
                    for path in ('/themes/mine/file/theme.json', '/themes/broken/file/m.woff2', '/themes/mine/file/..%2fsecret.woff2', '/themes/nope/file/m.woff2'):
                        self.assertEqual((await client.get(path)).status, 404, path)
                    self.assertEqual((await client.get('/themes/mine/file/m.woff2', headers={'Host': 'evil.example'})).status, 403)

                    patch = lambda body: client.patch('/api/v1/settings', json=body)
                    self.assertEqual((await patch(dict(style='mine'))).status, 200)
                    self.assertEqual((await patch(dict(hud=dict(style='gold-rush')))).status, 200)
                    self.assertEqual((await patch(dict(style='broken'))).status, 400)
                    self.assertEqual((await client.get('/api/v1/settings')).status, 200)
                # a theme that disappears later must not lose the saved settings
                self.assertEqual(FxConfigStore(tmp/'fx.json').load()['style'], 'mine')
                self.assertEqual(ThemeStore(tmp/'empty', tmp/'none').all(), {})
        asyncio.run(go())


if __name__ == '__main__':
    unittest.main()
