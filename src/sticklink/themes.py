"""Overlay themes: extra looks for the stick overlay (/fx) and the HUD, added without touching the program.

A theme is data only: a folder with `theme.json` (and optionally font files), or a single `.json` file. It names a built-in style to start
from and changes some of its settings (colours, glow, frame shape, ...). Nothing in a theme is ever executed. See docs/themes.md.
"""
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

SHIPPED = Path(__file__).resolve().parent/'web'/'themes'
ID = re.compile(r'[a-z0-9][a-z0-9_-]{0,39}')
API = 1
CORE = ('clean', 'minimal', 'neon', 'arcade', 'synthwave', 'inferno', 'unicorn', 'hacker')  # ids a theme cannot take
FONT_TYPES = {'.woff', '.woff2', '.ttf'}
MAX_FILES, MAX_BYTES = 20, 5*1024*1024

COLOUR = re.compile(r'#[0-9a-fA-F]{3,8}|(?:rgb|rgba|hsl|hsla)\([0-9 .,%/-]{1,60}\)|[a-zA-Z]{3,20}')
FONT = re.compile(r"[\w\s{}.,'\"-]{1,120}")
LABEL = re.compile(r"[A-Za-z0-9 _:!?.'-]{1,40}")
ENUMS = dict(frame=('circle', 'square', 'brackets', 'none'), dotShape=('circle', 'square'),
             sparkShape=('streak', 'star', 'glyph'), popupStyle=('pop', 'terminal'))
COLOURS = ('ring', 'dot', 'textColor', 'textStroke')           # always a colour (ring may also be 'rainbow')
OPTIONAL_COLOURS = ('plate', 'cross', 'dotRing', 'hot')        # a colour or null
NUMBERS = dict(ringW=(0.005, 0.3), dotR=(0.02, 0.5), glow=(0, 2), bloom=(0, 1.5), trail=(0, 3), trailW=(0.01, 0.6), sparks=(0, 3),
               shock=(0, 2), shake=(0, 0.5), flame=(0, 2), embers=(0, 2), scan=(0, 1), chroma=(0, 0.2), glitch=(0, 2))
INTEGERS = dict(grid=(0, 12))
FLAGS = ('popups', 'stats', 'thrBar', 'labels', 'intro', 'rainbow', 'readout')
STYLE_KEYS = set(ENUMS) | set(COLOURS) | set(OPTIONAL_COLOURS) | set(NUMBERS) | set(INTEGERS) | set(FLAGS) | {'font', 'sparkColors', 'labelMap'}


class ThemeError(ValueError):
    pass


def default_dir():
    base = os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config'
    return Path(base)/'sticklink'/'themes'


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', str(text).lower()).strip('-')[:40]


def safe_name(rel):
    """Plain relative names only: no .., no absolute path, no hidden or odd names."""
    parts = rel.replace('\\', '/').split('/')
    return bool(rel) and all(p not in ('', '.', '..') and not p.startswith('.') and re.fullmatch(r'[\w. @()+-]+', p) for p in parts)


