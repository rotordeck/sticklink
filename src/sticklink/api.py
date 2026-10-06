"""REST API handlers (see openapi.py for the contract; /docs for Swagger UI)."""
import json
import re
import time

from aiohttp import web

from . import __version__
from .analysis import analyze
from .fxconfig import STYLE_INFO, validate
from .openapi import build
from .obs import ObsError
from .recorder import RecorderError
from .scenes import validate_modes, validate_obs

SENSOR = re.compile(r'[A-Za-z0-9_%-]{1,24}')
LOCAL_HOSTS = {'localhost', '127.0.0.1', '[::1]'}
STATUS_FOR = dict(already_recording=409, not_recording=409, recording_active=409, invalid_label=400,
                  invalid_name=400, not_found=404)


def error(status, code, message):
    return web.json_response(dict(error=dict(code=code, message=message)), status=status)


@web.middleware
async def guard(request, handler):
    """Reject foreign Host headers (DNS rebinding) and give API errors a JSON body."""
    host = request.host.rsplit(':', 1)[0] if not request.host.endswith(']') else request.host
    if host not in LOCAL_HOSTS:
        return error(403, 'forbidden_host', 'this server only answers to localhost')
    try:
        return await handler(request)
    except web.HTTPException as exc:
        if request.path.startswith('/api/') and not exc.empty_body:
            reason = exc.reason.lower().replace(' ', '_')
            return error(exc.status, reason, exc.text if exc.text and exc.text != f'{exc.status}: {exc.reason}' else exc.reason)
        raise


async def json_body(request, allow_empty=False):
    # Always demand the JSON content type, even for an empty body: a cross-site HTML form cannot send it without a
    # CORS pre-flight that this server never answers, so a web page you visit cannot trigger POST actions.
    if request.content_type != 'application/json':
        raise web.HTTPUnsupportedMediaType(text='send Content-Type: application/json')
    if allow_empty and not request.can_read_body:
        return {}
    try:
        data = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text='body is not valid JSON')
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text='body must be a JSON object')
    return data


