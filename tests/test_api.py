import asyncio
import copy
import json
from pathlib import Path
import re
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

try:
    import jsonschema
    from openapi_spec_validator import validate as validate_spec
except ImportError:  # dev extra not installed
    jsonschema = None

from sticklink.config import Config
from sticklink.fxconfig import DEFAULTS, STYLE_INFO, STYLES, FxConfigStore
from sticklink.openapi import build
from sticklink.pipeline import Pipeline
from sticklink.plugins import PluginStore
from sticklink.recorder import Recorder
from sticklink.scenes import SceneStore
from sticklink.server import OverlayServer
from sticklink.sources.base import Source

ROOT = Path(__file__).resolve().parent.parent
SPEC = build()


class IdleSource(Source):
    label = 'test'

    async def run(self, pipeline):
        await asyncio.Event().wait()


def resolve(schema):
    """Inline $refs and turn OpenAPI `nullable` into JSON Schema so jsonschema can check real responses."""
    if isinstance(schema, dict):
        if '$ref' in schema:
            return resolve(SPEC['components']['schemas'][schema['$ref'].rsplit('/', 1)[1]])
        out = {k: resolve(v) for k, v in schema.items() if k != 'nullable'}
        if schema.get('nullable'):
            out = {'anyOf': [out, {'type': 'null'}]}
        return out
    if isinstance(schema, list):
        return [resolve(v) for v in schema]
    return schema


def check_schema(testcase, body, op_path, method, status):
    spec = SPEC['paths'][op_path][method]['responses'][str(status)]
    schema = spec['content']['application/json']['schema']
    try:
        jsonschema.validate(body, resolve(schema))
    except jsonschema.ValidationError as exc:
        testcase.fail(f'{method.upper()} {op_path} -> {status} does not match its schema: {exc.message} at {list(exc.absolute_path)}')


class ApiCase(unittest.TestCase):
    def run_api(self, scenario, feed=True):
        async def go():
            with tempfile.TemporaryDirectory() as tmp:
                pipe = Pipeline(Config())
                server = OverlayServer(pipe, IdleSource(), fx_config=FxConfigStore(Path(tmp)/'fx.json'),
                                       recorder=Recorder(pipe, Path(tmp)/'rec', source='test'), scene_store=SceneStore(Path(tmp)/'scenes.json'), plugin_store=PluginStore(Path(tmp)/'plugins'))
                if feed:
                    pipe.connection(True)
                    pipe.accept('H,1,DDRAW,0')
                    pipe.accept('S,100,1,512,-512,0,-1024,1024,-1024')
                    pipe.accept('T,100,2,RQly,98,1,1')
                    pipe.accept('C,100,3,1,' + ','.join(str(v) for v in range(1, 9)))
                    pipe.accept('C,100,4,9,' + ','.join(str(v) for v in range(9, 17)))
                    pipe.accept('D,100,5,hello from the radio')
                async with TestClient(TestServer(server.app())) as client:
                    await scenario(client, server, Path(tmp))
        asyncio.run(go())

    async def call(self, client, method, path, spec_path=None, status=200, **kw):
        resp = await client.request(method, path, **kw)
        self.assertEqual(resp.status, status, await resp.text())
        body = await resp.json() if resp.content_type == 'application/json' else await resp.read()
        if spec_path and jsonschema and resp.content_type == 'application/json':
            check_schema(self, body, spec_path, method.lower(), status)
        return body


@unittest.skipUnless(jsonschema, 'pip install -e ".[dev]" for spec validation')
class ContractTests(ApiCase):
    def test_spec_is_valid_openapi(self):
        validate_spec(copy.deepcopy(SPEC))

    def test_every_route_is_documented_and_every_documented_route_exists(self):
        async def scenario(client, server, tmp):
            routed = set()
            for resource in server.app().router.resources():
                for route in resource:
                    path = resource.canonical
                    if path.startswith('/api/') and route.method not in ('HEAD', '*') and path != '/api/v1/openapi.json':
                        routed.add((route.method.lower(), path))
            documented = {(m, p) for p, ops in SPEC['paths'].items() for m in ops}
            self.assertEqual(routed - documented, set(), 'routes missing from the OpenAPI spec')
            self.assertEqual(documented - routed, set(), 'documented operations without a route')
        self.run_api(scenario)

    def test_get_responses_match_their_schemas_live_and_idle(self):
        paths = ['/api/v1/status', '/api/v1/state', '/api/v1/controls', '/api/v1/telemetry', '/api/v1/channels',
                 '/api/v1/styles', '/api/v1/settings', '/api/v1/settings/mapping', '/api/v1/recording',
                 '/api/v1/recordings', '/api/v1/plugins', '/api/state', '/api/fx-config']
        async def scenario(client, server, tmp):
            for path in paths:
                await self.call(client, 'GET', path, spec_path=path)
        self.run_api(scenario, feed=True)
        self.run_api(scenario, feed=False)  # nothing received yet: nulls must validate too

    def test_served_spec_equals_built_spec(self):
        async def scenario(client, server, tmp):
            self.assertEqual(await self.call(client, 'GET', '/api/v1/openapi.json'), SPEC)
        self.run_api(scenario)


