"""OpenAPI 3.0 description of the REST API (served at /api/v1/openapi.json, browsable at /docs)."""
from . import __version__
from .fxconfig import DEFAULTS, STYLES

CHANNEL = dict(type='integer', minimum=-2048, maximum=2048, description='Raw channel value, normally -1024..1024')
SRC = dict(type='string', pattern=r'^(in:(roll|pitch|yaw|throttle|arm|crash)|ch:([1-9]|1[0-6]))$',
           description="`in:roll|pitch|yaw|throttle|arm|crash` = the radio's stick/command inputs, `ch:1`..`ch:16` = mixer output channels",
           example='ch:8')


def ref(name):
    return {'$ref': f'#/components/schemas/{name}'}


def obj(properties, required=None, **extra):
    out = dict(type='object', properties=properties, additionalProperties=False)
    if required is not False:
        out['required'] = list(properties) if required is None else required
    out.update(extra)
    return out


def nullable(schema):
    if '$ref' in schema:  # siblings of $ref are ignored in OpenAPI 3.0, so wrap it
        return {'nullable': True, 'allOf': [schema]}
    return {**schema, 'nullable': True}


SCHEMAS = {
    'Error': obj(dict(error=obj(dict(code=dict(type='string', example='invalid_json'),
                                      message=dict(type='string'))))),
    'Controls': obj(dict(roll=dict(type='number'), pitch=dict(type='number'), yaw=dict(type='number'),
                         throttle=dict(type='number')),
                    description='Sticks normalised to -1..1 (positive = right / up)'),
    'RawInputs': obj(dict(roll=CHANNEL, pitch=CHANNEL, yaw=CHANNEL, throttle=CHANNEL, arm=CHANNEL, crash=CHANNEL),
                     description="The radio's six reported inputs (the Lua script's `S` record)"),
    'Commands': obj(dict(arm=nullable(dict(type='boolean')), crash=nullable(dict(type='boolean'))),
                    description='Switch states from the radio defaults (ch5 and ch8). `null` while data is not live.'),
    'Sensor': obj(dict(value=dict(type='number'), current=dict(type='boolean', description='Seen recently and valid'),
                       fresh=dict(type='boolean', description='Updated within the last 300 ms'),
                       age_ms=dict(type='integer'))),
    'Diagnostics': obj(dict(invalid=dict(type='integer'), missing=dict(type='integer', description='Lost records (sequence gaps)'),
                            resets=dict(type='integer'), samples=dict(type='integer'))),
    'State': obj(dict(
        schema=dict(type='integer', example=1), session=dict(type='integer', description='Increments on every radio restart/reconnect'),
        status=dict(type='string', enum=['live', 'demo', 'paused', 'disconnected']),
        source=dict(type='string', description='What the control values represent: sticks, outputs or unknown'),
        controls=nullable(ref('Controls')), raw=nullable(ref('RawInputs')),
        channels=nullable(dict(type='array', items=CHANNEL, minItems=16, maxItems=16,
                               description='Mixer outputs CH1..CH16; `null` until the radio script reports them')),
        notes=dict(type='array', items=dict(type='string'), description='Diagnostics sent by the radio script (newest last)'),
        commands=ref('Commands'), telemetry=dict(type='object', additionalProperties=ref('Sensor')),
        tick=nullable(dict(type='integer', description='Radio clock, 10 ms ticks')),
        seq=nullable(dict(type='integer')), age_ms=nullable(dict(type='integer', description='Age of the newest control sample')),
        error=dict(type='string'), diagnostics=ref('Diagnostics'),
    ), description='The snapshot also broadcast on the WebSocket at 30 Hz'),
    'Status': obj(dict(
        version=dict(type='string', example=__version__), uptime_s=dict(type='number'),
        source=dict(type='string', example='serial:/dev/ttyACM0'),
        radio=obj(dict(status=dict(type='string', enum=['live', 'demo', 'paused', 'disconnected']),
                       connected=dict(type='boolean'), session=dict(type='integer'),
                       age_ms=nullable(dict(type='integer')), error=dict(type='string'),
                       input=dict(type='string'), notes=dict(type='array', items=dict(type='string')))),
        diagnostics=ref('Diagnostics'), websocket_clients=dict(type='integer'), recording=ref('Recording'),
    )),
    'AxisMap': obj(dict(src=SRC, rev=dict(type='boolean', description='Invert the axis')), description='Which input drives a stick axis'),
    'SwitchMap': obj(dict(src=SRC, thr=dict(type='integer', minimum=-2048, maximum=2048,
                                            description='Threshold between the two switch positions'),
                          dir=dict(type='integer', enum=[1, -1], description='1 = active above `thr`, -1 = active below')),
                     description='Which input is a switch, and when it counts as on'),
    'Mapping': obj(dict(roll=ref('AxisMap'), pitch=ref('AxisMap'), yaw=ref('AxisMap'), throttle=ref('AxisMap'),
                        arm=nullable(ref('SwitchMap')), flip=nullable(ref('SwitchMap')))),
    'PartialMapping': obj(dict(roll=ref('AxisMap'), pitch=ref('AxisMap'), yaw=ref('AxisMap'), throttle=ref('AxisMap'),
                               arm=nullable(ref('SwitchMap')), flip=nullable(ref('SwitchMap'))), required=False,
                          description='Only the entries named are changed'),
    'Settings': obj(dict(
        style=dict(type='string', enum=list(STYLES), default=DEFAULTS['style']),
        chaos=dict(type='number', minimum=0, maximum=2, default=DEFAULTS['chaos'], description='Effect strength'),
        mode=dict(type='integer', enum=[1, 2, 3, 4], default=DEFAULTS['mode'],
                  description='Stick layout. 1: L yaw/pitch R roll/thr. 2: L yaw/thr R roll/pitch. 3: L roll/pitch R yaw/thr. 4: L roll/thr R yaw/pitch'),
        delay=dict(type='integer', minimum=0, maximum=5000, default=DEFAULTS['delay'], description='Extra overlay delay in ms, to match video'),
        invert=dict(type='array', items=dict(type='string', enum=['roll', 'pitch', 'yaw', 'throttle']), uniqueItems=True),
        size=dict(type='integer', minimum=240, maximum=2160, default=DEFAULTS['size'], description='Reference size in px (sets the OBS source size)'),
        mapping=ref('Mapping'))),
    'PartialSettings': obj(dict(
        style=dict(type='string', enum=list(STYLES)), chaos=dict(type='number', minimum=0, maximum=2),
        mode=dict(type='integer', enum=[1, 2, 3, 4]), delay=dict(type='integer', minimum=0, maximum=5000),
        invert=dict(type='array', items=dict(type='string', enum=['roll', 'pitch', 'yaw', 'throttle'])),
        size=dict(type='integer', minimum=240, maximum=2160), mapping=ref('PartialMapping')), required=False),
    'Style': obj(dict(id=dict(type='string', enum=list(STYLES)), name=dict(type='string'), blurb=dict(type='string'))),
    'Recording': obj(dict(active=dict(type='boolean'), name=nullable(dict(type='string', example='20261006-143000-test.jsonl')),
                          records=dict(type='integer'), started_unix=nullable(dict(type='number')),
                          external=dict(type='boolean', description='Started with `--log FILE` on the command line')),
                     description='The recording currently being written'),
    'RecordingStart': obj(dict(label=dict(type='string', pattern='^[A-Za-z0-9_-]{1,40}$', example='first-flight')), required=False),
    'RecordingInfo': obj(dict(name=dict(type='string'), size_bytes=dict(type='integer'),
                              modified_unix=dict(type='number'), active=dict(type='boolean'))),
    'Gaps': obj(dict(median=nullable(dict(type='number')), p95=nullable(dict(type='number')),
                     p99=nullable(dict(type='number')), max=nullable(dict(type='number')))),
    'Report': obj(dict(
        path=dict(type='string'), duration_s=dict(type='number'),
        counts=dict(type='object', additionalProperties=dict(type='integer')),
        sample_rate_hz=nullable(dict(type='number')), radio_gap_ms=ref('Gaps'), host_gap_ms=ref('Gaps'),
        missing_seq=dict(type='integer'), resets=dict(type='integer'), sessions=dict(type='integer'),
        stick_range=dict(type='object', additionalProperties=dict(type='array', items=dict(type='integer'), minItems=2, maxItems=2)),
        output_ranges=dict(type='object', description='Per output channel number: [min, max]',
                           additionalProperties=dict(type='array', items=dict(type='integer'), minItems=2, maxItems=2)),
        telemetry=dict(type='object', additionalProperties=dict(type='object')),
        radio_notes=dict(type='array', items=dict(type='string')),
        warnings=dict(type='array', items=dict(type='string'))),
        description='Quality report of a recording, like `sticklink check-log`'),
}