def clean_style(style):
    """Validate the overrides; unknown or malformed settings are errors (a typo should not silently do nothing)."""
    if not isinstance(style, dict):
        raise ThemeError('"style" must be an object')
    out = {}
    for key, value in style.items():
        if key not in STYLE_KEYS:
            raise ThemeError(f'unknown style setting "{key}"')
        if key in ENUMS:
            if value not in ENUMS[key]:
                raise ThemeError(f'"{key}" must be one of {", ".join(ENUMS[key])}')
        elif key in COLOURS + OPTIONAL_COLOURS:
            ok = (value is None and key in OPTIONAL_COLOURS) or (isinstance(value, str) and (COLOUR.fullmatch(value) or (key == 'ring' and value == 'rainbow')))
            if not ok:
                raise ThemeError(f'"{key}" must be a colour like #ff8800 or rgba(255,136,0,0.5)' + (' or null' if key in OPTIONAL_COLOURS else ''))
        elif key in NUMBERS or key in INTEGERS:
            low, high = NUMBERS.get(key) or INTEGERS[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high or (key in INTEGERS and value != int(value)):
                raise ThemeError(f'"{key}" must be a {"whole " if key in INTEGERS else ""}number from {low} to {high}')
        elif key in FLAGS:
            if not isinstance(value, bool):
                raise ThemeError(f'"{key}" must be true or false')
        elif key == 'font':
            if not isinstance(value, str) or not FONT.fullmatch(value) or '{px}' not in value:
                raise ThemeError('"font" must be a CSS font with {px} for the size, e.g. "bold {px}px Orbitron, sans-serif"')
        elif key == 'sparkColors':
            if not isinstance(value, list) or not 1 <= len(value) <= 8 or not all(isinstance(c, str) and COLOUR.fullmatch(c) for c in value):
                raise ThemeError('"sparkColors" must be a list of 1 to 8 colours')
        elif key == 'labelMap':
            if (not isinstance(value, dict) or len(value) > 30
                    or not all(LABEL.fullmatch(k) and isinstance(v, str) and LABEL.fullmatch(v) for k, v in value.items())):
                raise ThemeError('"labelMap" must map popup labels (WASTED, ARMED, ...) to short plain text')
        out[key] = value
    return out


def read_theme(folder_or_file):
    """The cleaned theme described by a folder (theme.json inside) or a .json file. Raises ThemeError saying what is wrong."""
    path = Path(folder_or_file)
    folder = path if path.is_dir() else path.parent
    try:
        data = json.loads((path/'theme.json' if path.is_dir() else path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise ThemeError('theme.json is missing')
    except (ValueError, OSError):
        raise ThemeError('theme.json is not valid JSON')
    if not isinstance(data, dict):
        raise ThemeError('theme.json must be an object')

    def text(key, limit, default=''):
        value = data.get(key, default)
        if not isinstance(value, str) or len(value) > limit or any(c in value for c in '<>\n\r\t'):
            raise ThemeError(f'"{key}" must be plain text of at most {limit} characters')
        return value
    name = text('name', 40)
    if not name.strip():
        raise ThemeError('"name" is required')
    if data.get('api', API) != API:
        raise ThemeError(f'needs theme format {data.get("api")}, this Sticklink speaks {API}')
    base = text('base', 40, 'clean')
    if base not in CORE:
        raise ThemeError(f'"base" must be one of {", ".join(CORE)}')
    fonts = data.get('fonts', [])
    if not isinstance(fonts, list) or len(fonts) > 6:
        raise ThemeError('"fonts" must be a list of up to 6 {"family", "file"} entries')
    clean_fonts = []
    for item in fonts:
        if (not isinstance(item, dict) or set(item) != {'family', 'file'} or not isinstance(item['family'], str) or not re.fullmatch(r"[A-Za-z0-9 _-]{1,40}", item['family'])
                or not isinstance(item['file'], str) or not safe_name(item['file']) or Path(item['file']).suffix.lower() not in FONT_TYPES):
            raise ThemeError('each font needs a "family" (letters, digits, spaces) and a "file" (.woff2, .woff or .ttf)')
        if not path.is_dir() or not (folder/item['file']).is_file():
            raise ThemeError(f'font file "{item["file"]}" not found')
        clean_fonts.append(dict(family=item['family'], file=item['file']))
    return dict(name=name.strip(), author=text('author', 60), description=text('description', 120), version=text('version', 20),
                base=base, style=clean_style(data.get('style', {})), fonts=clean_fonts)


class ThemeStore:
    def __init__(self, user_dir=None, shipped_dir=None):
        self.user_dir = Path(user_dir) if user_dir else default_dir()
        self.shipped_dir = Path(shipped_dir) if shipped_dir else SHIPPED

    def _scan(self, base, source):
        found = {}
        if not base.is_dir():
            return found
        for entry in sorted(base.iterdir()):
            is_file = entry.is_file() and entry.suffix.lower() == '.json'
            theme_id = entry.stem if is_file else entry.name
            if not (is_file or entry.is_dir()) or not ID.fullmatch(theme_id):
                continue
            item = dict(id=theme_id, name=theme_id, author='', description='', version='', base='clean', style={}, fonts=[],
                        source=source, error=None, root=entry if entry.is_dir() else entry.parent)
            try:
                if theme_id in CORE:
                    raise ThemeError(f'"{theme_id}" is the name of a built-in style: rename the folder')
                item.update(read_theme(entry))
            except ThemeError as exc:
                item.update(error=str(exc), style={}, fonts=[])
            found[theme_id] = item
        return found

    def all(self):
        """Every theme by id; yours win over the shipped examples with the same id."""
        found = self._scan(self.shipped_dir, 'example')
        found.update(self._scan(self.user_dir, 'yours'))
        return dict(sorted(found.items()))

    def listing(self):
        """What the pages need: ready-to-use themes (broken ones are listed with their error and no style)."""
        out = []
        for t in self.all().values():
            item = {k: v for k, v in t.items() if k not in ('root', 'fonts')}
            item['fonts'] = [dict(family=f['family'], url=f'/themes/{t["id"]}/file/{f["file"]}') for f in t['fonts']]
            out.append(item)
        return out

    def font_file(self, theme_id, rel):
        """Path of a font file of a working theme, or None."""
        theme = self.all().get(theme_id)
        if theme is None or theme['error'] or not safe_name(rel) or rel not in {f['file'] for f in theme['fonts']}:
            return None
        root = theme['root'].resolve()
        path = (root/rel).resolve()
        return path if root in path.parents and path.is_file() else None

    def install(self, source, replace=False):
        """Install a theme folder, a .zip, or a single theme .json file. Returns the theme id."""
        source = Path(source)
        self.user_dir.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.install-', dir=self.user_dir))
        try:
            suffix = source.suffix.lower()
            if source.is_dir():
                copy_folder(source, stage/'t')
            elif suffix == '.zip':
                extract_zip(source, stage/'t')
            elif suffix == '.json' and source.is_file():
                (stage/'t').mkdir()
                shutil.copyfile(source, stage/'t'/'theme.json')
            else:
                raise ThemeError('give a theme folder, a .zip, or a theme .json file')
            meta = read_theme(stage/'t')
            theme_id = slug(source.stem) if suffix == '.json' else slug(meta['name'])
            if not ID.fullmatch(theme_id):
                raise ThemeError('cannot make an id from the theme name')
            if theme_id in CORE:
                raise ThemeError(f'"{theme_id}" is the name of a built-in style: rename the theme')
            target = self.user_dir/theme_id
            if target.exists() or (self.user_dir/f'{theme_id}.json').exists():
                if not replace:
                    raise ThemeError(f'"{theme_id}" is already installed (use --force to replace it)')
                shutil.rmtree(target, ignore_errors=True)
                (self.user_dir/f'{theme_id}.json').unlink(missing_ok=True)
            (stage/'t').rename(target)
            return theme_id
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def remove(self, theme_id):
        folder, single = self.user_dir/theme_id, self.user_dir/f'{theme_id}.json'
        if not ID.fullmatch(theme_id) or not (folder.is_dir() or single.is_file()):
            raise ThemeError(f'"{theme_id}" is not one of your installed themes')
        shutil.rmtree(folder, ignore_errors=True)
        single.unlink(missing_ok=True)


def _allowed(rel):
    return rel == 'theme.json' or (safe_name(rel) and Path(rel).suffix.lower() in FONT_TYPES)


def copy_folder(src, dest):
    total = count = 0
    for path in sorted(src.rglob('*')):
        rel = path.relative_to(src).as_posix()
        if path.is_symlink():
            raise ThemeError(f'{rel}: links are not allowed')
        if path.is_dir():
            continue
        if not _allowed(rel):
            raise ThemeError(f'{rel}: only theme.json and font files (.woff2 .woff .ttf) are allowed')
        count += 1
        total += path.stat().st_size
        if count > MAX_FILES or total > MAX_BYTES:
            raise ThemeError('theme is too big')
        (dest/rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest/rel)


def extract_zip(archive, dest):
    try:
        zf = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError):
        raise ThemeError('not a valid zip file')
    with zf:
        files = [i for i in zf.infolist() if not i.is_dir()]
        names = [i.filename for i in files]
        prefix = ''  # theme.json at the top, or inside the one top-level folder
        if 'theme.json' not in names:
            tops = {n.split('/', 1)[0] for n in names}
            if len(tops) == 1 and f'{next(iter(tops))}/theme.json' in names:
                prefix = next(iter(tops)) + '/'
        if len(files) > MAX_FILES or sum(i.file_size for i in files) > MAX_BYTES:
            raise ThemeError('theme is too big')
        for info in files:
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ThemeError(f'{info.filename}: links are not allowed')
            if not info.filename.startswith(prefix):
                raise ThemeError('the zip must hold one theme folder')
            rel = info.filename[len(prefix):]
            if not _allowed(rel):
                raise ThemeError(f'{info.filename}: only theme.json and font files (.woff2 .woff .ttf) are allowed')
            out = dest/rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(out, 'wb') as dst:
                data = src.read(MAX_BYTES + 1)  # the size in the zip header can lie; bound what is really written
                if len(data) > MAX_BYTES:
                    raise ThemeError('theme is too big')
                dst.write(data)
