# PyInstaller recipe: one self-contained executable (bundles its own Python). Build from the repo root:
#   pip install ".[binary]" && pyinstaller packaging/sticklink.spec
# The package must be installed non-editable so its data files (web UI, fonts, Swagger UI, radio script) are collected.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files('sticklink') + collect_data_files('customtkinter')
hiddenimports = collect_submodules('serial') + collect_submodules('sticklink')

import os
import sys

a = Analysis([os.path.join(SPECPATH, 'entry.py')], pathex=[], datas=datas, hiddenimports=hiddenimports, excludes=['unittest.mock'])
pyz = PYZ(a.pure)
# The Rotordeck mark: .ico for the Windows exe, .icns for macOS (Linux ELF files carry no icon).
icon = os.path.join(SPECPATH, {'win32': 'icon.ico', 'darwin': 'icon.icns'}.get(sys.platform, 'icon.png'))
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='sticklink', console=True, upx=False, icon=icon,
          strip=sys.platform.startswith('linux'))  # the CI Linux Python ships an unstripped 30 MB libpython
