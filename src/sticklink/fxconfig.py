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
    if 'invert' in data:
        if not isinstance(data['invert'], list) or any(a not in AXES for a in data['invert']):
            raise ValueError('invalid invert list')
        out['invert'] = [a for a in AXES if a in data['invert']]
    if 'size' in data:
        out['size'] = int(_num(data['size'], 240, 2160))
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
        out.update({k: v for k, v in saved.items() if k != 'mapping'})
        out['mapping'].update(saved.get('mapping', {}))
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
        self._write(cleaned)
        return cleaned

    def replace(self, data):
        """Full replacement: every setting must be present."""
        cleaned = validate(data)
        missing = [k for k in DEFAULTS if k not in cleaned]
        if missing:
            raise ValueError('missing: ' + ', '.join(missing))
        _complete_mapping(cleaned['mapping'])
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
