import asyncio
import json
import time

from .base import Source


def read_log(path):
    """Yield decoded log lines; skip the header and tolerate a torn last line."""
    with open(path, encoding='utf-8') as f:
        for line in f:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict) and 'received_monotonic_ns' in obj:
                yield obj


class ReplaySource(Source):
    """Feed a recorded session back through the pipeline at its original pace."""

    def __init__(self, path, speed=1.0, loop=False):
        self.path, self.speed, self.loop = path, speed, loop
        self.label = f'replay:{path}'

    async def run(self, pipeline):
        while True:
            origin = wall = None
            pipeline.connection(True)  # logs without connection events still go live
            for item in read_log(self.path):
                at = item['received_monotonic_ns']
                if origin is None:
                    origin, wall = at, time.monotonic()
                delay = wall+(at-origin)/1e9/self.speed-time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                if 'record' in item:
                    pipeline.accept_record(item['record'])
                elif 'connection' in item:
                    pipeline.connection(item['connection']['connected'],
                                        item['connection'].get('message', ''))
            if not self.loop:
                print('Replay finished.', flush=True)
                await asyncio.Event().wait()  # keep serving the last state
            await asyncio.sleep(0.5)
