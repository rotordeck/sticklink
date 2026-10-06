"""Switch OBS scenes from radio channels, like Betaflight's Modes tab: every scene ("mode") has one or more ranges on a channel
(microseconds, 900-2100); a mode is active while any of its channels is inside any of its ranges.

Safety rules, because this changes a live output:
  - off until enabled; it never acts on stale radio data or while OBS is not connected;
  - when enabled, or after (re)connecting to OBS, it adopts the current situation without switching;
  - a candidate must stay stable for `debounceMs` (a 3-position switch passes through its middle position);
  - several active modes: the first one in the list wins (list order = priority).
"""
import asyncio
import json
import os
from pathlib import Path
import re
import time

HOST = re.compile(r'[A-Za-z0-9._:-]{1,253}')
CHANNEL = re.compile(r'ch:([1-9]|1[0-6])')
US_MIN, US_MAX = 900, 2100
MAX_MODES, MAX_RANGES, RECENT = 64, 8, 20
WHEN_NONE = ('stay', 'previous', 'scene')

DEFAULT_OBS = dict(enabled=False, host='127.0.0.1', port=4455, password='')
DEFAULT_MODES = dict(enabled=False, debounceMs=150, whenNone=dict(action='stay', scene=None), modes=[])


def default_path():
    base = os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config'
    return Path(base)/'sticklink'/'scenes.json'


def to_us(raw):
    """EdgeTX channel value (-1024..1024) to the microsecond scale Betaflight uses (1000..2000 at the ends)."""
    return round(1500 + raw*500/1024)


