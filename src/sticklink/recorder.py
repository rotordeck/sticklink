"""Start/stop session recordings at runtime, and manage the recordings folder.

API-driven recordings only ever live in one directory, under server-generated names, so a client can never choose
a path. (`--log FILE` on the command line is trusted and may point anywhere.)
"""
import os
from pathlib import Path
import re
import time

from .sinks.jsonl_log import JsonlLog

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\.jsonl')
LABEL = re.compile(r'[A-Za-z0-9_-]{1,40}')


def default_dir():
    base = os.environ.get('XDG_DATA_HOME') or Path.home()/'.local'/'share'
    return Path(base)/'sticklink'/'recordings'


class RecorderError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


class Recorder:
    def __init__(self, pipeline, directory=None, source=''):
        self.pipeline = pipeline
        self.dir = Path(directory) if directory else default_dir()
        self.source = source
        self.external = False

    # -- active recording
    @property
    def log(self):
        return self.pipeline.log

    def status(self):
        log = self.log
        if log is None:
            return dict(active=False, name=None, records=0, started_unix=None, external=False)
        return dict(active=True, name=Path(log.path).name, records=log.records,
                    started_unix=round(log.started, 3), external=self.external)

    def start(self, label=None):
        if self.log is not None:
            raise RecorderError('already_recording', 'a recording is already running')
        if label is not None and not LABEL.fullmatch(label):
            raise RecorderError('invalid_label', 'label must match [A-Za-z0-9_-]{1,40}')
        self.dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        base = f'{stamp}-{label}' if label else stamp
        name, n = f'{base}.jsonl', 1
        while (self.dir/name).exists():
            n += 1
            name = f'{base}-{n}.jsonl'
        self.external = False
        self.pipeline.log = JsonlLog(str(self.dir/name), self.pipeline.config, self.source)
        return self.status()

    def start_path(self, path):
        """Command-line `--log`: a trusted, arbitrary path."""
        self.external = True
        self.pipeline.log = JsonlLog(path, self.pipeline.config, self.source)

    def stop(self):
        log = self.log
        if log is None:
            raise RecorderError('not_recording', 'no recording is running')
        info = dict(self.status(), active=False)  # the recording that was just stopped
        self.pipeline.log = None
        log.close()
        return info

    def close(self):
        if self.log is not None:
            self.stop()

    # -- recordings folder
    def _path(self, name):
        if not NAME.fullmatch(name):
            raise RecorderError('invalid_name', 'invalid recording name')
        path = self.dir/name
        if not path.is_file():
            raise RecorderError('not_found', 'no such recording')
        return path

    def list(self):
        if not self.dir.is_dir():
            return []
        out = []
        for path in self.dir.iterdir():
            if NAME.fullmatch(path.name) and path.is_file():
                st = path.stat()
                out.append(dict(name=path.name, size_bytes=st.st_size, modified_unix=round(st.st_mtime, 3),
                                active=self.log is not None and not self.external and Path(self.log.path) == path))
        return sorted(out, key=lambda r: r['name'], reverse=True)

    def path_for(self, name):
        return self._path(name)

    def delete(self, name):
        path = self._path(name)
        if self.log is not None and Path(self.log.path) == path:
            raise RecorderError('recording_active', 'stop the recording before deleting it')
        path.unlink()
