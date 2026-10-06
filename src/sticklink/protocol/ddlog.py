"""DDLOG protocol v1: ASCII lines written by the radio's Lua script.

    H,1,DDRAW,100                    hello (logger id, tick)
    S,tick,seq,roll,pitch,yaw,thr,arm,crash
    E,tick,seq,ARM|CRASH,0|1
    T,tick,seq,sensor,value,current,fresh
    D,tick,seq,text                  radio-side diagnostics (shown by check-log)
    C,tick,seq,first,v1,...,v8       mixer outputs first..first+7 (first = 1 or 9), for setup/learn screens
    G,tick,seq,lat,lon,plat,plon     GPS position and pilot position in decimal degrees (0,0 = none)
"""
import math
import re

MAX_LINE = 512
NAME = re.compile(r'[A-Za-z0-9_-]{1,24}')
SENSOR_NAME = re.compile(r'[A-Za-z0-9_%-]{1,24}')  # EdgeTX names include e.g. `Bat%`
DEGREES = re.compile(r'-?\d{1,3}(\.\d{1,10})?')
CHANNELS = ('roll', 'pitch', 'yaw', 'throttle', 'arm', 'crash')
OUTPUTS = 16
OUTPUT_CHUNK = 8


class LineFramer:
    """Keep fragmented reads; discard oversized records through their newline."""
    def __init__(self):
        self.buffer = bytearray()
        self.discarding = False
        self.dropped = 0

    def feed(self, data: bytes):
        lines = []
        for byte in data:
            if byte == 10:
                if not self.discarding and self.buffer:
                    try:
                        lines.append(self.buffer.decode('ascii').rstrip('\r'))
                    except UnicodeDecodeError:
                        self.dropped += 1
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                self.buffer.append(byte)
                if len(self.buffer) > MAX_LINE:
                    self.buffer.clear()
                    self.discarding = True
                    self.dropped += 1
        return lines


def integer(value, low, high):
    if not re.fullmatch(r'-?\d+', value):
        raise ValueError('integer required')
    number = int(value)
    if not low <= number <= high:
        raise ValueError('out of range')
    return number


def degrees(value, limit):
    if not DEGREES.fullmatch(value):
        raise ValueError('decimal degrees required')
    number = float(value)
    if abs(number) > limit:
        raise ValueError('out of range')
    return number


def parse_line(line: str):
    if len(line) > MAX_LINE:
        raise ValueError('record too long')
    p = line.split(',')
    kind = p[0]
    if kind == 'H' and len(p) == 4:
        if p[1] != '1' or not NAME.fullmatch(p[2]):
            raise ValueError('unsupported hello')
        return dict(type='H', logger=p[2], tick=integer(p[3], 0, 2**32-1))
    if kind not in {'S', 'E', 'T', 'C', 'D', 'G'}:
        raise ValueError('unknown record')
    expected = {'S': 9, 'E': 5, 'T': 7, 'C': 4+OUTPUT_CHUNK, 'D': 4, 'G': 7}[kind]
    if len(p) != expected:
        raise ValueError('wrong field count')
    result = dict(type=kind, tick=integer(p[1], 0, 2**32-1),
                  seq=integer(p[2], 0, 65535))
    if kind == 'S':
        result['channels'] = dict(zip(
            CHANNELS, (integer(v, -2048, 2048) for v in p[3:])))
    elif kind == 'D':
        if not re.fullmatch(r'[A-Za-z0-9 _.:-]{0,60}', p[3]):
            raise ValueError('invalid diagnostic text')
        result['message'] = p[3]
    elif kind == 'G':
        lat, lon, plat, plon = degrees(p[3], 90), degrees(p[4], 180), degrees(p[5], 90), degrees(p[6], 180)
        result.update(lat=lat, lon=lon, plat=plat, plon=plon)
    elif kind == 'C':
        first = integer(p[3], 1, OUTPUTS-OUTPUT_CHUNK+1)
        if first not in (1, 1+OUTPUT_CHUNK):
            raise ValueError('output chunk must start at 1 or 9')
        result.update(first=first, outputs=[integer(v, -2048, 2048) for v in p[4:]])
    elif kind == 'E':
        if p[3] not in {'ARM', 'CRASH'}:
            raise ValueError('unknown event')
        result.update(event=p[3], value=integer(p[4], 0, 1))
    else:
        if not SENSOR_NAME.fullmatch(p[3]):
            raise ValueError('invalid sensor name')
        value = float(p[4])
        if not math.isfinite(value):
            raise ValueError('finite telemetry required')
        result.update(sensor=p[3], value=value,
                      current=bool(integer(p[5], 0, 1)),
                      fresh=bool(integer(p[6], 0, 1)))
    return result