def register(app, server):
    pipe, fx, rec = server.pipeline, server.fx_config, server.recorder
    started = time.monotonic()
    snap = pipe.snapshot
    ok = web.json_response

    async def status(request):
        s = snap()
        st = pipe.state
        return ok(dict(version=__version__, uptime_s=round(time.monotonic()-started, 1), source=server.source.label,
                       radio=dict(status=s['status'], connected=st.connected, session=s['session'], age_ms=s['age_ms'],
                                  error=s['error'], input=s['source'], notes=s['notes']),
                       diagnostics=s['diagnostics'], websocket_clients=len(server.clients), recording=rec.status()))

    async def state(request):
        return ok(snap())

    async def controls(request):
        s = snap()
        return ok({k: s[k] for k in ('status', 'source', 'controls', 'raw', 'commands', 'age_ms', 'tick', 'seq')})

    async def telemetry(request):
        return ok(dict(sensors=snap()['telemetry']))

    async def sensor(request):
        name = request.match_info['sensor']
        if not SENSOR.fullmatch(name):
            return error(400, 'invalid_sensor', 'sensor names are 1-24 characters of A-Z a-z 0-9 _ % -')
        item = snap()['telemetry'].get(name)
        if item is None:
            return error(404, 'not_found', f'no sensor named {name}')
        return ok(dict(name=name, **item))

    async def gps(request):
        return ok(snap()['gps'])

    def track_body():
        st = pipe.state
        return dict(home=None if st.home is None else dict(lat=st.home[0], lon=st.home[1]),
                    points=[[round(a, 6), round(b, 6)] for a, b in st.track])

    async def gps_track(request):
        return ok(track_body())

    async def gps_track_clear(request):
        pipe.state.reset_gps()
        return ok(track_body())

    async def race_reset(request):
        pipe.state.race.reset()
        return ok(pipe.state.race.snapshot())

    # ------------------------------------------------------------ OBS scenes
    obs, engine, scene_store = server.obs, server.scenes, server.scene_store

    async def obs_status(request):
        return ok(obs.snapshot())

    async def obs_connection(request):
        data = await json_body(request)
        try:
            settings = scene_store.save_obs(data)
        except ValueError as exc:
            return error(400, 'invalid_obs_settings', str(exc))
        obs.configure(settings)
        return ok(obs.snapshot())

    async def obs_scene(request):
        data = await json_body(request)
        scene = data.get('scene')
        if not isinstance(scene, str) or not scene or set(data) != {'scene'}:
            return error(400, 'invalid_scene', 'send {"scene": "<name>"}')
        try:
            await obs.set_scene(scene)
        except ObsError as exc:
            if obs.status != 'connected':
                return error(409, 'obs_not_connected', str(exc))
            return error(400, 'scene_not_found' if exc.code == 600 else 'obs_error', str(exc))
        return ok(dict(scene=scene))

    async def modes(request):
        return ok(engine.config)

    async def modes_put(request):
        data = await json_body(request)
        try:
            cfg = scene_store.save_modes(validate_modes(data))
        except ValueError as exc:
            return error(400, 'invalid_scene_modes', str(exc))
        engine.configure(cfg)
        return ok(cfg)

    async def modes_state(request):
        return ok(dict(engine.status(), obs=obs.status))

    async def modes_apply(request):
        await json_body(request, allow_empty=True)
        if engine.blocked == 'obs_not_connected' or obs.status != 'connected':
            return error(409, 'obs_not_connected', 'OBS is not connected')
        try:
            scene = engine.apply_now()
        except ValueError as exc:
            return error(409, 'nothing_to_apply', str(exc))
        return ok(dict(scene=scene))

    async def channels(request):
        return ok(dict(channels=snap()['channels']))

    async def channel(request):
        try:
            n = int(request.match_info['n'])
        except ValueError:
            n = 0
        if not 1 <= n <= 16:
            return error(400, 'invalid_channel', 'channel must be a number from 1 to 16')
        values = snap()['channels']
        return ok(dict(channel=n, value=None if values is None else values[n-1]))

    async def styles(request):
        return ok([dict(id=i, name=n, blurb=b, builtin=True) for i, n, b in STYLE_INFO]
                  + [dict(id=t['id'], name=t['name'], blurb=t['description'], builtin=False) for t in server.themes.listing() if not t['error']])

    async def settings(request):
        return ok(fx.merged())

    def check_styles(data):
        """Writes may only choose a built-in style or an installed, working theme (stored settings stay lenient: a removed theme must not lose them)."""
        known = {s[0] for s in STYLE_INFO} | {t['id'] for t in server.themes.listing() if not t['error']}
        hud = data.get('hud') if isinstance(data.get('hud'), dict) else {}
        for value in (data.get('style'), hud.get('style')):
            if isinstance(value, str) and value not in known:
                raise ValueError(f'unknown style "{value}" (see GET /api/v1/styles)')

    def settings_write(action):
        async def handler(request):
            data = await json_body(request)
            try:
                check_styles(data)
                action(data)
            except ValueError as exc:
                return error(400, 'invalid_settings', str(exc))
            return ok(fx.merged())
        return handler

    async def settings_reset(request):
        fx.reset()
        return ok(fx.merged())

    async def mapping(request):
        return ok(fx.merged()['mapping'])

    async def mapping_put(request):
        data = await json_body(request)
        try:
            fx.replace_mapping(data)
        except ValueError as exc:
            return error(400, 'invalid_mapping', str(exc))
        return ok(fx.merged()['mapping'])

    def recorder_call(fn, status_ok=200):
        async def handler(request):
            try:
                return await fn(request, status_ok)
            except RecorderError as exc:
                return error(STATUS_FOR.get(exc.code, 400), exc.code, exc.message)
        return handler

    async def recording(request, _):
        return ok(rec.status())

    async def recording_start(request, code):
        body = await json_body(request, allow_empty=True)
        unknown = set(body) - {'label'}
        if unknown:
            raise RecorderError('invalid_label', 'unknown field: ' + ', '.join(sorted(unknown)))
        label = body.get('label')
        if label is not None and not isinstance(label, str):
            raise RecorderError('invalid_label', 'label must be a string')
        return ok(rec.start(label), status=code)

    async def recording_stop(request, _):
        return ok(rec.stop())

    async def recordings(request, _):
        return ok(rec.list())

    async def recording_file(request, _):
        path = rec.path_for(request.match_info['name'])
        return web.FileResponse(path, headers={'Content-Type': 'application/x-ndjson',
                                               'Content-Disposition': f'attachment; filename="{path.name}"'})

    async def recording_delete(request, _):
        rec.delete(request.match_info['name'])
        return web.Response(status=204)

    async def recording_report(request, _):
        report = analyze(rec.path_for(request.match_info['name']))
        return web.Response(text=json.dumps(report, allow_nan=False), content_type='application/json')

    async def themes(request):
        return ok(dict(themes=server.themes.listing()))

    spec_json = json.dumps(build())

    async def openapi(request):
        return web.Response(text=spec_json, content_type='application/json')

    v1 = '/api/v1'
    routes = [
        ('GET', '/status', status), ('GET', '/state', state), ('GET', '/controls', controls),
        ('GET', '/telemetry', telemetry), ('GET', '/telemetry/{sensor}', sensor),
        ('GET', '/gps', gps), ('GET', '/gps/track', gps_track), ('DELETE', '/gps/track', gps_track_clear),
        ('POST', '/race/reset', race_reset),
        ('GET', '/obs', obs_status), ('PATCH', '/obs/connection', obs_connection), ('POST', '/obs/scene', obs_scene),
        ('GET', '/scene-modes', modes), ('PUT', '/scene-modes', modes_put), ('GET', '/scene-modes/state', modes_state),
        ('POST', '/scene-modes/apply', modes_apply),
        ('GET', '/themes', themes),
        ('GET', '/channels', channels), ('GET', '/channels/{n}', channel), ('GET', '/styles', styles),
        ('GET', '/settings', settings),
        ('PUT', '/settings', settings_write(fx.replace)), ('PATCH', '/settings', settings_write(fx.save)),
        ('DELETE', '/settings', settings_reset),
        ('GET', '/settings/mapping', mapping), ('PUT', '/settings/mapping', mapping_put),
        ('GET', '/recording', recorder_call(recording)), ('POST', '/recording', recorder_call(recording_start, 201)),
        ('DELETE', '/recording', recorder_call(recording_stop)),
        ('GET', '/recordings', recorder_call(recordings)),
        ('GET', '/recordings/{name}', recorder_call(recording_file)),
        ('DELETE', '/recordings/{name}', recorder_call(recording_delete)),
        ('GET', '/recordings/{name}/report', recorder_call(recording_report)),
        ('GET', '/openapi.json', openapi),
    ]
    for method, path, handler in routes:
        app.router.add_route(method, v1 + path, handler)

    # Legacy aliases used by the bundled pages.
    async def legacy_get(request):
        return ok(fx.load(), headers={'Cache-Control': 'no-store'})

    async def legacy_post(request):
        data = await json_body(request)
        try:
            check_styles(data)
            return ok(fx.save(data))
        except ValueError as exc:
            return error(400, 'invalid_settings', str(exc))

    app.router.add_get('/api/state', state)
    app.router.add_get('/api/fx-config', legacy_get)
    app.router.add_post('/api/fx-config', legacy_post)