class LiveDataTests(ApiCase):
    def test_live_endpoints(self):
        async def scenario(client, server, tmp):
            st = await self.call(client, 'GET', '/api/v1/status', '/api/v1/status')
            self.assertEqual((st['source'], st['radio']['status'], st['radio']['notes']), ('test', 'live', ['hello from the radio']))
            c = await self.call(client, 'GET', '/api/v1/controls', '/api/v1/controls')
            self.assertEqual((c['controls']['roll'], c['controls']['pitch'], c['raw']['roll']), (0.5, -0.5, 512))
            self.assertEqual(await self.call(client, 'GET', '/api/v1/channels'), dict(channels=list(range(1, 17))))
            self.assertEqual(await self.call(client, 'GET', '/api/v1/channels/9', '/api/v1/channels/{n}'), dict(channel=9, value=9))
            self.assertEqual((await self.call(client, 'GET', '/api/v1/telemetry/RQly', '/api/v1/telemetry/{sensor}'))['value'], 98)
            await self.call(client, 'GET', '/api/v1/telemetry/Nope', status=404)
            await self.call(client, 'GET', '/api/v1/telemetry/bad%20name', status=400)
            for n in ('0', '17', 'x', '-1'):
                err = await self.call(client, 'GET', f'/api/v1/channels/{n}', status=400)
                self.assertEqual(err['error']['code'], 'invalid_channel')
        self.run_api(scenario)

    def test_idle_radio_has_nulls_not_errors(self):
        async def scenario(client, server, tmp):
            c = await self.call(client, 'GET', '/api/v1/controls')
            self.assertEqual((c['controls'], c['raw'], c['status']), (None, None, 'disconnected'))
            self.assertEqual(await self.call(client, 'GET', '/api/v1/channels/3'), dict(channel=3, value=None))
        self.run_api(scenario, feed=False)


