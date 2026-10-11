"""Pack the one-folder Windows build into a Microsoft Store package. On Windows, from the repo root:
    set STICKLINK_ONEDIR=1 && pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/sticklink.spec
    python packaging/msix/make_msix.py dist/sticklink OUTPUT.msix

Needs makeappx.exe from the Windows SDK (found on PATH or under Windows Kits\\10\\bin). The package is unsigned:
upload it in Partner Center, which signs it. Installing it locally needs your own signature (signtool).
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def store_version(version):
    """0.1.3 -> 0.1.3.0; a pre-release suffix is dropped. The Store reserves the fourth part, so it stays 0."""
    parts = re.match(r'(\d+)\.(\d+)\.(\d+)', version)
    if not parts:
        raise SystemExit(f'cannot make a package version from {version!r}')
    return '.'.join(parts.groups()) + '.0'


def makeappx():
    found = shutil.which('makeappx')
    if found:
        return found
    kits = os.path.join(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'), 'Windows Kits', '10', 'bin')
    candidates = sorted(glob.glob(os.path.join(kits, '10.*', 'x64', 'makeappx.exe')))
    if not candidates:
        raise SystemExit('makeappx.exe not found: install the Windows SDK')
    return candidates[-1]


def main(build_dir, output):
    sys.path.insert(0, os.path.join(HERE, '..', '..', 'src'))
    from sticklink import __version__
    version = store_version(__version__)
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(build_dir, os.path.join(tmp, 'sticklink'))
        shutil.copytree(os.path.join(HERE, 'Assets'), os.path.join(tmp, 'Assets'))
        with open(os.path.join(HERE, 'AppxManifest.xml'), encoding='utf-8') as f:
            manifest = f.read().replace('{VERSION}', version)
        with open(os.path.join(tmp, 'AppxManifest.xml'), 'w', encoding='utf-8') as f:
            f.write(manifest)
        subprocess.run([makeappx(), 'pack', '/o', '/d', tmp, '/p', output], check=True)
    print(f'built {output} (version {version})')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
