import asyncio
import math
import time

from .base import Source


HOME = (51.054300, 3.717400)


def telemetry(t, thr):
    """Plausible values for every sensor an ELRS + Betaflight quad sends (names as EdgeTX shows them)."""
    load = (thr + 1024) / 2048  # 0..1, from the demo throttle
    volts = 4.18*4 - 0.9*load - (t % 600)/600*0.9  # a 4S pack that sags under load and drains slowly
    amps = 3 + 55*load
    used = (t * 6.5) % 1800
    return [('RQly', round(max(60, 99 - 6*abs(math.sin(t*0.13)) - 20*max(0, math.sin(t*0.05)-0.93)))), ('RSNR', round(11 + 6*math.sin(t*0.4))),
            ('1RSS', round(-58 - 8*math.sin(t*0.3))), ('2RSS', round(-61 - 9*math.sin(t*0.27))),
            ('TPWR', 250), ('RFMD', 7), ('ANT', 0 if int(t) % 8 < 4 else 1), ('TRSS', round(-66 - 5*math.sin(t*0.2))),
            ('TQly', 100), ('TSNR', round(9 + 4*math.sin(t*0.3))),
            ('RxBt', round(volts, 2)), ('Curr', round(amps, 1)), ('Capa', round(used)), ('Bat%', max(0, round(100 - used/1800*100))),
            ('Sats', 14), ('GSpd', round(8 + 40*load, 1)), ('Alt', round(35 + 25*math.sin(t*0.2), 1)), ('VSpd', round(5*math.cos(t*0.2), 1)),
            ('Hdg', round((t*20) % 360, 1)), ('Ptch', round(0.2*math.sin(t*0.7), 3)), ('Roll', round(0.3*math.sin(t*0.9), 3)),
            ('Yaw', round(((t*0.3) % 6.28) - 3.14, 3))]


class DemoSource(Source):
    """Synthetic sticks, ARM/flip switches and telemetry. No radio needed."""
    label = 'demo'

    async def run(self, pipeline):
        pipeline.connection(True)
        pipeline.accept('H,1,DDRAW,0')
        started = time.monotonic()
        seq = 0

        def emit(t, kind, *fields):
            nonlocal seq
            seq = (seq+1) % 65536
            pipeline.accept(','.join(map(str, (kind, int(t*100), seq, *fields))))

        while True:
            t = time.monotonic()-started
            roll, pitch = int(math.sin(t*1.9)*850), int(math.cos(t*1.4)*700)
            yaw, thr = int(math.sin(t*0.9)*700), int(-250+math.sin(t*0.6)*650)
            arm = 1024 if t % 16 > 2 else -1024
            c = t % 16  # race timer: start tap, two lap taps, then a double tap to stop (the result stays until the next start tap)
            tap = any(a < c < a + 0.15 for a in (4, 7.4, 11.2, 13, 13.3))
            flip = 1024 if tap else -1024
            emit(t, 'S', roll, pitch, yaw, thr, arm, flip)
            if int(t*30) % 3 == 0:  # CH1-4 = A E T R like the FPV DRONE model, CH5 arm, CH8 flip
                outputs = [roll, pitch, thr, yaw, arm, 0, 0, flip] + [0]*8
                emit(t, 'C', 1, *outputs[:8])
                emit(t, 'C', 9, *outputs[8:])
            if int(t*30) % 6 == 0:
                for name, value in telemetry(t, thr):
                    emit(t, 'T', name, value, 1, 1)
            if int(t*30) % 15 == 0:  # GPS about 2 Hz: a lazy circle around a fixed spot, pilot position unknown
                lat = HOME[0] + 0.0012*math.sin(t*0.35)
                lon = HOME[1] + 0.0018*math.sin(t*0.35)*math.cos(t*0.35) + 0.0006*math.sin(t*0.9)
                emit(t, 'G', f'{lat:.6f}', f'{lon:.6f}', '0', '0')
            await asyncio.sleep(0.03)
