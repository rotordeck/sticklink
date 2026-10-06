import copy
import unittest

try:
    from test_api import ApiCase  # python -m unittest discover -s tests
except ImportError:
    from tests.test_api import ApiCase  # python -m unittest tests.test_gps

from sticklink.config import Config
from sticklink.fxconfig import DEFAULTS
from sticklink.geo import bearing_deg, haversine_m
from sticklink.protocol import parse_line
from sticklink.state import MAX_TRACK_POINTS, RadioState


def gps(lat, lon, plat=0, plon=0, seq=1):
    return parse_line(f'G,100,{seq},{lat:.6f},{lon:.6f},{plat:.6f},{plon:.6f}')


class GeoTests(unittest.TestCase):
    def test_known_distances_and_bearings(self):
        # Brussels -> Paris: 263.98 km and initial bearing 213.656 degrees (south-west), both cross-checked with an
        # independent unit-vector calculation
        self.assertAlmostEqual(haversine_m(50.8503, 4.3517, 48.8566, 2.3522) / 1000, 263.98, delta=0.05)
        self.assertAlmostEqual(bearing_deg(50.8503, 4.3517, 48.8566, 2.3522), 213.656, delta=0.01)
        self.assertAlmostEqual(haversine_m(0, 0, 0, 1) / 1000, 111.19, delta=0.1)  # one degree on the equator
        for target, expect in (((1, 0), 0), ((0, 1), 90), ((-1, 0), 180), ((0, -1), 270)):
            self.assertAlmostEqual(bearing_deg(0, 0, *target), expect, delta=0.01)
        self.assertEqual(haversine_m(51.0, 3.7, 51.0, 3.7), 0)


class GpsStateTests(unittest.TestCase):
    def setUp(self):
        self.s = RadioState(Config())
        self.s.connection(True)

    def test_first_fix_is_home_and_distance_bearing_follow(self):
        self.s.ingest(gps(51.0, 3.7), 1)
        snap = self.s.snapshot(1.1)['gps']
        self.assertTrue(snap['fix'])
        self.assertEqual((snap['home'], snap['distance_m']), (dict(lat=51.0, lon=3.7), 0.0))
        self.s.ingest(gps(51.001, 3.7, seq=2), 2)  # about 111 m north
        snap = self.s.snapshot(2.1)['gps']
        self.assertAlmostEqual(snap['distance_m'], 111.2, delta=0.5)
        self.assertAlmostEqual(snap['bearing_deg'], 0, delta=0.1)

    def test_pilot_position_becomes_home_when_the_radio_has_one(self):
        self.s.ingest(gps(51.001, 3.7, 51.0, 3.7), 1)
        self.assertEqual(self.s.snapshot(1.1)['gps']['home'], dict(lat=51.0, lon=3.7))

    def test_no_fix_zero_zero_is_ignored(self):
        self.s.ingest(gps(0, 0), 1)
        snap = self.s.snapshot(1.1)['gps']
        self.assertEqual((snap['fix'], snap['lat'], snap['home'], snap['track_points']), (False, None, None, 0))

    def test_fix_goes_stale(self):
        self.s.ingest(gps(51.0, 3.7), 1)
        self.assertTrue(self.s.snapshot(3.5)['gps']['fix'])
        snap = self.s.snapshot(5)['gps']
        self.assertFalse(snap['fix'])
        self.assertEqual(snap['lat'], 51.0, 'the last position is still reported, just not as a live fix')

    def test_track_is_thinned_and_capped(self):
        for k in range(10):  # 0.11 m steps, 1.1 m in total: only the first point is kept
            self.s.ingest(gps(51.0 + k*0.000001, 3.7, seq=k+1), 1)
        self.assertEqual(len(self.s.track), 1)
        self.s.track.clear()
        for k in range(MAX_TRACK_POINTS + 50):  # 5.5 m steps
            self.s.ingest(gps(51.0 + k*0.00005, 3.7, seq=k % 60000 + 1), 1)
        self.assertEqual(len(self.s.track), MAX_TRACK_POINTS)

    def test_usb_reconnect_keeps_the_track_but_a_radio_restart_clears_it(self):
        self.s.ingest(gps(51.0, 3.7), 1)
        self.s.ingest(gps(51.001, 3.7, seq=2), 2)
        self.s.connection(False)
        self.s.connection(True)  # cable bump: the radio kept running
        self.assertEqual((len(self.s.track), self.s.home), (2, (51.0, 3.7)))
        self.s.ingest(parse_line('H,1,DDRAW,5'), 3)
        self.s.ingest(gps(51.5, 3.9, seq=3), 3)  # first record seen after the reconnect
        self.s.ingest(parse_line('H,1,DDRAW,5'), 4)  # the script restarted on the radio
        self.assertEqual((len(self.s.track), self.s.home, self.s.gps), (0, None, None))

    def test_g_records_are_validated(self):
        for bad in ('G,1,1,91.0,0,0,0', 'G,1,1,0,181,0,0', 'G,1,1,nan,0,0,0', 'G,1,1,1e3,0,0,0', 'G,1,1,1,2,3'):
            with self.assertRaises(ValueError):
                parse_line(bad)