def _scene_name(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 255 or any(ord(c) < 32 for c in value):
        raise ValueError('a scene name is 1-255 characters without control characters')
    return value


def validate_obs(data, current):
    """Merge and validate connection settings. A missing `password` keeps the old one; a string (even empty) replaces it."""
    if not isinstance(data, dict):
        raise ValueError('object required')
    out = dict(current)
    unknown = set(data) - set(DEFAULT_OBS)
    if unknown:
        raise ValueError('unknown field: ' + ', '.join(sorted(unknown)))
    if 'enabled' in data:
        if not isinstance(data['enabled'], bool):
            raise ValueError('enabled must be a boolean')
        out['enabled'] = data['enabled']
    if 'host' in data:
        if not isinstance(data['host'], str) or not HOST.fullmatch(data['host']):
            raise ValueError('host is a name or IP address')
        out['host'] = data['host']
    if 'port' in data:
        if isinstance(data['port'], bool) or not isinstance(data['port'], int) or not 1 <= data['port'] <= 65535:
            raise ValueError('port must be 1-65535')
        out['port'] = data['port']
    if 'password' in data:
        if not isinstance(data['password'], str) or len(data['password']) > 256:
            raise ValueError('password must be text of at most 256 characters')
        out['password'] = data['password']
    return out


def validate_modes(data):
    """Validate a full scene-modes configuration."""
    if not isinstance(data, dict):
        raise ValueError('object required')
    unknown = set(data) - set(DEFAULT_MODES)
    if unknown:
        raise ValueError('unknown field: ' + ', '.join(sorted(unknown)))
    out = json.loads(json.dumps(DEFAULT_MODES))
    if 'enabled' in data:
        if not isinstance(data['enabled'], bool):
            raise ValueError('enabled must be a boolean')
        out['enabled'] = data['enabled']
    if 'debounceMs' in data:
        d = data['debounceMs']
        if isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 2000:
            raise ValueError('debounceMs must be 0-2000')
        out['debounceMs'] = d
    if 'whenNone' in data:
        w = data['whenNone']
        if not isinstance(w, dict) or w.get('action') not in WHEN_NONE or set(w) - {'action', 'scene'}:
            raise ValueError('whenNone.action must be one of ' + ', '.join(WHEN_NONE))
        scene = w.get('scene')
        if w['action'] == 'scene':
            scene = _scene_name(scene)
        elif scene is not None:
            raise ValueError('whenNone.scene is only used with action "scene"')
        out['whenNone'] = dict(action=w['action'], scene=scene)
    if 'modes' in data:
        modes = data['modes']
        if not isinstance(modes, list) or len(modes) > MAX_MODES:
            raise ValueError(f'modes is a list of at most {MAX_MODES}')
        seen, cleaned = set(), []
        for m in modes:
            if not isinstance(m, dict) or set(m) - {'scene', 'ranges'}:
                raise ValueError('a mode has a scene and ranges')
            scene = _scene_name(m.get('scene'))
            if scene in seen:
                raise ValueError(f'scene "{scene}" appears twice: give it more ranges instead')
            seen.add(scene)
            ranges = m.get('ranges', [])
            if not isinstance(ranges, list) or len(ranges) > MAX_RANGES:
                raise ValueError(f'a mode has at most {MAX_RANGES} ranges')
            clean_ranges = []
            for r in ranges:
                if not isinstance(r, dict) or set(r) != {'channel', 'min', 'max'}:
                    raise ValueError('a range has channel, min and max')
                if not isinstance(r['channel'], str) or not CHANNEL.fullmatch(r['channel']):
                    raise ValueError('channel must be ch:1 to ch:16')
                lo, hi = r['min'], r['max']
                if any(isinstance(v, bool) or not isinstance(v, int) for v in (lo, hi)) or not US_MIN <= lo <= hi <= US_MAX:
                    raise ValueError(f'min and max are whole microseconds, {US_MIN} <= min <= max <= {US_MAX}')
                clean_ranges.append(dict(channel=r['channel'], min=lo, max=hi))
            cleaned.append(dict(scene=scene, ranges=clean_ranges))
        out['modes'] = cleaned
    return out


class SceneStore:
    """The connection settings (including the OBS password) and the scene modes, in one JSON file only the user can read."""
    def __init__(self, path=None):
        self.path = Path(path) if path else default_path()

    def _read(self):
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            return validate_obs(raw.get('obs', {}), DEFAULT_OBS), validate_modes(raw.get('modes', {}))
        except (OSError, ValueError, AttributeError, TypeError):
            return dict(DEFAULT_OBS), json.loads(json.dumps(DEFAULT_MODES))

    def load(self):
        obs, modes = self._read()
        return dict(obs=obs, modes=modes)

    def _write(self, obs, modes):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # private from the first byte: it holds the OBS password
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(dict(obs=obs, modes=modes), f, indent=1)
        tmp.replace(self.path)

    def save_obs(self, data):
        obs, modes = self._read()
        obs = validate_obs(data, obs)
        self._write(obs, modes)
        return obs

    def save_modes(self, data):
        obs, _ = self._read()
        modes = validate_modes(data)
        self._write(obs, modes)
        return modes


class SceneEngine:
    def __init__(self, store, obs, channels, clock=time.monotonic):
        """`channels()` returns the 16 raw channel values, or None when the radio data is not live."""
        self.store, self.obs, self.channels, self.clock = store, obs, channels, clock
        self.config = store.load()['modes']
        self.baseline = False
        self.generation = None
        self.committed = None
        self.candidate, self.since = None, 0.0
        self.before_episode = None
        self.requested = None
        self.in_flight = None
        self.recent = []
        self.us = {}
        self.active = []
        self.desired = None
        self.blocked = 'disabled'

    def configure(self, config):
        was = self.config['enabled']
        self.config = config
        if not config['enabled'] or not was:
            self.baseline = False  # (re)enabling adopts the current state instead of switching
            self.committed = self.candidate = self.requested = None
            self.before_episode = None

    # ---------------------------------------------------------------- evaluation
    def evaluate(self, raw):
        """Which modes are active for these channel values, and which scene they ask for."""
        self.us = {f'ch:{i+1}': to_us(v) for i, v in enumerate(raw)}
        active = [m['scene'] for m in self.config['modes']
                  if any(r['min'] <= self.us.get(r['channel'], -1) <= r['max'] for r in m['ranges'])]
        desired = active[0] if active else None
        if desired is None:
            w = self.config['whenNone']
            desired = w['scene'] if w['action'] == 'scene' else self.before_episode if w['action'] == 'previous' and self.committed is not None else None
        return active, desired

    def tick(self, now=None):
        now = self.clock() if now is None else now
        cfg = self.config
        raw = self.channels()
        self.blocked = self._reason(raw)
        if raw is not None:
            self.active, self.desired = self.evaluate(raw)
        if self.blocked:
            if self.blocked == 'obs_not_connected':
                self.baseline = False
            return
        if self.generation != self.obs.generation:  # a new connection to OBS: adopt, never switch
            self.generation = self.obs.generation
            self.baseline = False
        if self.desired != self.candidate:
            self.candidate, self.since = self.desired, now
        stable = (now - self.since) * 1000 >= cfg['debounceMs']
        if not self.baseline:
            if stable:  # the first stable reading is the starting point, even if no mode is active in it
                self.committed, self.baseline, self.requested = self.candidate, True, self.candidate
        elif self.candidate != self.committed and stable:
            if self.committed is None and self.candidate is not None:
                self.before_episode = self.obs.current  # where "previous" returns to
            self.committed = self.candidate
        if self.baseline and self.committed is not None and self.committed != self.requested and self.in_flight is None:
            self.requested = self.committed
            self._switch(self.committed, 'radio')

    def _reason(self, raw):
        """Why nothing is being switched right now (None = the engine is live)."""
        return ('disabled' if not self.config['enabled'] else 'obs_not_connected' if self.obs.status != 'connected'
                else 'no_radio_data' if raw is None else None)

    def apply_now(self):
        """Switch to what the radio is asking for right now (a manual 'sync')."""
        raw = self.channels()
        if raw is None:
            raise ValueError('no live radio data')
        _, desired = self.evaluate(raw)
        if desired is None:
            raise ValueError('no mode is active')
        self.committed = self.candidate = self.requested = desired
        self.baseline = True
        self._switch(desired, 'apply')
        return desired

    # ---------------------------------------------------------------- switching
    def _switch(self, scene, reason):
        previous = self.obs.current
        entry = dict(t=round(time.time(), 3), scene=scene, previous=previous, reason=reason, ok=None, error=None)
        self.recent = (self.recent + [entry])[-RECENT:]

        async def go():
            try:
                await self.obs.set_scene(scene)
                entry['ok'] = True
            except Exception as exc:  # ObsError, or the connection vanished
                entry['ok'], entry['error'] = False, str(exc)
            finally:
                self.in_flight = None
        self.in_flight = asyncio.ensure_future(go())

    async def run(self, interval=0.05):
        while True:
            try:
                self.tick()
            except Exception as exc:  # never let a rule bug end the loop
                self.recent = (self.recent + [dict(t=round(time.time(), 3), scene=None, previous=None, reason='error', ok=False, error=repr(exc))])[-RECENT:]
            await asyncio.sleep(interval)

    def status(self):
        return dict(enabled=self.config['enabled'], blocked=self._reason(self.channels()), active=list(self.active), desired=self.desired,
                    committed=self.committed, channels={k: v for k, v in self.us.items() if int(k[3:]) >= 5},
                    recent=list(self.recent), currentScene=self.obs.current)
