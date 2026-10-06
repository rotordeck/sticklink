"""Visualiser plugins: a folder with plugin.json and a script that draws on a canvas (see docs/plugins.md).

Plugins are found in the user's plugin folder (new ones show up without a restart) and in the ones shipped with
Sticklink. They are only ever *served*; they run in the browser, in a sandboxed frame (see server.py).
"""
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

BUILTIN = Path(__file__).resolve().parent/'web'/'plugins'
ID = re.compile(r'[a-z0-9][a-z0-9_-]{0,39}')
API = 1
FILE_TYPES = {'.js', '.json', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.woff', '.woff2', '.ttf', '.txt'}
MAX_FILES, MAX_BYTES = 200, 10*1024*1024


class PluginError(ValueError):
    pass


def default_dir():
    base = os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config'
    return Path(base)/'sticklink'/'plugins'


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', str(text).lower()).strip('-')[:40]


def read_manifest(folder):
    """Return the cleaned manifest of a plugin folder; raise PluginError saying what is wrong."""
    path = Path(folder)/'plugin.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise PluginError('plugin.json is missing')
    except (ValueError, OSError):
        raise PluginError('plugin.json is not valid JSON')
    if not isinstance(data, dict):
        raise PluginError('plugin.json must be an object')

    def text(key, limit, default=''):
        value = data.get(key, default)
        if not isinstance(value, str) or len(value) > limit:
            raise PluginError(f'"{key}" must be text of at most {limit} characters')
        return value
    name = text('name', 60)
    if not name.strip():
        raise PluginError('"name" is required')
    entry = text('entry', 100, 'main.js')
    if data.get('api', API) != API:
        raise PluginError(f'needs plugin API {data.get("api")}, this Sticklink speaks {API}')
    if not safe_name(entry) or not entry.endswith('.js') or not (Path(folder)/entry).is_file():
        raise PluginError(f'entry script "{entry}" not found')
    return dict(name=name.strip(), author=text('author', 60), description=text('description', 200),
                version=text('version', 20), entry=entry)


def safe_name(rel):
    """A relative path with plain names only (no .., no absolute, no odd characters), of an allowed file type."""
    parts = rel.replace('\\', '/').split('/')
    return (bool(rel) and all(p not in ('', '.', '..') and not p.startswith('.') and re.fullmatch(r'[\w. @()+-]+', p) for p in parts)
            and Path(parts[-1]).suffix.lower() in FILE_TYPES)


class PluginStore:
    def __init__(self, user_dir=None, builtin_dir=None):
        self.user_dir = Path(user_dir) if user_dir else default_dir()
        self.builtin_dir = Path(builtin_dir) if builtin_dir else BUILTIN

    def _scan(self, base, builtin):
        found = {}
        if not base.is_dir():
            return found
        for folder in sorted(base.iterdir()):
            if not folder.is_dir() or not ID.fullmatch(folder.name):
                continue
            item = dict(id=folder.name, name=folder.name, author='', description='', version='', builtin=builtin,
                        error=None, entry=None, root=folder)
            try:
                item.update(read_manifest(folder))
            except PluginError as exc:
                item['error'] = str(exc)
            found[folder.name] = item
        return found

    def all(self):
        """Every plugin by id; the user's folder wins over a built-in with the same id."""
        found = self._scan(self.builtin_dir, True)
        found.update(self._scan(self.user_dir, False))
        return dict(sorted(found.items()))

    def get(self, plugin_id):
        return self.all().get(plugin_id)

    def listing(self):
        return [{k: v for k, v in p.items() if k not in ('root', 'entry')} | dict(url=f'/viz/{p["id"]}') for p in self.all().values()]

    def file(self, plugin_id, rel):
        """Path of a servable file inside a plugin, or None."""
        plugin = self.get(plugin_id)
        if plugin is None or plugin['error'] or not safe_name(rel):
            return None
        root = plugin['root'].resolve()
        path = (root/rel).resolve()
        if root not in path.parents or not path.is_file():
            return None
        return path

    def install(self, source, replace=False):
        """Install a folder, a .zip or a single .js file. Returns the plugin id."""
        source = Path(source)
        self.user_dir.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.install-', dir=self.user_dir))
        try:
            if source.is_dir():
                copy_folder(source, stage/'p')
            elif source.suffix.lower() == '.zip':
                extract_zip(source, stage/'p')
            elif source.suffix.lower() == '.js' and source.is_file():
                (stage/'p').mkdir()
                shutil.copyfile(source, stage/'p'/'main.js')
                (stage/'p'/'plugin.json').write_text(json.dumps(dict(name=source.stem.replace('-', ' ').replace('_', ' ').title(), api=API)))
            else:
                raise PluginError('give a plugin folder, a .zip, or a single .js file')
            meta = read_manifest(stage/'p')
            plugin_id = slug(source.stem if source.suffix.lower() == '.js' else (meta["name"]))
            if not ID.fullmatch(plugin_id):
                raise PluginError('cannot make an id from the plugin name')
            target = self.user_dir/plugin_id
            if target.exists():
                if not replace:
                    raise PluginError(f'"{plugin_id}" is already installed (use --force to replace it)')
                shutil.rmtree(target)
            (stage/'p').rename(target)
            return plugin_id
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def remove(self, plugin_id):
        if not ID.fullmatch(plugin_id) or not (self.user_dir/plugin_id).is_dir():
            raise PluginError(f'"{plugin_id}" is not an installed user plugin')
        shutil.rmtree(self.user_dir/plugin_id)


def copy_folder(src, dest):
    total = count = 0
    for path in sorted(src.rglob('*')):
        rel = path.relative_to(src).as_posix()
        if path.is_symlink():
            raise PluginError(f'{rel}: links are not allowed')
        if path.is_dir():
            continue
        if not safe_name(rel):
            raise PluginError(f'{rel}: file name or type not allowed')
        count += 1
        total += path.stat().st_size
        if count > MAX_FILES or total > MAX_BYTES:
            raise PluginError('plugin is too big')
        (dest/rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest/rel)


def extract_zip(archive, dest):
    try:
        zf = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError):
        raise PluginError('not a valid zip file')
    with zf:
        files = [i for i in zf.infolist() if not i.is_dir()]
        names = [i.filename for i in files]
        prefix = ''  # plugin.json at the top, or inside the one top-level folder
        if 'plugin.json' not in names:
            tops = {n.split('/', 1)[0] for n in names}
            if len(tops) == 1 and f'{next(iter(tops))}/plugin.json' in names:
                prefix = next(iter(tops)) + '/'
        if len(files) > MAX_FILES or sum(i.file_size for i in files) > MAX_BYTES:
            raise PluginError('plugin is too big')
        for info in files:
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise PluginError(f'{info.filename}: links are not allowed')
            if not info.filename.startswith(prefix):
                raise PluginError('the zip must hold one plugin folder')
            rel = info.filename[len(prefix):]
            if not safe_name(rel):
                raise PluginError(f'{info.filename}: file name or type not allowed')
            out = dest/rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(out, 'wb') as dst:
                data = src.read(MAX_BYTES + 1)  # the size in the zip header can lie; bound what is really written
                if len(data) > MAX_BYTES:
                    raise PluginError('plugin is too big')
                dst.write(data)
