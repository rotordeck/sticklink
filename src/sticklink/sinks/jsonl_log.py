"""Append-only JSONL session log.

Line 1 of a new file is a header. After that each line is either
  {received_monotonic_ns, received_unix_ns, session, record}   parsed DDLOG record
  {received_monotonic_ns, received_unix_ns, session, connection: {connected, message}}
"""
import json
import time

from .. import __version__

FORMAT = 'sticklink-log'
VERSION = 1


class JsonlLog:
    def __init__(self, path, config=None, source=''):
        self.path = path
        self.records = 0
        self.started = time.time()
        # Line buffered: a crash loses at most the line being written.
        self.file = open(path, 'a', encoding='utf-8', buffering=1)
        if self.file.tell() == 0:
            self._write(dict(format=FORMAT, version=VERSION,
                sticklink=__version__, source=source,
                config=vars(config) if config else None,
                started_unix_ns=time.time_ns()))

    def _write(self, obj):
        self.file.write(json.dumps(obj, allow_nan=False)+'\n')

    def _stamped(self, session, **body):
        return dict(received_monotonic_ns=time.monotonic_ns(),
                    received_unix_ns=time.time_ns(), session=session, **body)

    def record(self, record, session):
        self.records += 1
        self._write(self._stamped(session, record=record))

    def connection(self, connected, message, session):
        self.records += 1
        self._write(self._stamped(session,
            connection=dict(connected=connected, message=message)))

    def close(self):
        self.file.close()
