import asyncio
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from sticklink.obs import ObsError
from sticklink.scenes import SceneEngine, SceneStore, to_us, validate_modes, validate_obs, DEFAULT_OBS


def rng(channel, lo, hi):
    return dict(channel=channel, min=lo, max=hi)


def raw_for(us):
    return round((us - 1500) * 1024 / 500)


class FakeObsClient:
    def __init__(self, current='Intro'):
        self.status, self.generation, self.current = 'connected', 1, current
        self.switched, self.fail = [], False

    async def set_scene(self, name):
        if self.fail:
            raise ObsError('No scene was found by that name.', 600)
        self.switched.append(name)
        self.current = name


class Rig:
    """An engine wired to a fake OBS and a settable set of channel values, driven by a fake clock."""
    def __init__(self, modes, debounce=150, when_none=None, enabled=True, current='Intro'):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SceneStore(Path(self.tmp.name)/'scenes.json')
        self.obs = FakeObsClient(current)
        self.values = [0] * 16
        self.live = True
        self.engine = SceneEngine(self.store, self.obs, lambda: list(self.values) if self.live else None)
        self.engine.configure(validate_modes(dict(enabled=enabled, debounceMs=debounce, modes=modes, **({'whenNone': when_none} if when_none else {}))))
        self.now = 0.0

    def set(self, channel, us):
        self.values[channel - 1] = raw_for(us)

    async def run(self, seconds, step=0.05):
        end = self.now + seconds
        while self.now < end - 1e-9:
            self.now += step
            self.engine.tick(self.now)
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    def close(self):
        self.tmp.cleanup()


MODES3 = [dict(scene='Drone', ranges=[rng('ch:6', 900, 1300)]),
          dict(scene='Room', ranges=[rng('ch:6', 1300, 1700)]),
          dict(scene='Replay', ranges=[rng('ch:6', 1700, 2100)])]


