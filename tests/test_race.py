import unittest

from sticklink.config import Config
from sticklink.protocol import parse_line
from sticklink.race import RaceTimer
from sticklink.state import RadioState


class Rig:
    """Feeds a RaceTimer at 20 Hz (radio ticks are 10 ms): `tap(t)` presses the switch for 100 ms starting at t seconds."""

    def __init__(self, **kw):
        self.race = RaceTimer(**kw)
        self.armed = True

    def run(self, until, taps=(), armed_until=None):
        for i in range(0, int(until*20)+1):
            t = i/20
            armed = self.armed and (armed_until is None or t < armed_until)
            self.race.feed(round(t*100), armed, any(a <= t < a+0.1 for a in taps))
        return self.race.snapshot()


class RaceTimerTests(unittest.TestCase):
    def test_idle_until_pressed_and_unarmed_presses_are_ignored(self):
        rig = Rig()
        rig.armed = False
        self.assertEqual(rig.run(3, taps=[1])['state'], 'idle')
        rig.armed = True
        self.assertEqual(rig.run(6)['state'], 'idle')

    def test_switch_already_on_at_connect_is_not_a_press(self):
        race = RaceTimer()
        for t in range(0, 100, 5):
            race.feed(t, True, True)
        self.assertEqual(race.snapshot()['state'], 'idle')

    def test_start_then_laps(self):
        snap = Rig().run(20, taps=[2, 7, 12.5])
        self.assertEqual(snap['state'], 'running')
        self.assertEqual(snap['laps'], [5000, 5500])
        self.assertEqual(snap['lap_count'], 2)
        self.assertEqual(snap['lap_ms'], 7500)      # 12.5 -> 20
        self.assertEqual(snap['elapsed_ms'], 18000)  # 2 -> 20

    def test_double_tap_stops_and_keeps_the_lap_it_closed(self):
        snap = Rig().run(20, taps=[2, 7, 12, 12.3])
        self.assertEqual(snap['state'], 'finished')
        self.assertEqual(snap['laps'], [5000, 5000])
        self.assertEqual(snap['elapsed_ms'], 10000)  # total at the first tap of the double
        self.assertIsNone(snap['lap_ms'])

    def test_double_tap_at_the_start_cancels(self):
        snap = Rig().run(10, taps=[2, 2.3])
        self.assertEqual((snap['state'], snap['laps']), ('idle', []))

    def test_triple_tap_does_not_restart(self):
        snap = Rig().run(10, taps=[2, 5, 5.3, 5.6])
        self.assertEqual(snap['state'], 'finished')

    def test_next_single_tap_after_a_stop_starts_a_fresh_race(self):
        snap = Rig().run(30, taps=[2, 5, 5.3, 12])
        self.assertEqual(snap['state'], 'running')
        self.assertEqual(snap['laps'], [])
        self.assertEqual(snap['elapsed_ms'], 18000)

    def test_slow_second_tap_is_just_another_lap(self):
        snap = Rig(double_tap_ms=300).run(10, taps=[2, 4, 4.4])
        self.assertEqual((snap['state'], snap['laps']), ('running', [2000, 400]))

    def test_disarming_ends_the_race_at_the_last_lap(self):
        snap = Rig().run(20, taps=[2, 6, 9], armed_until=12)
        self.assertEqual(snap['state'], 'finished')
        self.assertEqual(snap['elapsed_ms'], 7000)   # 2 -> 9
        self.assertEqual(Rig().run(20, taps=[2], armed_until=5)['state'], 'idle')

    def test_reset_and_version(self):
        rig = Rig()
        v0 = rig.race.snapshot()['version']
        snap = rig.run(8, taps=[2, 5])
        self.assertGreater(snap['version'], v0)
        rig.race.reset()
        self.assertEqual(rig.race.snapshot()['state'], 'idle')
        self.assertGreater(rig.race.snapshot()['version'], snap['version'])

    def test_laps_in_the_snapshot_are_capped_but_counted(self):
        snap = Rig().run(80, taps=[2 + 2*i for i in range(30)])
        self.assertEqual(snap['lap_count'], 29)
        self.assertEqual(len(snap['laps']), 20)


class RaceThroughStateTests(unittest.TestCase):
    def test_snapshot_carries_the_race_and_a_new_session_clears_it(self):
        s = RadioState(Config())
        s.connection(True)
        seq = 0

        def sample(tick, arm, crash):
            nonlocal seq
            seq += 1
            s.ingest(parse_line(f'S,{tick},{seq},0,0,0,-1024,{arm},{crash}'), tick/100)
        sample(100, 1024, -1024)
        sample(110, 1024, 1024)   # press: starts
        sample(120, 1024, -1024)
        sample(300, 1024, 1024)   # press: lap of 1.9 s
        snap = s.snapshot(3.0)
        self.assertEqual(snap['race']['state'], 'running')
        self.assertEqual(snap['race']['laps'], [1900])
        s.connection(True)
        self.assertEqual(s.race.snapshot()['state'], 'idle')


if __name__ == '__main__':
    unittest.main()
