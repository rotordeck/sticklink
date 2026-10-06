import unittest
from sticklink.config import Config
from sticklink.protocol import LineFramer, parse_line
from sticklink.state import RadioState


class ProtocolTests(unittest.TestCase):
    def test_fragments_and_oversize_recovery(self):
        f = LineFramer()
        self.assertEqual(f.feed(b'S,10,1,0,'), [])
        self.assertEqual(f.feed(b'0,0,-1024,-1024,-1024\r\n'),
                         ['S,10,1,0,0,0,-1024,-1024,-1024'])
        self.assertEqual(f.feed(b'x'*600+b'\nH,1,DDRAW,11\n'), ['H,1,DDRAW,11'])
        self.assertEqual(f.dropped, 1)

    def test_rejects_bad_input(self):
        for value in ['S,1,1,0,0,0,0,0', 'T,1,1,RQly,nan,1,1',
                      'T,1,1,RQly,inf,1,1', 'H,2,DDLOG,1',
                      'S,1,65536,0,0,0,0,0,0', 'E,1,1,ARM,2',
                      'S,1,1,0,0,0,0,0,9999']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_line(value)

    def test_sample_semantics_and_stale(self):
        s = RadioState(Config())
        s.connection(True)
        s.ingest(parse_line('S,100,1,1024,-512,0,-1024,1024,-1024'), 1)
        frame = s.snapshot(1.1)
        self.assertEqual(frame['controls'], dict(roll=1, pitch=-.5, yaw=0, throttle=-1))
        self.assertEqual(frame['commands'], dict(arm=True, crash=False))
        frame = s.snapshot(1.6)
        self.assertEqual(frame['status'], 'paused')
        self.assertIsNone(frame['controls'])
        self.assertIsNone(frame['commands']['arm'])

    def test_sequence_wrap_gap_and_restart(self):
        s = RadioState(Config())
        s.connection(True)
        for tick, seq in [(100,65535),(103,0),(106,3)]:
            s.ingest(parse_line(f'S,{tick},{seq},0,0,0,0,0,0'),1)
        self.assertEqual(s.missing,2)
        s.ingest(parse_line('S,2,1,0,0,0,0,0,0'),2)
        self.assertEqual(s.missing,2)
        self.assertEqual(s.resets,1)

    def test_reconnect_clears_state_and_telemetry_freshness(self):
        s = RadioState(Config())
        s.connection(True)
        s.ingest(parse_line('T,1,1,RQly,100,1,1'),1)
        self.assertTrue(s.snapshot(1.1)['telemetry']['RQly']['current'])
        self.assertFalse(s.snapshot(2.6)['telemetry']['RQly']['current'])
        s.ingest(parse_line('T,2,2,RQly,100,0,0'),2.7)
        self.assertFalse(s.snapshot(2.7)['telemetry']['RQly']['current'])
        s.connection(False)
        self.assertEqual(s.snapshot(3)['telemetry'],{})
        s.connection(True)
        self.assertIsNone(s.snapshot(3)['controls'])

    def test_explicit_hello_resets_even_without_tick_rollback(self):
        s = RadioState(Config())
        s.connection(True)
        s.ingest(parse_line('S,100,1,0,0,0,0,0,0'),1)
        s.ingest(parse_line('H,1,DDRAW,100'),1.1)
        self.assertIsNone(s.snapshot(1.1)['controls'])
        self.assertEqual(s.logger,'DDRAW')

    def test_output_channels_in_two_chunks_and_aging(self):
        low = 'C,100,1,1,' + ','.join(str(v) for v in range(-8, 0))
        high = 'C,101,2,9,' + ','.join(str(v) for v in range(0, 8))
        s = RadioState(Config())
        s.connection(True)
        s.ingest(parse_line(low), 1)
        self.assertIsNone(s.snapshot(1.1)['channels'], 'needs both halves')
        s.ingest(parse_line(high), 1.1)
        self.assertEqual(s.snapshot(1.2)['channels'], list(range(-8, 8)))
        self.assertIsNone(s.snapshot(2.5)['channels'])
        for bad in ['C,1,1,1,' + ','.join(['0']*7), 'C,1,1,1,' + ','.join(['9999']*8),
                    'C,1,1,5,' + ','.join(['0']*8), 'C,1,1,17,' + ','.join(['0']*8)]:
            with self.assertRaises(ValueError):
                parse_line(bad)

    def test_snapshot_exposes_raw_sticks_only_while_live(self):
        s = RadioState(Config())
        s.connection(True)
        s.ingest(parse_line('S,100,1,512,-512,0,-1024,1024,-1024'), 1)
        self.assertEqual(s.snapshot(1.1)['raw']['roll'], 512)
        self.assertIsNone(s.snapshot(1.6)['raw'])

    def test_radio_diagnostics_record(self):
        s = RadioState(Config())
        s.connection(True)
        s.ingest(parse_line('D,1,1,send attempt to index a nil value'), 1)
        self.assertEqual(s.snapshot(1.1)['notes'], ['send attempt to index a nil value'])
        for bad in ['D,1,2,has,comma', 'D,1,2,bad\x01char', 'D,1,2,' + 'x'*61]:
            with self.assertRaises(ValueError):
                parse_line(bad)


if __name__ == '__main__':
    unittest.main()
