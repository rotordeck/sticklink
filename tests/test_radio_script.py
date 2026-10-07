"""Runs the real DDSTK.lua under a desktop Lua interpreter against a mocked EdgeTX API, and feeds every line it
writes to the real parser. Skipped when no `lua` is installed (CI installs it for this test)."""
import collections
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from sticklink.protocol import parse_line

SCRIPT = Path(__file__).resolve().parent.parent/'src'/'sticklink'/'radio'/'DDSTK.lua'
LUA = next((p for p in (shutil.which(n) for n in ('lua', 'lua5.4', 'lua5.3', 'lua5.2', 'luajit')) if p), None)

MOCK = r'''
local mode, script = arg[1], arg[2]
local known = { RQly=1, RSNR=1, ["1RSS"]=1, ["2RSS"]=1, TPWR=1, RFMD=1, ANT=1, TRSS=1, TSNR=1, RxBt=1, Curr=1,
                ["Bat%"]=1, Sats=1, GSpd=1, Alt=1, Ptch=1, Roll=1, Yaw=1, GPS=1 }   -- this radio never discovered Capa, GAlt, ...
local ids, nextid, out, t = {}, 100, {}, 0
function getTime() return t end
function getFieldInfo(n)
  if mode == "resolve-boom" and n == "Sats" then error("simulated lookup failure") end
  if n:match("^ch%d+$") or n == "ail" or n == "ele" or n == "rud" or n == "thr" then return { id = #n * 7 + (tonumber(n:match("%d+")) or 0) } end
  if known[n] then if not ids[n] then ids[n] = nextid; nextid = nextid + 1 end; return { id = ids[n], name = n } end
  return nil
end
local function nameOf(id) for n, i in pairs(ids) do if i == id then return n end end end
function getSourceValue(id)
  local n = nameOf(id)
  if mode == "sensor-boom" and n == "Curr" then error("simulated sensor failure") end
  if mode == "tap" and id == 30 then return (t >= 1010 and t < 1020) and 1024 or -1024, true, true end  -- ch9: a 100 ms tap
  if n == "Bat%" then return 87, true, true end
  if n == "RxBt" then return 16.0999999046325, true, true end
  if n == "Alt" then return 35.2000007629395, true, false end
  return (id % 7) * 10 - 40, true, true
end
function getValue(id)
  if nameOf(id) == "GPS" then
    if mode == "gps-boom" then return { lat = "bad", lon = 3 } end
    return { lat = 51.054321, lon = 3.717424, ["pilot-lat"] = 0, ["pilot-lon"] = 0 }
  end
  return getSourceValue(id)
end
if mode == "no-format" then string.format = nil end
function serialWrite(s) out[#out + 1] = s end
local m = dofile(script)
m.init()
for _ = 1, 400 do t = t + 5; m.run() end
io.write(table.concat(out))
'''


@unittest.skipUnless(LUA, 'no lua interpreter installed')
class RadioScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.mock = Path(cls.tmp.name)/'mock.lua'
        cls.mock.write_text(MOCK)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_mode(self, mode):
        run = subprocess.run([LUA, str(self.mock), mode, str(SCRIPT)], capture_output=True, text=True, timeout=60)
        self.assertEqual((run.returncode, run.stderr), (0, ''), run.stderr)
        records = [parse_line(line) for line in run.stdout.splitlines()]  # every line must be valid DDLOG
        kinds = collections.Counter(r['type'] for r in records)
        return records, kinds, max(map(len, run.stdout.splitlines()))

    def test_normal_run(self):
        records, kinds, longest = self.run_mode('ok')
        self.assertEqual((kinds['H'], kinds['S'], kinds['C'], kinds['G']), (1, 400, 200, 40))
        self.assertEqual(kinds['T'], 800, 'two sensors per call, every call')
        sensors = {r['sensor'] for r in records if r['type'] == 'T'}
        self.assertEqual(sensors, {'RQly', 'RSNR', '1RSS', '2RSS', 'TPWR', 'RFMD', 'ANT', 'TRSS', 'TSNR', 'RxBt', 'Curr',
                                   'Bat%', 'Sats', 'GSpd', 'Alt', 'Ptch', 'Roll', 'Yaw'}, 'only discovered sensors are sent')
        self.assertLessEqual(longest, 60, 'long lines overflowed the radio once; keep them short')
        gps = next(r for r in records if r['type'] == 'G')
        self.assertEqual((gps['lat'], gps['lon']), (51.054321, 3.717424))
        note = next(r['message'] for r in records if r['type'] == 'D')
        self.assertIn('channels resolved 16', note)
        self.assertIn('gps', note)

    def test_a_quick_tap_on_an_aux_channel_is_sent_at_once(self):
        records, kinds, _ = self.run_mode('tap')
        ch9 = [(r['tick'], r['outputs'][0]) for r in records if r['type'] == 'C' and r['first'] == 9]
        self.assertTrue(any(1010 <= tick < 1020 and value == 1024 for tick, value in ch9), 'the tap itself')
        self.assertTrue(any(tick >= 1020 and value == -1024 for tick, value in ch9), 'and its release')
        self.assertLessEqual(kinds['C'], 205, 'only a few extra lines for one tap')

    def test_one_failing_sensor_does_not_stop_the_rest(self):
        records, kinds, _ = self.run_mode('sensor-boom')
        sensors = collections.Counter(r['sensor'] for r in records if r['type'] == 'T')
        self.assertNotIn('Curr', sensors)
        self.assertEqual(len(sensors), 17)
        self.assertEqual((kinds['S'], kinds['C'], kinds['G'], kinds['T']), (400, 200, 40, 800))
        self.assertTrue(any('sensor Curr' in r['message'] for r in records if r['type'] == 'D'))

    def test_broken_gps_value_is_ignored(self):
        _, kinds, _ = self.run_mode('gps-boom')
        self.assertEqual((kinds['S'], kinds['T'], kinds['G']), (400, 800, 0))

    def test_a_failed_lookup_skips_only_that_sensor_and_is_reported(self):
        records, kinds, _ = self.run_mode('resolve-boom')
        sensors = {r['sensor'] for r in records if r['type'] == 'T'}
        self.assertNotIn('Sats', sensors)
        self.assertEqual(len(sensors), 17)
        self.assertEqual((kinds['S'], kinds['C'], kinds['G'], kinds['T']), (400, 200, 40, 800))
        self.assertTrue(any(r['message'].startswith('lookup Sats') for r in records if r['type'] == 'D'))

    def test_works_without_string_format(self):
        _, kinds, _ = self.run_mode('no-format')
        self.assertEqual((kinds['S'], kinds['T'], kinds['G']), (400, 800, 40))


if __name__ == '__main__':
    unittest.main()