class SettingsTests(ApiCase):
    def test_defaults_patch_put_reset(self):
        async def scenario(client, server, tmp):
            self.assertEqual(await self.call(client, 'GET', '/api/v1/settings'), DEFAULTS)
            r = await self.call(client, 'PATCH', '/api/v1/settings', '/api/v1/settings', json=dict(style='hacker', mode=3, bogus=1))
            self.assertEqual((r['style'], r['mode'], r['chaos']), ('hacker', 3, 1.0))
            self.assertNotIn('bogus', r)
            # a partial mapping only changes the entries it names
            r = await self.call(client, 'PATCH', '/api/v1/settings', json=dict(mapping=dict(arm=dict(src='ch:8', thr=-512, dir=1))))
            self.assertEqual(r['mapping']['arm'], dict(src='ch:8', thr=-512, dir=1))
            self.assertEqual(r['mapping']['roll'], DEFAULTS['mapping']['roll'])
            r = await self.call(client, 'PATCH', '/api/v1/settings', json=dict(mapping=dict(flip=dict(src='ch:9', thr=0, dir=1))))
            self.assertEqual((r['mapping']['arm']['src'], r['mapping']['flip']['src']), ('ch:8', 'ch:9'), 'earlier mapping entries survive')
            # PUT needs everything
            err = await self.call(client, 'PUT', '/api/v1/settings', status=400, json=dict(style='neon'))
            self.assertIn('missing', err['error']['message'])
            full = copy.deepcopy(DEFAULTS); full['style'] = 'inferno'
            r = await self.call(client, 'PUT', '/api/v1/settings', '/api/v1/settings', json=full)
            self.assertEqual(r, full)
            r = await self.call(client, 'DELETE', '/api/v1/settings', '/api/v1/settings')
            self.assertEqual(r, DEFAULTS)
        self.run_api(scenario)

    def test_validation_errors(self):
        async def scenario(client, server, tmp):
            for bad in (dict(style='nope'), dict(chaos=5), dict(mode=7), dict(mapping=dict(roll=dict(src='ch:99')))):
                err = await self.call(client, 'PATCH', '/api/v1/settings', status=400, json=bad)
                self.assertEqual(err['error']['code'], 'invalid_settings')
            self.assertEqual(await self.call(client, 'GET', '/api/v1/settings'), DEFAULTS, 'bad requests change nothing')
            await self.call(client, 'PUT', '/api/v1/settings/mapping', status=400, json=dict(roll=dict(src='in:roll', rev=False)))
            m = copy.deepcopy(DEFAULTS['mapping']); m['yaw']['rev'] = True
            r = await self.call(client, 'PUT', '/api/v1/settings/mapping', '/api/v1/settings/mapping', json=m)
            self.assertEqual(r, m)
            self.assertEqual((await self.call(client, 'GET', '/api/v1/settings'))['mapping'], m)
        self.run_api(scenario)

    def test_styles_match_the_overlay(self):
        async def scenario(client, server, tmp):
            styles = await self.call(client, 'GET', '/api/v1/styles', '/api/v1/styles')
            self.assertEqual([s['id'] for s in styles], list(STYLES))
            ts = (ROOT/'fx/src/render/style.ts').read_text()
            self.assertEqual(re.findall(r"id: '(\w+)', name: '([^']+)'", ts), [(i, n) for i, n, _ in STYLE_INFO])
        self.run_api(scenario)

    def test_python_defaults_match_the_typescript_defaults(self):
        """Run the real TypeScript config module under Node and compare its DEFAULTS with the server's, key for key."""
        import json
        import shutil
        import subprocess
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        version = subprocess.run([node, '--version'], capture_output=True, text=True).stdout.strip().lstrip('v').split('.')
        if tuple(int(x) for x in version[:2]) < (22, 18):
            self.skipTest('Node 22.18+ is needed to run TypeScript directly')
        code = "import { DEFAULTS } from './fx/src/config.ts'; console.log(JSON.stringify(DEFAULTS));"
        run = subprocess.run([node, '--input-type=module', '-e', code], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), json.loads(json.dumps(DEFAULTS)))


class RecordingTests(ApiCase):
    def test_lifecycle_download_report_delete(self):
        async def scenario(client, server, tmp):
            self.assertEqual((await self.call(client, 'GET', '/api/v1/recording'))['active'], False)
            r = await self.call(client, 'POST', '/api/v1/recording', '/api/v1/recording', status=201, json=dict(label='first-flight'))
            self.assertTrue(r['active'] and r['name'].endswith('-first-flight.jsonl'))
            name = r['name']
            err = await self.call(client, 'POST', '/api/v1/recording', status=409, json={})
            self.assertEqual(err['error']['code'], 'already_recording')
            for k in range(5):
                server.pipeline.accept(f'S,{110+3*k},{10+k},{100*k},0,0,-1024,-1024,-1024')
            await self.call(client, 'DELETE', f'/api/v1/recordings/{name}', status=409)  # still active
            self.assertEqual((await self.call(client, 'GET', '/api/v1/recording'))['records'], 5)
            stopped = await self.call(client, 'DELETE', '/api/v1/recording', '/api/v1/recording')
            self.assertEqual((stopped['name'], stopped['records'], stopped['active']), (name, 5, False))
            self.assertEqual((await self.call(client, 'DELETE', '/api/v1/recording', status=409))['error']['code'], 'not_recording')
            listing = await self.call(client, 'GET', '/api/v1/recordings', '/api/v1/recordings')
            self.assertEqual([x['name'] for x in listing], [name])
            raw = await client.get(f'/api/v1/recordings/{name}')
            self.assertEqual((raw.status, raw.content_type), (200, 'application/x-ndjson'))
            lines = (await raw.text()).splitlines()
            self.assertEqual(json.loads(lines[0])['format'], 'sticklink-log')
            self.assertEqual(len(lines), 6)
            rep = await self.call(client, 'GET', f'/api/v1/recordings/{name}/report', '/api/v1/recordings/{name}/report')
            self.assertEqual(rep['counts']['samples'], 5)
            await self.call(client, 'DELETE', f'/api/v1/recordings/{name}', status=204)
            await self.call(client, 'GET', f'/api/v1/recordings/{name}', status=404)
            self.assertEqual(await self.call(client, 'GET', '/api/v1/recordings'), [])
        self.run_api(scenario)

    def test_clients_can_not_choose_paths(self):
        async def scenario(client, server, tmp):
            for label in ('../evil', '/etc/passwd', 'a b', 'x' * 41, ''):
                err = await self.call(client, 'POST', '/api/v1/recording', status=400, json=dict(label=label))
                self.assertEqual(err['error']['code'], 'invalid_label')
            await self.call(client, 'POST', '/api/v1/recording', status=400, json=dict(path='/tmp/x.jsonl'))
            await self.call(client, 'POST', '/api/v1/recording', status=400, json=dict(label=5))
            for name in ('..%2F..%2Fetc%2Fpasswd', 'notes.txt', '.hidden.jsonl', 'a%00.jsonl'):
                resp = await client.get(f'/api/v1/recordings/{name}')
                self.assertIn(resp.status, (400, 404), name)
                self.assertEqual((await resp.json())['error']['code'] in ('invalid_name', 'not_found'), True, name)
            self.assertFalse((tmp/'rec').exists() and any((tmp/'rec').iterdir()), 'nothing was written')
            self.assertEqual(list(tmp.glob('*.jsonl')), [])
        self.run_api(scenario)

    def test_post_without_body_starts_a_recording(self):
        async def scenario(client, server, tmp):
            err = await self.call(client, 'POST', '/api/v1/recording', status=415)  # no JSON content type: a cross-site form could send this
            self.assertEqual(err['error']['code'], 'unsupported_media_type')
            r = await self.call(client, 'POST', '/api/v1/recording', status=201, headers={'content-type': 'application/json'})
            self.assertRegex(r['name'], r'^\d{8}-\d{6}\.jsonl$')
            await self.call(client, 'DELETE', '/api/v1/recording')
        self.run_api(scenario)


