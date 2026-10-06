import asyncio
import math
import time

from .base import Source


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
            flip = 1024 if 14 < t % 16 < 15 else -1024
            emit(t, 'S', roll, pitch, yaw, thr, arm, flip)
            if int(t*30) % 3 == 0:  # CH1-4 = A E T R like the FPV DRONE model, CH5 arm, CH8 flip
                outputs = [roll, pitch, thr, yaw, arm, 0, 0, flip] + [0]*8
                emit(t, 'C', 1, *outputs[:8])
                emit(t, 'C', 9, *outputs[8:])
            if int(t*30) % 6 == 0:
                emit(t, 'T', 'RQly', 98, 1, 1)
                emit(t, 'T', 'RxBt', round(4.2-(t % 120)/200, 2), 1, 1)
            await asyncio.sleep(0.03)
