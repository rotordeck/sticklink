import asyncio
import json
import os
import tempfile
import unittest

from sticklink.analysis import analyze, format_report
from sticklink.config import Config
from sticklink.pipeline import Pipeline
from sticklink.sinks.jsonl_log import JsonlLog
from sticklink.sources.replay import ReplaySource, read_log

LINES = ['H,1,DDRAW,0',
         'S,100,1,100,0,0,-1024,1024,-1024',
         'T,100,2,RQly,100,1,1',
         'S,103,3,200,50,-50,-900,1024,-1024',
         'E,105,4,CRASH,1',
         'S,106,5,300,60,-60,-800,1024,1024',
         'T,108,6,RxBt,4.1,1,1',
         'C,108,6,1,'+','.join(['0']*8),
         'G,108,6,51.0543,3.7174,0,0',
         'S,109,9,400,70,-70,-700,1024,1024']  # seq 7..8 lost


def record_session(path):
    log = JsonlLog(path, Config(), 'test')
    pipe = Pipeline(Config(), log)
    pipe.connection(True)
    for line in LINES:
        pipe.accept(line)
    log.close()
    return pipe


class LogTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, 'session.jsonl')

    def tearDown(self):
        self.dir.cleanup()

    def test_header_written_once_and_records_roundtrip(self):
        record_session(self.path)
        record_session(self.path)  # appending must not add a second header
        with open(self.path) as f:
            lines = [json.loads(line) for line in f]
        headers = [x for x in lines if x.get('format') == 'sticklink-log']
        self.assertEqual(len(headers), 1)
        self.assertEqual(headers[0]['version'], 1)
        self.assertEqual(len(list(read_log(self.path))), 2*(len(LINES)+1))

    def test_torn_last_line_is_ignored(self):
        record_session(self.path)
        with open(self.path, 'a') as f:
            f.write('{"received_monotonic_ns": 5, "rec')
        self.assertEqual(len(list(read_log(self.path))), len(LINES)+1)

    def test_analyze_reports_gaps_and_ranges(self):
        record_session(self.path)
        r = analyze(self.path)
        self.assertEqual(r['counts']['samples'], 4)
        self.assertEqual(r['missing_seq'], 2)
        self.assertEqual(r['resets'], 0)
        self.assertEqual(r['stick_range']['roll'], (100, 400))
        self.assertEqual(r['radio_gap_ms']['max'], 30)
        self.assertEqual(set(r['telemetry']), {'RQly', 'RxBt'})
        self.assertTrue(any('missing' in w for w in r['warnings']))
        self.assertIn('Telemetry RQly', format_report(r))
        self.assertEqual(r['output_ranges'][1], (0, 0))
        self.assertEqual(r['counts']['gps'], 1)
        self.assertIn('GPS records: 1', format_report(r))

    def test_analyze_warns_without_telemetry_or_motion(self):
        pipe = Pipeline(Config(), JsonlLog(self.path))
        pipe.connection(True)
        for i in range(5):
            pipe.accept(f'S,{100+3*i},{i+1},0,0,0,0,0,0')
        pipe.log.close()
        w = ' '.join(analyze(self.path)['warnings'])
        self.assertIn('no telemetry', w)
        self.assertIn('never changed', w)

    def test_very_short_recording_with_identical_timestamps(self):
        # A coarse clock (Windows with Python < 3.13) can stamp every record of a short session the same.
        with open(self.path, 'w') as f:
            for k, line in enumerate(LINES):
                from sticklink.protocol import parse_line
                f.write(json.dumps(dict(received_monotonic_ns=1000, received_unix_ns=1, session=1,
                                        record=parse_line(line))) + '\n')
        r = analyze(self.path)
        self.assertEqual(r['duration_s'], 0)
        self.assertIsNone(r['sample_rate_hz'])
        self.assertIn('Control rate', format_report(r) + 'Control rate')  # formatting must not raise either
        self.assertTrue(any('missing' in w for w in r['warnings']))

    def test_replay_reproduces_state(self):
        live = record_session(self.path)
        replayed = Pipeline(Config())

        async def go():
            task = asyncio.create_task(ReplaySource(self.path, speed=1000).run(replayed))
            await asyncio.sleep(0.2)
            task.cancel()
        asyncio.run(go())
        a, b = live.state, replayed.state
        self.assertEqual((a.samples, a.missing, a.resets), (b.samples, b.missing, b.resets))
        self.assertEqual(a.controls, b.controls)
        self.assertEqual(set(a.telemetry), set(b.telemetry))
        self.assertEqual(a.crash, b.crash)


class RadioScriptTests(unittest.TestCase):
    def test_radio_script_is_packaged_and_copyable(self):
        from sticklink.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            main(['radio-script', tmp])
            copied = open(os.path.join(tmp, 'DDSTK.lua'), encoding='utf-8').read()
        self.assertIn('return { init=init, run=run', copied)
        self.assertLessEqual(len('DDSTK'), 6, 'EdgeTX function script names are limited to 6 characters')
        with self.assertRaises(SystemExit):
            main(['radio-script', '/definitely/not/a/folder'])


if __name__ == '__main__':
    unittest.main()