class HardeningTests(ApiCase):
    def test_json_required_and_errors_are_json(self):
        async def scenario(client, server, tmp):
            for method, path in (('PATCH', '/api/v1/settings'), ('PUT', '/api/v1/settings'), ('PUT', '/api/v1/settings/mapping'), ('POST', '/api/fx-config')):
                err = await self.call(client, method, path, status=415, data='style=neon')
                self.assertEqual(err['error']['code'], 'unsupported_media_type')
                await self.call(client, method, path, status=400, data='{nope', headers={'content-type': 'application/json'})
                await self.call(client, method, path, status=400, data='[1]', headers={'content-type': 'application/json'})
            big = await client.patch('/api/v1/settings', data='{"style":"' + 'x'*70000 + '"}', headers={'content-type': 'application/json'})
            self.assertEqual(big.status, 413)
            nf = await self.call(client, 'GET', '/api/v1/nothing', status=404)
            self.assertEqual(nf['error']['code'], 'not_found')
            mm = await self.call(client, 'DELETE', '/api/v1/status', status=405)
            self.assertEqual(mm['error']['code'], 'method_not_allowed')
        self.run_api(scenario)

    def test_foreign_host_headers_are_refused(self):
        async def scenario(client, server, tmp):
            for host in ('evil.example', 'evil.example:8877', '192.168.1.5:8877', '127.0.0.1.evil.com'):
                resp = await client.get('/api/v1/state', headers={'Host': host})
                self.assertEqual(resp.status, 403, host)
                self.assertEqual((await resp.json())['error']['code'], 'forbidden_host')
                page = await client.get('/fx', headers={'Host': host})
                self.assertEqual(page.status, 403, host)
            for host in ('localhost:8877', '127.0.0.1:1234', '[::1]:8877', 'localhost'):
                resp = await client.get('/api/v1/state', headers={'Host': host})
                self.assertEqual(resp.status, 200, host)
        self.run_api(scenario)

    def test_docs_page_and_offline_assets(self):
        async def scenario(client, server, tmp):
            html = await (await client.get('/docs')).text()
            self.assertIn('/assets/swagger/swagger-ui-bundle.js', html)
            for asset in ('swagger-ui-bundle.js', 'swagger-ui.css', 'init.js', 'favicon-32x32.png', 'LICENSE'):
                self.assertEqual((await client.get(f'/assets/swagger/{asset}')).status, 200, asset)
            self.assertNotIn('http', re.sub(r'https?://github', '', html), 'docs must not load anything from the internet')
        self.run_api(scenario)


if __name__ == '__main__':
    unittest.main()
