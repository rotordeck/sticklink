"""Overlay settings shared by every open overlay page (OBS, browser), stored as JSON."""
import json
import os
import re
from pathlib import Path

STYLE_INFO = (
    ('clean', 'Clean', 'The classic: white ring, crosshair, red dot'),
    ('minimal', 'Minimal', 'Thin square, white dot, nothing else'),
    ('neon', 'Neon', 'Glowing rings and light-painted trails'),
    ('arcade', 'Arcade', 'Sparks, shockwaves, combos and live throttle stats. Go nuts.'),
    ('synthwave', 'Synthwave', 'Retro grid, scanlines and RGB split'),
    ('inferno', 'Inferno', 'Afterburner flames and rising embers'),
    ('unicorn', 'Unicorns & Rainbows', 'Rainbow trails, twinkling stars, pastel magic'),
    ('hacker', '80s Cyberpunk Hacker', 'Green phosphor terminal, glyph rain, glitches'),
)
STYLES = tuple(s[0] for s in STYLE_INFO)
DEFAULTS = dict(
    style='neon', chaos=1.0, mode=2, delay=0, invert=[], size=1080,
    mapping=dict(roll=dict(src='in:roll', rev=False), pitch=dict(src='in:pitch', rev=False),
                 yaw=dict(src='in:yaw', rev=False), throttle=dict(src='in:throttle', rev=False),
                 arm=dict(src='in:arm', thr=0, dir=1), flip=None),
)
MAPPING_KEYS = ('roll', 'pitch', 'yaw', 'throttle', 'arm', 'flip')
DEFAULTS['hud'] = dict(
    style=None, layout='corners', cells=4,
    blocks=dict(link=True, battery=True, gps=True, status=True),
    units=dict(speed='kmh', alt='m'),
    map=dict(provider='osm', customUrl='', attribution='', zoom='auto', follow=True),
)
HUD_LAYOUTS = ('corners', 'row', 'column')
MAP_PROVIDERS = ('osm', 'carto-dark', 'carto-light', 'custom', 'none')
TILE_URL = re.compile(r'(https://|http://(localhost|127\.0\.0\.1)(:\d{1,5})?/)[^\s"\'<>]{1,250}')
AXES = ('roll', 'pitch', 'yaw', 'throttle')
SOURCE = re.compile(r'in:(roll|pitch|yaw|throttle|arm|crash)|ch:([1-9]|1[0-6])')


def _source(value):
    if not isinstance(value, str) or not SOURCE.fullmatch(value):
        raise ValueError('invalid source')
    return value


def _mapping(data):
    if not isinstance(data, dict):
        raise ValueError('mapping must be an object')
    out = {}
    for axis in AXES:
        if axis in data:
            m = data[axis]
            if not isinstance(m, dict) or not isinstance(m.get('rev', False), bool):
                raise ValueError('invalid axis mapping')
            out[axis] = dict(src=_source(m.get('src')), rev=m.get('rev', False))
    for name in ('arm', 'flip'):
        if name in data:
            m = data[name]
            if m is None:
                out[name] = None
                continue
            if not isinstance(m, dict) or m.get('dir') not in (1, -1):
                raise ValueError('invalid switch mapping')
            out[name] = dict(src=_source(m.get('src')), thr=int(_num(m.get('thr'), -2048, 2048)),
                             dir=m['dir'])
    return out


def default_path():
    base = os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config'
    return Path(base)/'sticklink'/'fx.json'