class ConversionAndValidation(unittest.TestCase):
    def test_microseconds(self):
        self.assertEqual([to_us(v) for v in (-1024, 0, 1024, 512, -512)], [1000, 1500, 2000, 1750, 1250])
        self.assertEqual(to_us(2048), 2500, 'extended channel limits are not clamped')

    def test_valid_modes_roundtrip(self):
        cfg = validate_modes(dict(enabled=True, debounceMs=200, whenNone=dict(action='scene', scene='Intro'), modes=MODES3))
        self.assertEqual((cfg['enabled'], cfg['debounceMs'], len(cfg['modes'])), (True, 200, 3))

    def test_invalid_modes_are_rejected(self):
        bad = [dict(enabled='yes'), dict(debounceMs=-1), dict(debounceMs=5000), dict(whenNone=dict(action='explode')),
               dict(whenNone=dict(action='scene')), dict(whenNone=dict(action='stay', scene='X')), dict(extra=1), dict(modes='x'),
               dict(modes=[dict(scene='', ranges=[])]), dict(modes=[dict(scene='A\x00B', ranges=[])]),
               dict(modes=[dict(scene='A', ranges=[]), dict(scene='A', ranges=[])]),
               dict(modes=[dict(scene='A', ranges=[rng('ch:17', 1000, 1100)])]), dict(modes=[dict(scene='A', ranges=[rng('aux1', 1000, 1100)])]),
               dict(modes=[dict(scene='A', ranges=[rng('ch:5', 1100, 1000)])]), dict(modes=[dict(scene='A', ranges=[rng('ch:5', 800, 1000)])]),
               dict(modes=[dict(scene='A', ranges=[rng('ch:5', 1000, 2200)])]), dict(modes=[dict(scene='A', ranges=[rng('ch:5', 1000.5, 1100)])]),
               dict(modes=[dict(scene='A', ranges=[dict(channel='ch:5', min=1000, max=1100, x=1)])]),
               dict(modes=[dict(scene='S%d' % i, ranges=[]) for i in range(65)]),
               dict(modes=[dict(scene='A', ranges=[rng('ch:5', 1000, 1100)] * 9)])]
        for data in bad:
            with self.subTest(data=str(data)[:80]), self.assertRaises(ValueError):
                validate_modes(data)

    def test_obs_settings_keep_the_password_unless_replaced(self):
        cur = dict(DEFAULT_OBS, password='secret')
        self.assertEqual(validate_obs(dict(host='192.168.1.5', port=4456), cur)['password'], 'secret')
        self.assertEqual(validate_obs(dict(password=''), cur)['password'], '')
        for bad in (dict(host='http://x'), dict(host='a b'), dict(port=0), dict(port=70000), dict(port='4455'), dict(enabled=1), dict(password=5), dict(x=1)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_obs(bad, cur)

    def test_store_is_private_atomic_and_survives_garbage(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SceneStore(Path(tmp)/'sub'/'scenes.json')
            self.assertEqual(store.load()['obs'], DEFAULT_OBS)
            store.save_obs(dict(host='10.0.0.2', password='hunter2'))
            store.save_modes(dict(enabled=True, modes=MODES3))
            self.assertEqual(store.load()['obs']['password'], 'hunter2')
            self.assertEqual(len(store.load()['modes']['modes']), 3)
            if os.name != 'nt':
                self.assertEqual(stat.S_IMODE(store.path.stat().st_mode), 0o600, 'only the user may read the OBS password')
            store.path.write_text('{not json')
            self.assertEqual(store.load()['obs'], DEFAULT_OBS)


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_adopts_the_current_state_when_enabled_then_switches_on_change(self):
        r = Rig(MODES3, current='Intro')
        r.set(6, 1000)                       # the switch is already in the Drone position
        await r.run(1.0)
        self.assertEqual(r.obs.switched, [], 'enabling must not switch by itself')
        r.set(6, 1500)
        await r.run(0.4)
        self.assertEqual(r.obs.switched, ['Room'])
        r.set(6, 2000)
        await r.run(0.4)
        self.assertEqual(r.obs.switched, ['Room', 'Replay'])
        r.close()

    async def test_debounce_ignores_a_switch_passing_through_the_middle(self):
        r = Rig(MODES3, debounce=150)
        r.set(6, 1000)
        await r.run(0.5)
        r.set(6, 1500); await r.run(0.1)     # 100 ms in the middle position...
        r.set(6, 2000); await r.run(0.5)     # ...then on to the top
        self.assertEqual(r.obs.switched, ['Replay'], 'the middle scene never flashed')
        r.close()

    async def test_range_boundaries_are_inclusive(self):
        r = Rig([dict(scene='Edge', ranges=[rng('ch:7', 1700, 1800)])], debounce=0)
        for us, expect in ((1675, False), (1700, True), (1750, True), (1800, True), (1825, False)):
            r.set(7, us)
            r.engine.config['modes'][0]
            active, _ = r.engine.evaluate(r.values)
            self.assertEqual(bool(active), expect, us)
        r.close()

    async def test_first_mode_in_the_list_wins_and_the_next_takes_over(self):
        modes = [dict(scene='Replay', ranges=[rng('ch:9', 1700, 2100)]), dict(scene='Drone', ranges=[rng('ch:6', 1700, 2100)])]
        r = Rig(modes, debounce=0)
        r.set(6, 1000); r.set(9, 1000)
        await r.run(0.3)
        r.set(6, 2000); await r.run(0.3)
        r.set(9, 2000); await r.run(0.3)       # both active: Replay is first in the list
        r.set(9, 1000); await r.run(0.3)       # released: Drone is still asked for by ch:6
        self.assertEqual(r.obs.switched, ['Drone', 'Replay', 'Drone'])
        r.close()

    async def test_several_ranges_and_channels_for_one_mode(self):
        r = Rig([dict(scene='Crash', ranges=[rng('ch:8', 1700, 2100), rng('ch:5', 900, 1100)])], debounce=0)
        r.set(8, 1000); r.set(5, 1500)
        await r.run(0.3)
        r.set(5, 1000); await r.run(0.3)
        self.assertEqual(r.obs.switched, ['Crash'])
        r.close()

    async def test_when_released_return_to_the_previous_scene(self):
        r = Rig([dict(scene='Replay', ranges=[rng('ch:10', 1700, 2100)])], debounce=0, when_none=dict(action='previous', scene=None), current='Drone')
        r.set(10, 1000)
        await r.run(0.3)
        r.set(10, 2000); await r.run(0.3)      # button held
        r.set(10, 1000); await r.run(0.4)      # released
        self.assertEqual(r.obs.switched, ['Replay', 'Drone'])
        r.close()

    async def test_when_nothing_is_active_go_to_a_fixed_scene_or_stay(self):
        r = Rig(MODES3[:1], debounce=0, when_none=dict(action='scene', scene='Intro'), current='Room')
        r.set(6, 2000); await r.run(0.3)       # nothing active (Drone is 900-1300): baseline -> Intro? it adopts, no switch
        self.assertEqual(r.obs.switched, [])
        r.set(6, 1000); await r.run(0.3)
        r.set(6, 2000); await r.run(0.3)
        self.assertEqual(r.obs.switched, ['Drone', 'Intro'])
        r.close()
        stay = Rig(MODES3[:1], debounce=0, current='Room')
        stay.set(6, 1000); await stay.run(0.3)
        stay.set(6, 2000); await stay.run(0.3)
        self.assertEqual(stay.obs.switched, [], 'the default is to stay on the scene')
        stay.close()

    async def test_stale_radio_data_never_switches_and_resuming_does_not_either(self):
        r = Rig(MODES3, debounce=0)
        r.set(6, 1000); await r.run(0.3)
        r.live = False
        r.set(6, 2000); await r.run(2.0)       # the radio is gone; garbage in the buffer must not be acted on
        self.assertEqual(r.obs.switched, [])
        self.assertEqual(r.engine.blocked, 'no_radio_data')
        r.live = True
        await r.run(0.4)                        # data is back, switch is in the Replay position: that is a change
        self.assertEqual(r.obs.switched, ['Replay'])
        r.close()

    async def test_a_new_obs_connection_adopts_instead_of_switching(self):
        r = Rig(MODES3, debounce=0)
        r.set(6, 1000); await r.run(0.3)
        r.obs.status = 'error'; await r.run(0.2)
        r.set(6, 2000)                          # moved while OBS was away
        r.obs.status, r.obs.generation = 'connected', 2
        await r.run(0.5)
        self.assertEqual(r.obs.switched, [], 'reconnecting must not fire a scene change')
        r.set(6, 1500); await r.run(0.3)
        self.assertEqual(r.obs.switched, ['Room'])
        r.close()

    async def test_disabled_does_nothing_and_enabling_re_baselines(self):
        r = Rig(MODES3, debounce=0, enabled=False)
        r.set(6, 1000); await r.run(0.3)
        r.set(6, 2000); await r.run(0.3)
        self.assertEqual((r.obs.switched, r.engine.blocked), ([], 'disabled'))
        r.engine.configure(validate_modes(dict(enabled=True, debounceMs=0, modes=MODES3)))
        await r.run(0.3)
        self.assertEqual(r.obs.switched, [], 'switching on enabled the state, it did not fire a change')
        r.close()

    async def test_apply_now_syncs_obs_to_the_radio(self):
        r = Rig(MODES3, debounce=500)
        r.set(6, 2000); await r.run(0.2)
        self.assertEqual(r.engine.apply_now(), 'Replay')
        await asyncio.sleep(0)
        self.assertEqual(r.obs.switched, ['Replay'])
        r.live = False
        with self.assertRaises(ValueError):
            r.engine.apply_now()
        r.close()

    async def test_a_failed_switch_is_recorded_once_and_not_retried_every_tick(self):
        r = Rig(MODES3, debounce=0)
        r.set(6, 1000); await r.run(0.3)
        r.obs.fail = True
        r.set(6, 2000); await r.run(1.5)
        failures = [e for e in r.engine.recent if e['ok'] is False]
        self.assertEqual(len(failures), 1)
        self.assertIn('No scene', failures[0]['error'])
        r.close()

    async def test_status_reports_live_values_for_the_ui(self):
        r = Rig(MODES3, debounce=0)
        r.set(6, 1500); await r.run(0.3)
        st = r.engine.status()
        self.assertEqual((st['active'], st['desired'], st['blocked']), (['Room'], 'Room', None))
        self.assertEqual(st['channels']['ch:6'], 1500)
        self.assertNotIn('ch:1', st['channels'], 'only AUX channels (CH5 and up) are reported')
        r.close()


if __name__ == '__main__':
    unittest.main()
