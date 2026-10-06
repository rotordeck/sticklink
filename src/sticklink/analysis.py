"""check-log: judge whether a recorded session is good enough data."""
from .sources.replay import read_log

STICKS = ('roll', 'pitch', 'yaw', 'throttle')
CHANNELS = STICKS + ('arm', 'crash')


def percentile(sorted_values, q):
    if not sorted_values:
        return None
    return sorted_values[min(len(sorted_values)-1, int(q*len(sorted_values)))]


def gap_stats(gaps_ms):
    gaps = sorted(gaps_ms)
    return dict(median=percentile(gaps, .5), p95=percentile(gaps, .95),
                p99=percentile(gaps, .99), max=gaps[-1] if gaps else None)


def analyze(path):
    n = dict(records=0, samples=0, events=0, telemetry=0, connections=0, disconnects=0)
    first_mono = last_mono = None
    last_tick = last_seq = last_sample_tick = last_sample_mono = None
    missing = resets = 0
    tick_gaps, host_gaps = [], []
    ranges = {}
    sensors = {}
    sessions = set()
    notes = []
    out_ranges = {}
    for item in read_log(path):
        mono = item['received_monotonic_ns']
        first_mono = mono if first_mono is None else first_mono
        last_mono = mono
        sessions.add(item.get('session'))
        if 'connection' in item:
            n['connections'] += 1
            n['disconnects'] += not item['connection']['connected']
            last_tick = last_seq = last_sample_tick = last_sample_mono = None
            continue
        rec = item['record']
        n['records'] += 1
        tick = rec['tick']
        if last_tick is not None and tick < last_tick:
            resets += 1
            last_seq = last_sample_tick = None
        last_tick = tick
        if rec['type'] == 'H':
            if last_seq is not None:
                resets += 1
            last_seq = last_sample_tick = None
            continue
        step = None if last_seq is None else (rec['seq']-last_seq) % 65536
        if step is not None and step >= 32768:
            resets += 1
            last_sample_tick = None
        elif step:
            missing += step-1
        last_seq = rec['seq']
        if rec['type'] == 'S':
            n['samples'] += 1
            if last_sample_tick is not None:
                tick_gaps.append((tick-last_sample_tick)*10)  # ticks are 10 ms
                host_gaps.append((mono-last_sample_mono)/1e6)
            last_sample_tick, last_sample_mono = tick, mono
            for name, value in rec['channels'].items():
                lo, hi = ranges.get(name, (value, value))
                ranges[name] = (min(lo, value), max(hi, value))
        elif rec['type'] == 'E':
            n['events'] += 1
        elif rec['type'] == 'D':
            notes.append(rec['message'])
        elif rec['type'] == 'C':
            n['outputs'] = n.get('outputs', 0) + 1
            for k, value in enumerate(rec['outputs']):
                ch = rec['first'] + k
                lo, hi = out_ranges.get(ch, (value, value))
                out_ranges[ch] = (min(lo, value), max(hi, value))
        else:
            n['telemetry'] += 1
            s = sensors.setdefault(rec['sensor'], dict(count=0, current=0,
                first=mono, last=mono, lo=rec['value'], hi=rec['value']))
            s['count'] += 1
            s['current'] += rec['current']
            s['last'] = mono
            s['lo'], s['hi'] = min(s['lo'], rec['value']), max(s['hi'], rec['value'])
    duration = 0 if first_mono is None else (last_mono-first_mono)/1e9
    for s in sensors.values():
        span = (s['last']-s['first'])/1e9
        s['rate_hz'] = (s['count']-1)/span if span > 0 else None
    result = dict(path=str(path), duration_s=duration, counts=n,
        sample_rate_hz=(n['samples']-1)/duration if duration > 0 and n['samples'] > 1 else None,
        radio_gap_ms=gap_stats(tick_gaps), host_gap_ms=gap_stats(host_gaps),
        missing_seq=missing, resets=resets, sessions=len(sessions - {None}),
        stick_range={k: ranges[k] for k in CHANNELS if k in ranges}, telemetry=sensors, radio_notes=notes, output_ranges=out_ranges)
    result['warnings'] = warnings(result)
    return result


def warnings(r):
    out = []
    if r['counts']['samples'] < 2:
        return ['no control samples recorded']
    if r['sample_rate_hz'] < 20:
        out.append(f"average sample rate {r['sample_rate_hz']:.1f} Hz is low (expected ~30 Hz)")
    if r['radio_gap_ms']['p95'] and r['radio_gap_ms']['p95'] > 100:
        out.append(f"95th percentile gap {r['radio_gap_ms']['p95']} ms: stalls in the Lua script")
    if r['missing_seq']:
        out.append(f"{r['missing_seq']} records missing (sequence gaps): serial data lost")
    if r['resets']:
        out.append(f"{r['resets']} radio session resets")
    if not r['telemetry']:
        out.append('no telemetry records: check sensor names in DDSTK.lua')
    for name, (lo, hi) in r['stick_range'].items():
        if lo == hi and name in STICKS:  # switches may legitimately stay put
            out.append(f'{name} never changed ({lo}): wrong source or stick not moved')
    return out


def format_report(r):
    def ms(v):
        return '—' if v is None else f'{v:.1f} ms'
    c = r['counts']
    lines = [f"Log: {r['path']}",
        f"Duration: {r['duration_s']:.1f} s   sessions: {r['sessions']}   "
        f"resets: {r['resets']}   disconnects: {c['disconnects']}",
        f"Records: {c['records']} (control {c['samples']}, events {c['events']}, "
        f"telemetry {c['telemetry']})   missing seq: {r['missing_seq']}"]
    if r['sample_rate_hz']:
        lines.append(f"Control rate: {r['sample_rate_hz']:.1f} Hz")
    for label, key in (('Radio-clock gaps', 'radio_gap_ms'), ('Host-clock gaps ', 'host_gap_ms')):
        g = r[key]
        lines.append(f"{label}: median {ms(g['median'])}, p95 {ms(g['p95'])}, "
                     f"p99 {ms(g['p99'])}, max {ms(g['max'])}")
    lines.append('Channel ranges: ' + (', '.join(
        f'{k} {lo}..{hi}' for k, (lo, hi) in r['stick_range'].items()) or '—'))
    for name, s in sorted(r['telemetry'].items()):
        rate = '—' if s['rate_hz'] is None else f"{s['rate_hz']:.1f} Hz"
        lines.append(f"Telemetry {name}: {s['count']} records, {rate}, "
                     f"range {s['lo']:g}..{s['hi']:g}, current {s['current']}/{s['count']}")
    moved = {ch: rg for ch, rg in sorted(r['output_ranges'].items()) if rg[0] != rg[1]}
    if r['output_ranges']:
        lines.append('Output channels that moved: ' + (', '.join(f'CH{ch} {lo}..{hi}' for ch, (lo, hi) in moved.items()) or 'none'))
    for note in r['radio_notes']:
        lines.append(f'Radio note: {note}')
    lines.append('')
    lines += [f'WARNING: {w}' for w in r['warnings']] or ['OK: no problems found']
    return '\n'.join(lines)
