"""Radio state machine: ingest parsed records, produce overlay snapshots."""
import time

from .config import Config
from .geo import bearing_deg, haversine_m
from .race import RaceTimer

MIN_TRACK_STEP_M = 2.0   # a new track point only after moving this far
MAX_TRACK_POINTS = 5000
FIX_MAX_AGE_S = 3.0


class RadioState:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.connected = False
        self.error = 'waiting for radio'
        self.invalid = self.missing = self.resets = self.samples = 0
        self.logger = None
        self.notes = []  # radio-side diagnostics (D records), newest last
        self.reset_gps()
        self.session = 0
        self.clear()

    def reset_gps(self):
        """Forget the GPS fix, home point and track (the radio script restarted, or the user cleared it)."""
        self.gps = None  # dict(lat, lon, received)
        self.home = None  # (lat, lon)
        self.track = []  # [(lat, lon)], thinned by distance

    def clear(self):
        self.controls = None
        self.outputs = [0]*16
        self.output_times = {}
        self.arm = self.crash = None
        self.race = RaceTimer(self.config.race_double_tap_ms)
        self.telemetry = {}
        self.last_sample = self.last_tick = self.last_seq = None

    def connection(self, connected, message=''):
        if connected:
            self.session += 1
            self.clear()
            self.logger = None
        else:
            self.clear()
        self.connected = connected
        self.error = message

    def ingest(self, record, now=None):
        cfg = self.config
        now = time.monotonic() if now is None else now
        tick = record['tick']
        restarted = self.last_tick is not None and tick < self.last_tick
        if restarted:
            self.clear()
            self.reset_gps()
            self.session += 1
            self.resets += 1
        self.last_tick = tick
        if record['type'] == 'H':
            # An explicit hello marks a new script run, even at the same tick.
            if self.last_seq is not None:
                self.clear()
                self.reset_gps()
                self.session += 1
                self.resets += 1
                self.last_tick = tick
            self.logger = record['logger']
            self.notes = []
            return
        seq = record['seq']
        if self.last_seq is not None:
            step = (seq - self.last_seq) % 65536
            if step == 0:  # retransmitted record
                return
            if step >= 32768:  # restart without a received hello
                self.clear()
                self.reset_gps()
                self.session += 1
                self.resets += 1
                self.last_tick = tick
            else:
                self.missing += step - 1
        self.last_seq = seq
        if record['type'] == 'S':
            self.controls = record['channels']
            self.arm = self.controls['arm'] > cfg.arm_threshold
            self.crash = self.controls['crash'] > cfg.crash_threshold
            self.race.feed(tick, self.arm, self.crash)
            self.last_sample = now
            self.samples += 1
        elif record['type'] == 'G':
            self.ingest_gps(record, now)
        elif record['type'] == 'D':
            self.notes = (self.notes + [record['message']])[-8:]
        elif record['type'] == 'C':
            first = record['first']
            self.outputs[first-1:first-1+len(record['outputs'])] = record['outputs']
            self.output_times[first] = now
        elif record['type'] == 'E':
            setattr(self, record['event'].lower(), bool(record['value']))
        else:
            self.telemetry[record['sensor']] = dict(
                value=record['value'], current=record['current'],
                fresh=record['fresh'], received=now)

    def ingest_gps(self, record, now):
        lat, lon = record['lat'], record['lon']
        if abs(lat) < 1e-6 and abs(lon) < 1e-6:  # (0, 0) means "no fix"
            return
        self.gps = dict(lat=lat, lon=lon, received=now)
        if self.home is None:
            plat, plon = record['plat'], record['plon']
            pilot = not (abs(plat) < 1e-6 and abs(plon) < 1e-6)
            self.home = (plat, plon) if pilot else (lat, lon)
        if not self.track or haversine_m(*self.track[-1], lat, lon) >= MIN_TRACK_STEP_M:
            self.track.append((lat, lon))
            if len(self.track) > MAX_TRACK_POINTS:
                del self.track[0]

    def channels_now(self, now=None):
        """The 16 raw channel values, or None unless both halves arrived recently (the same rule as the snapshot's `channels`)."""
        now = time.monotonic() if now is None else now
        limit = max(1000, self.config.stale_ms)
        if self.connected and len(self.output_times) == 2 and all((now-t)*1000 <= limit for t in self.output_times.values()):
            return list(self.outputs)
        return None

    def gps_snapshot(self, now):
        if self.gps is None:
            return dict(fix=False, lat=None, lon=None, age_ms=None, home=None, distance_m=None, bearing_deg=None,
                        track_points=len(self.track))
        age = now - self.gps['received']
        out = dict(fix=self.connected and age <= FIX_MAX_AGE_S, lat=self.gps['lat'], lon=self.gps['lon'],
                   age_ms=round(age*1000), home=None, distance_m=None, bearing_deg=None, track_points=len(self.track))
        if self.home is not None:
            out['home'] = dict(lat=self.home[0], lon=self.home[1])
            out['distance_m'] = round(haversine_m(*self.home, self.gps['lat'], self.gps['lon']), 1)
            out['bearing_deg'] = round(bearing_deg(*self.home, self.gps['lat'], self.gps['lon']), 1)
        return out

    def snapshot(self, now=None):
        cfg = self.config
        now = time.monotonic() if now is None else now
        age = None if self.last_sample is None else (now-self.last_sample)*1000
        live = self.connected and age is not None and age <= cfg.stale_ms
        status = ('demo' if cfg.demo else 'live') if live else (
            'paused' if self.connected else 'disconnected')
        controls = None
        if live:
            controls = {k: max(-1, min(1, self.controls[k]/cfg.scale))
                        for k in ('roll', 'pitch', 'yaw', 'throttle')}
        outputs = None
        limit = max(1000, cfg.stale_ms)
        if (self.connected and len(self.output_times) == 2
                and all((now-t)*1000 <= limit for t in self.output_times.values())):
            outputs = list(self.outputs)
        telemetry = {}
        for name, item in self.telemetry.items():
            sensor_age = (now-item['received'])*1000
            telemetry[name] = dict(value=item['value'],
                current=item['current'] and self.connected and sensor_age <= 1500,
                fresh=item['fresh'] and self.connected and sensor_age <= 300,
                age_ms=round(sensor_age))
        return dict(schema=1, session=self.session, status=status,
            source=('sticks' if self.logger == 'DDRAW' else 'outputs'
                    if self.logger == 'DDOUT' else cfg.input_label),
            notes=list(self.notes), gps=self.gps_snapshot(now), controls=controls, raw=dict(self.controls) if live else None, channels=outputs,
            commands=dict(arm=self.arm if live else None,
            crash=self.crash if live else None), telemetry=telemetry,
            race=self.race.snapshot() if live else None,
            tick=self.last_tick, seq=self.last_seq,
            age_ms=None if age is None else round(age), error=self.error,
            diagnostics=dict(invalid=self.invalid, missing=self.missing,
                             resets=self.resets, samples=self.samples))