def _num(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('number required')
    if value != value or not low <= value <= high:
        raise ValueError('out of range')
    return value


def _hud(data):
    if not isinstance(data, dict):
        raise ValueError('hud must be an object')
    out = {}
    if 'style' in data:
        if data['style'] is not None and data['style'] not in STYLES:
            raise ValueError('unknown hud style')
        out['style'] = data['style']
    if 'layout' in data:
        if data['layout'] not in HUD_LAYOUTS:
            raise ValueError('hud layout must be one of ' + ', '.join(HUD_LAYOUTS))
        out['layout'] = data['layout']
    if 'cells' in data:
        out['cells'] = int(_num(data['cells'], 1, 8))
    if 'blocks' in data:
        b = data['blocks']
        if not isinstance(b, dict) or any(k not in DEFAULTS['hud']['blocks'] or not isinstance(v, bool) for k, v in b.items()):
            raise ValueError('hud.blocks takes booleans for ' + ', '.join(DEFAULTS['hud']['blocks']))
        out['blocks'] = dict(b)
    if 'units' in data:
        u = data['units']
        ok = dict(speed=('kmh', 'mph'), alt=('m', 'ft'))
        if not isinstance(u, dict) or any(k not in ok or v not in ok[k] for k, v in u.items()):
            raise ValueError('hud.units: speed is kmh or mph, alt is m or ft')
        out['units'] = dict(u)
    if 'map' in data:
        m, clean = data['map'], {}
        if not isinstance(m, dict) or set(m) - set(DEFAULTS['hud']['map']):
            raise ValueError('hud.map takes ' + ', '.join(DEFAULTS['hud']['map']))
        if 'provider' in m:
            if m['provider'] not in MAP_PROVIDERS:
                raise ValueError('map provider must be one of ' + ', '.join(MAP_PROVIDERS))
            clean['provider'] = m['provider']
        if 'customUrl' in m:
            url = m['customUrl']
            if not isinstance(url, str) or (url and not (TILE_URL.fullmatch(url) and all(t in url for t in ('{z}', '{x}', '{y}')))):
                raise ValueError('customUrl must be https:// (or http://localhost) and contain {z}, {x} and {y}')
            clean['customUrl'] = url
        if 'attribution' in m:
            a = m['attribution']
            if not isinstance(a, str) or len(a) > 120 or any(c in a for c in '<>\n\r\t'):
                raise ValueError('attribution is plain text, up to 120 characters')
            clean['attribution'] = a
        if 'zoom' in m:
            z = m['zoom']
            if z != 'auto':
                z = int(_num(z, 1, 19))
            clean['zoom'] = z
        if 'follow' in m:
            if not isinstance(m['follow'], bool):
                raise ValueError('follow must be a boolean')
            clean['follow'] = m['follow']
        out['map'] = clean
    return out


def validate(data):
    """Return a cleaned dict of known keys; raise ValueError on any invalid value."""
    if not isinstance(data, dict):
        raise ValueError('object required')
    out = {}
    if 'style' in data:
        if data['style'] not in STYLES:
            raise ValueError('unknown style')
        out['style'] = data['style']
    if 'chaos' in data:
        out['chaos'] = float(_num(data['chaos'], 0, 2))
    if 'mode' in data:
        if data['mode'] not in (1, 2, 3, 4):
            raise ValueError('mode must be 1-4')
        out['mode'] = data['mode']
    if 'delay' in data:
        out['delay'] = int(_num(data['delay'], 0, 5000))
    if 'mapping' in data:
        out['mapping'] = _mapping(data['mapping'])
    if 'hud' in data:
        out['hud'] = _hud(data['hud'])
    if 'invert' in data:
        if not isinstance(data['invert'], list) or any(a not in AXES for a in data['invert']):
            raise ValueError('invalid invert list')
        out['invert'] = [a for a in AXES if a in data['invert']]
    if 'size' in data:
        out['size'] = int(_num(data['size'], 240, 2160))
    return out


def deep_merge(base, new):
    """Dicts merge key by key (so a partial update changes only what it names); anything else is replaced."""
    out = _copy(base)
    for key, value in new.items():
        out[key] = deep_merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else _copy(value)
    return out


def _copy(value):
    return json.loads(json.dumps(value))


def _complete_mapping(mapping):
    missing = [k for k in MAPPING_KEYS if k not in mapping]
    if missing:
        raise ValueError('mapping is missing: ' + ', '.join(missing))


class FxConfigStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else default_path()

    def load(self):
        """Saved settings only (possibly partial)."""
        try:
            return validate(json.loads(self.path.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            return {}

    def merged(self):
        """Complete settings: saved values over the defaults."""
        out = _copy(DEFAULTS)
        saved = self.load()
        out.update({k: v for k, v in saved.items() if k not in ('mapping', 'hud')})
        out['mapping'].update(saved.get('mapping', {}))
        out['hud'] = deep_merge(out['hud'], saved.get('hud', {}))
        return out

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=1), encoding='utf-8')
        tmp.replace(self.path)  # atomic: a crash never leaves a torn file

    def save(self, data):
        """Merge: provided keys win; a partial mapping only changes the keys it names."""
        new = validate(data)
        cleaned = {**self.load(), **new}
        if 'mapping' in new:
            cleaned['mapping'] = {**self.load().get('mapping', {}), **new['mapping']}
        if 'hud' in new:
            cleaned['hud'] = deep_merge(self.load().get('hud', {}), new['hud'])
        self._write(cleaned)
        return cleaned

    def replace(self, data):
        """Full replacement: every setting must be present."""
        cleaned = validate(data)
        missing = [k for k in DEFAULTS if k not in cleaned]
        if missing:
            raise ValueError('missing: ' + ', '.join(missing))
        _complete_mapping(cleaned['mapping'])
        cleaned['hud'] = deep_merge(DEFAULTS['hud'], cleaned['hud'])
        self._write(cleaned)
        return cleaned

    def replace_mapping(self, mapping):
        cleaned = validate(dict(mapping=mapping))['mapping']
        _complete_mapping(cleaned)
        self._write({**self.load(), 'mapping': cleaned})
        return cleaned

    def reset(self):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
