"""Lap timer driven by one switch (the crash flip). Pure and deterministic: time comes from the radio's own clock.

A press (rising edge) while armed starts a race; every later press closes a lap. Two presses within `double_tap_ms`
are the stop gesture: the first of the two was a real lap, the second only says "stop", and the big number freezes at
the total race time of that first press.
"""

MAX_LAPS_SHOWN = 20   # the snapshot carries the newest laps only; `lap_count` is the real total
TICK_MS = 10          # the radio clock counts in 10 ms units


class RaceTimer:
    def __init__(self, double_tap_ms=500):
        self.double_tap_ms = double_tap_ms
        self._pressed = None   # last switch state; None until the first sample, so a switch already on at connect is no press
        self.reset()

    def reset(self):
        """Back to idle with no laps (the radio restarted, or the user pressed Reset)."""
        self.state = 'idle'    # idle | running | finished
        self.laps = []
        self.start_ms = self.lap_start_ms = self.last_press_ms = self.total_ms = None
        self.now_ms = None
        self.version = getattr(self, 'version', 0) + 1

    def _finish(self, total_ms):
        self.state, self.total_ms = 'finished', total_ms
        self.version += 1

    def feed(self, tick, armed, pressed):
        """One control sample: radio tick (10 ms units), whether the quad is armed, whether the switch is on."""
        now = tick * TICK_MS
        self.now_ms = now
        pressed = bool(pressed)
        edge = pressed and self._pressed is False
        self._pressed = pressed
        if not armed:
            if self.state == 'running':  # disarming ends the race at the last closed lap
                if self.laps:
                    self._finish(self.lap_start_ms - self.start_ms)
                else:
                    self.reset()
            return
        if not edge:
            return
        double = self.last_press_ms is not None and now - self.last_press_ms <= self.double_tap_ms
        self.last_press_ms = now
        if self.state == 'running':
            if not double:
                self.laps.append(now - self.lap_start_ms)
                self.lap_start_ms = now
                self.version += 1
            elif self.laps:  # the previous press closed a lap: stop at it
                self._finish(self.lap_start_ms - self.start_ms)
            else:            # the previous press was the start: a double tap at the start cancels
                self.reset()
                self.last_press_ms = now
        elif not double:     # a third tap of a stop gesture must not start a new race
            self.laps = []
            self.start_ms = self.lap_start_ms = now
            self.total_ms = None
            self.state = 'running'
            self.version += 1

    def snapshot(self):
        """`lap_ms` is the current lap (only while running); `elapsed_ms` the race so far, or the frozen total when
        finished. Both are as of the newest sample: pages add the time since they received it."""
        running = self.state == 'running' and self.now_ms is not None
        return dict(
            state=self.state,
            lap_ms=self.now_ms - self.lap_start_ms if running else None,
            elapsed_ms=self.now_ms - self.start_ms if running else self.total_ms,
            laps=self.laps[-MAX_LAPS_SHOWN:], lap_count=len(self.laps), version=self.version)
