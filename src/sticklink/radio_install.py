"""Put DDSTK.lua on a radio's SD card: find the mounted card, work out the right folder, copy the file."""
import os
import shutil
import string
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent/'radio'/'DDSTK.lua'
TARGET = ('SCRIPTS', 'FUNCTIONS')  # where EdgeTX looks for function scripts


def _child(folder, name):
    """A child of `folder` whose name matches `name` ignoring case (FAT cards differ), or None."""
    try:
        for entry in os.scandir(folder):
            if entry.name.lower() == name.lower():
                return Path(entry.path)
    except OSError:
        pass
    return None


def is_radio_card(folder):
    """An EdgeTX / OpenTX SD card has RADIO and MODELS folders (or the EdgeTX version marker) in its root."""
    folder = Path(folder)
    return bool((_child(folder, 'RADIO') and _child(folder, 'MODELS')) or _child(folder, 'edgetx.sdcard.version'))


def mount_points():
    """Where removable drives show up on this system."""
    if sys.platform == 'win32':
        return [Path(f'{letter}:/') for letter in string.ascii_uppercase if Path(f'{letter}:/').exists()]
    user = os.environ.get('USER') or os.environ.get('USERNAME') or ''
    roots = [Path('/run/media')/user, Path('/media')/user, Path('/media'), Path('/mnt'), Path('/Volumes')]
    found = []
    for root in roots:
        try:
            found += [Path(e.path) for e in os.scandir(root) if e.is_dir()]
        except OSError:
            pass
    return found


def find_cards(mounts=None):
    """Mounted radio SD cards. `mounts` is for tests."""
    return [m for m in (mount_points() if mounts is None else mounts) if is_radio_card(m)]


def target_folder(chosen):
    """The folder DDSTK.lua goes into for whatever the user picked: the card root, SCRIPTS, or SCRIPTS/FUNCTIONS itself."""
    chosen = Path(chosen)
    if chosen.name.lower() == TARGET[1].lower() and chosen.parent.name.lower() == TARGET[0].lower():
        return chosen
    if chosen.name.lower() == TARGET[0].lower():
        return (_child(chosen, TARGET[1]) or chosen/TARGET[1])
    scripts = _child(chosen, TARGET[0]) or chosen/TARGET[0]
    return _child(scripts, TARGET[1]) or scripts/TARGET[1]


def install(chosen):
    """Copy DDSTK.lua to the radio card at `chosen`. Returns the file written; raises OSError with a plain message."""
    chosen = Path(chosen)
    if not chosen.is_dir():
        raise OSError(f'{chosen} is not a folder')
    folder = target_folder(chosen)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder/'DDSTK.lua'
        with open(SCRIPT, 'rb') as src, open(dest, 'wb') as out:
            shutil.copyfileobj(src, out)
            out.flush()
            os.fsync(out.fileno())  # the card is often unplugged right after
    except PermissionError as exc:
        raise OSError(f'No permission to write to {folder}. Is the card mounted read-only?') from exc
    return dest