def _err(description):
    return {'description': description, 'content': {'application/json': {'schema': ref('Error')}}}


def _ok(schema, description='OK'):
    return {'description': description, 'content': {'application/json': {'schema': schema}}}


def _json_body(schema, required=True):
    return {'required': required, 'content': {'application/json': {'schema': schema}}}


E400, E404, E409, E415 = (_err('Invalid request'), _err('Not found'), _err('Conflict with the current state'),
                          _err('Request body must be application/json'))
SENSOR_PARAM = dict(name='sensor', **{'in': 'path'}, required=True, schema=dict(type='string', pattern='^[A-Za-z0-9_-]{1,24}$'),
                    description='Sensor name as sent by the radio, e.g. `RQly`, `RxBt`')
CHANNEL_PARAM = dict(name='n', **{'in': 'path'}, required=True, schema=dict(type='integer', minimum=1, maximum=16),
                     description='Channel number 1-16')
NAME_PARAM = dict(name='name', **{'in': 'path'}, required=True, schema=dict(type='string', pattern='^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\\.jsonl$'),
                  description='Recording file name from `GET /recordings`')


def build():
    return {
        'openapi': '3.0.3',
        'info': {
            'title': 'Sticklink API', 'version': __version__,
            'description': (
                'Live stick, switch and telemetry data from an EdgeTX radio, overlay settings, and session recordings.\n\n'
                '**Live stream:** connect a WebSocket to `/ws` (not describable in OpenAPI). The server pushes the `State` '
                'object as JSON text about 30 times per second and ignores anything you send.\n\n'
                '**Security:** the server only listens on `127.0.0.1` and has no authentication. Requests whose `Host` header is '
                'not `localhost`, `127.0.0.1` or `[::1]` are rejected (DNS-rebinding protection), and every request that changes '
                'something must be `Content-Type: application/json`. Recording files are only ever created in the recordings '
                'folder under server-chosen names.\n\n'
                '**Errors** are always `{"error": {"code": "...", "message": "..."}}`.'),
        },
        'servers': [{'url': '/'}],
        'tags': [{'name': 'Live', 'description': 'Radio data, now'}, {'name': 'Settings', 'description': 'Overlay settings and stick mapping'},
                 {'name': 'Recording', 'description': 'Session logs'}, {'name': 'Legacy', 'description': 'Kept for the bundled pages'}],
        'paths': {
            '/api/v1/status': {'get': {
                'tags': ['Live'], 'operationId': 'getStatus', 'summary': 'Service and radio status',
                'responses': {'200': _ok(ref('Status'))}}},
            '/api/v1/state': {'get': {
                'tags': ['Live'], 'operationId': 'getState', 'summary': 'Everything in one snapshot',
                'responses': {'200': _ok(ref('State'))}}},
            '/api/v1/controls': {'get': {
                'tags': ['Live'], 'operationId': 'getControls', 'summary': 'Sticks and switches',
                'description': '`controls` and `raw` are `null` unless the radio data is live (a sample within the last 500 ms).',
                'responses': {'200': _ok(obj(dict(status=dict(type='string', enum=['live', 'demo', 'paused', 'disconnected']),
                                                   source=dict(type='string'), controls=nullable(ref('Controls')),
                                                   raw=nullable(ref('RawInputs')), commands=ref('Commands'),
                                                   age_ms=nullable(dict(type='integer')), tick=nullable(dict(type='integer')),
                                                   seq=nullable(dict(type='integer')))))}}},
            '/api/v1/telemetry': {'get': {
                'tags': ['Live'], 'operationId': 'listTelemetry', 'summary': 'All telemetry sensors',
                'responses': {'200': _ok(obj(dict(sensors=dict(type='object', additionalProperties=ref('Sensor')))))}}},
            '/api/v1/telemetry/{sensor}': {'get': {
                'tags': ['Live'], 'operationId': 'getTelemetrySensor', 'summary': 'One telemetry sensor', 'parameters': [SENSOR_PARAM],
                'responses': {'200': _ok(obj(dict(name=dict(type='string'), value=dict(type='number'), current=dict(type='boolean'),
                                                  fresh=dict(type='boolean'), age_ms=dict(type='integer')))),
                              '400': E400, '404': E404}}},
            '/api/v1/channels': {'get': {
                'tags': ['Live'], 'operationId': 'listChannels', 'summary': 'Mixer outputs CH1-CH16',
                'responses': {'200': _ok(obj(dict(channels=nullable(dict(type='array', items=CHANNEL, minItems=16, maxItems=16)))))}}},
            '/api/v1/channels/{n}': {'get': {
                'tags': ['Live'], 'operationId': 'getChannel', 'summary': 'One mixer output', 'parameters': [CHANNEL_PARAM],
                'responses': {'200': _ok(obj(dict(channel=dict(type='integer'), value=nullable(CHANNEL)))), '400': E400}}},
            '/api/v1/styles': {'get': {
                'tags': ['Settings'], 'operationId': 'listStyles', 'summary': 'Available overlay styles',
                'responses': {'200': _ok(dict(type='array', items=ref('Style')))}}},
            '/api/v1/settings': {
                'get': {'tags': ['Settings'], 'operationId': 'getSettings', 'summary': 'Current settings (saved values over defaults)',
                        'responses': {'200': _ok(ref('Settings'))}},
                'put': {'tags': ['Settings'], 'operationId': 'replaceSettings', 'summary': 'Replace all settings',
                        'description': 'Every setting must be present. Use PATCH to change only some.',
                        'requestBody': _json_body(ref('Settings')),
                        'responses': {'200': _ok(ref('Settings')), '400': E400, '415': E415}},
                'patch': {'tags': ['Settings'], 'operationId': 'updateSettings', 'summary': 'Change some settings',
                          'description': 'Unknown keys are ignored. A partial `mapping` only changes the entries it names.',
                          'requestBody': _json_body(ref('PartialSettings')),
                          'responses': {'200': _ok(ref('Settings')), '400': E400, '415': E415}},
                'delete': {'tags': ['Settings'], 'operationId': 'resetSettings', 'summary': 'Reset to defaults',
                           'responses': {'200': _ok(ref('Settings'))}}},
            '/api/v1/settings/mapping': {
                'get': {'tags': ['Settings'], 'operationId': 'getMapping', 'summary': 'Which radio inputs drive which functions',
                        'responses': {'200': _ok(ref('Mapping'))}},
                'put': {'tags': ['Settings'], 'operationId': 'replaceMapping', 'summary': 'Replace the mapping (all six entries)',
                        'requestBody': _json_body(ref('Mapping')),
                        'responses': {'200': _ok(ref('Mapping')), '400': E400, '415': E415}}},
            '/api/v1/recording': {
                'get': {'tags': ['Recording'], 'operationId': 'getRecording', 'summary': 'Current recording',
                        'responses': {'200': _ok(ref('Recording'))}},
                'post': {'tags': ['Recording'], 'operationId': 'startRecording', 'summary': 'Start recording',
                         'description': 'Writes a JSONL session log into the recordings folder. The file name is chosen by the server.',
                         'requestBody': _json_body(ref('RecordingStart'), required=False),
                         'responses': {'201': _ok(ref('Recording'), 'Recording started'), '400': E400, '409': E409, '415': E415}},
                'delete': {'tags': ['Recording'], 'operationId': 'stopRecording', 'summary': 'Stop recording',
                           'responses': {'200': _ok(ref('Recording'), 'The recording that was stopped'), '409': E409}}},
            '/api/v1/recordings': {'get': {
                'tags': ['Recording'], 'operationId': 'listRecordings', 'summary': 'Recordings in the folder, newest first',
                'responses': {'200': _ok(dict(type='array', items=ref('RecordingInfo')))}}},
            '/api/v1/recordings/{name}': {
                'get': {'tags': ['Recording'], 'operationId': 'downloadRecording', 'summary': 'Download the raw log (JSONL)',
                        'parameters': [NAME_PARAM],
                        'responses': {'200': {'description': 'JSON Lines, one object per line',
                                              'content': {'application/x-ndjson': {'schema': dict(type='string')}}},
                                      '400': E400, '404': E404}},
                'delete': {'tags': ['Recording'], 'operationId': 'deleteRecording', 'summary': 'Delete a recording',
                           'parameters': [NAME_PARAM],
                           'responses': {'204': {'description': 'Deleted'}, '400': E400, '404': E404, '409': E409}}},
            '/api/v1/recordings/{name}/report': {'get': {
                'tags': ['Recording'], 'operationId': 'getRecordingReport', 'summary': 'Quality report',
                'description': 'Sample rate, gaps, lost records, channel ranges, telemetry rates and warnings.',
                'parameters': [NAME_PARAM], 'responses': {'200': _ok(ref('Report')), '400': E400, '404': E404}}},
            '/api/state': {'get': {'tags': ['Legacy'], 'deprecated': True, 'operationId': 'legacyState',
                                   'summary': 'Alias of GET /api/v1/state', 'responses': {'200': _ok(ref('State'))}}},
            '/api/fx-config': {
                'get': {'tags': ['Legacy'], 'deprecated': True, 'operationId': 'legacyGetFxConfig',
                        'summary': 'Saved settings only (may be partial)', 'responses': {'200': _ok(ref('PartialSettings'))}},
                'post': {'tags': ['Legacy'], 'deprecated': True, 'operationId': 'legacyPostFxConfig',
                         'summary': 'Alias of PATCH /api/v1/settings; returns the saved (partial) settings',
                         'requestBody': _json_body(ref('PartialSettings')),
                         'responses': {'200': _ok(ref('PartialSettings')), '400': E400, '415': E415}}},
        },
        'components': {'schemas': SCHEMAS},
    }
