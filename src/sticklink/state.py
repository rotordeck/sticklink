"""Radio state machine: ingest parsed records, produce overlay snapshots."""
import time

from .config import Config


class RadioState:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.connected = False
        self.error = 'waiting for radio'
        self.invalid = self.missing = self.resets = self.samples = 0
        self.logger = None
        self.notes = []  # radio-side diagnostics (D records), newest last
        self.session = 0
        self.clear()

    def clear(self):
        self.controls = None
        self.outputs = [0]*16
        self.output_times = {}
        self.arm = self.crash = None
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
            self.session += 1
            self.resets += 1
        self.last_tick = tick
        if record['type'] == 'H':
            # An explicit hello marks a new script run, even at the same tick.
            if self.last_seq is not None:
                self.clear()
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
            self.last_sample = now
            self.samples += 1
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
            notes=list(self.notes), controls=controls, raw=dict(self.controls) if live else None, channels=outputs,
            commands=dict(arm=self.arm if live else None,
            crash=self.crash if live else None), telemetry=telemetry,
            tick=self.last_tick, seq=self.last_seq,
            age_ms=None if age is None else round(age), error=self.error,
            diagnostics=dict(invalid=self.invalid, missing=self.missing,
                             resets=self.resets, samples=self.samples))