class GpsApiTests(ApiCase):
    def test_endpoints(self):
        async def scenario(client, server, tmp):
            idle = await self.call(client, 'GET', '/api/v1/gps', '/api/v1/gps')
            self.assertEqual((idle['fix'], idle['home'], idle['track_points']), (False, None, 0))
            for k in range(4):
                server.pipeline.accept(f'G,200,{50 + k},{51.0 + k*0.0005:.6f},3.700000,0.000000,0.000000')
            g = await self.call(client, 'GET', '/api/v1/gps', '/api/v1/gps')
            self.assertEqual((g['fix'], g['home'], g['track_points']), (True, dict(lat=51.0, lon=3.7), 4))
            self.assertGreater(g['distance_m'], 150)
            track = await self.call(client, 'GET', '/api/v1/gps/track', '/api/v1/gps/track')
            self.assertEqual(len(track['points']), 4)
            self.assertEqual(track['points'][0], [51.0, 3.7])
            state = await self.call(client, 'GET', '/api/v1/state', '/api/v1/state')
            self.assertTrue(state['gps']['fix'], 'the snapshot carries the position too')
            cleared = await self.call(client, 'DELETE', '/api/v1/gps/track', '/api/v1/gps/track')
            self.assertEqual(cleared, dict(home=None, points=[]))
            self.assertEqual((await self.call(client, 'GET', '/api/v1/gps'))['home'], None)
        self.run_api(scenario)

    def test_hud_settings_merge_and_validate(self):
        async def scenario(client, server, tmp):
            s = await self.call(client, 'GET', '/api/v1/settings', '/api/v1/settings')
            self.assertEqual(s['hud'], DEFAULTS['hud'])
            r = await self.call(client, 'PATCH', '/api/v1/settings', '/api/v1/settings',
                                json=dict(hud=dict(layout='row', cells=6, map=dict(provider='none'))))
            self.assertEqual((r['hud']['layout'], r['hud']['cells'], r['hud']['map']['provider']), ('row', 6, 'none'))
            self.assertEqual(r['hud']['map']['zoom'], 'auto', 'untouched map settings survive')
            r = await self.call(client, 'PATCH', '/api/v1/settings', json=dict(hud=dict(blocks=dict(gps=False), style='hacker')))
            self.assertEqual((r['hud']['blocks'], r['hud']['layout']), (dict(link=True, battery=True, gps=False, status=True), 'row'))
            r = await self.call(client, 'PATCH', '/api/v1/settings', json=dict(hud=dict(style=None)))
            self.assertIsNone(r['hud']['style'])
            for bad in (dict(layout='diagonal'), dict(cells=12), dict(map=dict(provider='bing')),
                        dict(map=dict(customUrl='http://evil.example/{z}/{x}/{y}.png')), dict(blocks=dict(map=True))):
                err = await self.call(client, 'PATCH', '/api/v1/settings', status=400, json=dict(hud=bad))
                self.assertEqual(err['error']['code'], 'invalid_settings')
            full = copy.deepcopy(DEFAULTS); full['hud']['cells'] = 3
            r = await self.call(client, 'PUT', '/api/v1/settings', '/api/v1/settings', json=full)
            self.assertEqual(r['hud']['cells'], 3)
            partial = {k: v for k, v in full.items() if k != 'hud'}
            err = await self.call(client, 'PUT', '/api/v1/settings', status=400, json=partial)
            self.assertIn('hud', err['error']['message'])
        self.run_api(scenario)

    def test_sensor_names_with_percent_sign(self):
        async def scenario(client, server, tmp):
            server.pipeline.accept('T,10,40,Bat%,87.000,1,1')
            s = await self.call(client, 'GET', '/api/v1/telemetry/Bat%25', '/api/v1/telemetry/{sensor}')
            self.assertEqual((s['name'], s['value']), ('Bat%', 87.0))
        self.run_api(scenario)


if __name__ == '__main__':
    unittest.main()
