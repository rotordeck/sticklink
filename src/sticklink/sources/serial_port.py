import asyncio

from ..protocol import LineFramer
from .base import Source


class SerialSource(Source):
    """Read-only reader for the radio's USB-VCP stream; reconnects every 2 s."""

    def __init__(self, port, baud=115200):
        self.port, self.baud = port, baud
        self.label = f'serial:{port}'

    async def run(self, pipeline):
        import serial
        while True:
            port = None
            try:
                # No writes to the radio. Read timeout bounds shutdown latency.
                port = serial.Serial(self.port, self.baud, timeout=0.1)
                framer = LineFramer()
                pipeline.connection(True)
                print(f'Connected: {self.port}', flush=True)
                while True:
                    data = await asyncio.to_thread(
                        port.read, max(1, min(port.in_waiting, 4096)))
                    before = framer.dropped
                    for line in framer.feed(data):
                        pipeline.accept(line)
                    pipeline.state.invalid += framer.dropped-before
            except (serial.SerialException, OSError) as exc:
                pipeline.connection(False, str(exc))
                print(f'Radio disconnected: {exc}; retrying in 2s', flush=True)
            finally:
                if port is not None:
                    port.close()
            await asyncio.sleep(2)
