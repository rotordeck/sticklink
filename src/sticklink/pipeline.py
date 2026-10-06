"""Glue between sources (radio, demo, replay), state and sinks (log)."""
from .config import Config
from .protocol import parse_line
from .state import RadioState


class Pipeline:
    """Sources call connection()/accept(); everything else hangs off here."""

    def __init__(self, config: Config | None = None, log=None):
        self.config = config or Config()
        self.state = RadioState(self.config)
        self.log = log

    def connection(self, connected, message=''):
        self.state.connection(connected, message)
        if self.log:
            self.log.connection(connected, message, self.state.session)

    def accept(self, line):
        try:
            record = parse_line(line)
        except (ValueError, OverflowError):
            self.state.invalid += 1
            return
        self.accept_record(record)

    def accept_record(self, record):
        self.state.ingest(record)
        if self.log:
            self.log.record(record, self.state.session)

    def snapshot(self):
        return self.state.snapshot()
