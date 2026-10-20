"""Content-addressed cache of built duct/collector solids and their exports, in build/cache/ (gitignored).

An entry's key is the sha256 of everything its output depends on:
- what it is (duct or collector solids, or an export of either);
- the parameters: the params dataclass repr (every field, floats in round-trip repr);
- the code: every module-level statement of the duct package that the builder (and for exports the exporter) can
  reach, as its AST, plus the params class and this module's serialization (see "Keys" below: a new preset, a comment,
  a docstring or an edit to code the part does not reach keeps the key);
- the environment: the Python, numpy, scipy, shapely, trimesh and manifold3d versions, OS and CPU architecture;
- for exports, the export simplification tolerances (not the version name: it only names the files, so one entry
  serves every name, and an export whose contents mention it is refused).
Any change to any of these is a new key, so a stale entry is never served, only left behind (`clear()` removes them).
The cache's own plumbing (lookup, publishing, naming) is not followed into every key: bump FORMAT when a change to it
changes what an entry holds.

Solids are stored as their meshes (Mesh64, face ids included). A solid rebuilt from its mesh is the same geometry, but
manifold3d's internal state is not always restored exactly (to_mesh64 of `final` can reorder, and a collector's `final`
then simplifies differently), so solids loaded from disk are never exported: exports are cached separately, made from
solids built in this process (`_faithful`).

Drop-ins with the original signatures: build_duct, build_collector, export_duct, export_collector (tests/conftest.py
installs them for the test suite). For tools: duct_export_dir / collector_export_dir (an export directory for params,
optionally at other tolerances, e.g. a coarse preview).

DUCT_CACHE=0 turns the cache off (every call builds); DUCT_CACHE_DIR moves it (e.g. to share one across worktrees).
`duct cad` and `duct verify` use it; `duct release` does not (duct.print.release imports the real builders), so a
release always builds from source. In the test suite the drop-ins replace the real builders everywhere (conftest.py).
"""
import ast
import fcntl
import hashlib
import importlib.metadata
import os
import pickle
import platform
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import fields, replace
from functools import lru_cache
from pathlib import Path

import manifold3d as mf
import numpy as np

from .cad.exhaust import CollectorSolids
from .cad.exhaust import build_collector as _build_collector
from .cad.export import export_collector as _export_collector
from .cad.export import export_duct as _export_duct
from .cad.geometry import DuctSolids
from .cad.geometry import build_duct as _build_duct

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parent
FORMAT = 1   # bump when the on-disk layout changes
LIBRARIES = ('numpy', 'scipy', 'shapely', 'trimesh', 'manifold3d')
_MESH_FIELDS = dict(merge_from_vert=np.uint64, merge_to_vert=np.uint64, run_index=np.uint64, run_original_id=np.uint32,
                    run_transform=np.float64, run_flags=np.uint8, face_id=np.uint64, halfedge_tangent=np.float64)
_MARK = '_duct_cache'   # attribute set on solids that came through the cache: (kind, key)


def enabled() -> bool:
    return os.environ.get('DUCT_CACHE', '1').lower() not in ('0', 'off', 'false', 'no', '')


def cache_dir() -> Path:
    return Path(os.environ.get('DUCT_CACHE_DIR') or ROOT/'build'/'cache')


# --------------------------------------------------------------------------------------------------------------------
# Keys: the code a part depends on, definition by definition
#
# Not whole files: the module-level definitions its code can reach. From root symbols (the builder, the params class,
# the cache's own serialization), every module-level statement that a reached statement names is followed, across
# duct modules through imports (module level or function local), re-exports and module aliases (`ex.foo`). Each reached
# statement counts as its AST (ast.dump), so comments, formatting and docstrings do not. Where static analysis cannot
# see, it takes more: a module used as a value (not as `alias.name`) or globals()/vars()/eval()/exec()/__import__ takes
# the whole module, and every module-level statement that is not an import, a definition or an assignment to a name
# (import-time side effects) counts for each module reached and for its parent packages.


def _module_path(name: str) -> Path | None:
    """Source file of a duct.* module, or None outside the package."""
    if name != 'duct' and not name.startswith('duct.'): return None
    parts = name.split('.')[1:]
    if not parts: return PACKAGE/'__init__.py'
    rel = Path(*parts)
    for p in (PACKAGE/rel.with_suffix('.py'), PACKAGE/rel/'__init__.py'):
        if p.exists(): return p
    return None


_DYNAMIC = {'globals', 'vars', 'eval', 'exec', '__import__'}


def _strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                node.body = node.body[1:]
    return tree


def _import_names(node, module: str, is_package: bool) -> dict[str, tuple]:
    """What an import statement binds in `module`, duct.* targets only: name -> ('module', m) | ('symbol', m, attr) |
    ('star', m)."""
    out = {}
    if isinstance(node, ast.Import):
        for a in node.names:
            if _module_path(a.name) is None: continue
            if a.asname: out[a.asname] = ('module', a.name)
            else: out[a.name.split('.')[0]] = ('module', a.name.split('.')[0])
    elif isinstance(node, ast.ImportFrom):
        base = node.module or ''
        if node.level:
            package = module.split('.') if is_package else module.split('.')[:-1]
            base = '.'.join(package[:len(package)-node.level+1]+([base] if base else []))
        if _module_path(base) is None: return out
        for a in node.names:
            if a.name == '*': out['*'+base] = ('star', base)
            else: out[a.asname or a.name] = ('symbol', base, a.name)
    return out


def _bound_names(node) -> list[str]:
    """Names a module-level statement binds: a definition, or an assignment to a name (or to name.attr / name[...])."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): return [node.name]
    if isinstance(node, ast.Assign): targets = node.targets
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)): targets = [node.target]
    else: return []
    out = []
    for t in targets:
        for n in [t] if not isinstance(t, (ast.Tuple, ast.List)) else t.elts:
            while isinstance(n, (ast.Attribute, ast.Subscript, ast.Starred)): n = n.value
            if isinstance(n, ast.Name): out.append(n.id)
    return out


def _is_main_guard(node) -> bool:
    return (isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name)
            and node.test.left.id == '__name__')


class _Module:
    """A parsed duct module: statements, definitions by name, module-level imports, always-counted statements."""
    def __init__(self, name: str, path: Path):
        self.name = name; self.is_package = path.name == '__init__.py'
        self.nodes = _strip_docstrings(ast.parse(path.read_text())).body
        self.dumps = [ast.dump(n) for n in self.nodes]
        self.defs: dict[str, list[int]] = {}; self.imports: dict[str, tuple] = {}; self.always: list[int] = []
        for i, node in enumerate(self.nodes):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.imports.update(_import_names(node, name, self.is_package))
            elif names := _bound_names(node):
                for n in names: self.defs.setdefault(n, []).append(i)
            elif not _is_main_guard(node):
                self.always.append(i)


@lru_cache(maxsize=None)
def _parse(name: str, path: Path, mtime_ns: int, size: int) -> _Module:
    return _Module(name, path)


def _module(name: str) -> _Module:
    path = _module_path(name); st = path.stat()
    return _parse(name, path, st.st_mtime_ns, st.st_size)


def _submodule(base: str, attr: str) -> str | None:
    """base.attr when that is a duct module (and not shadowed by a definition of `attr` in base)."""
    sub = f'{base}.{attr}'
    return sub if _module_path(sub) is not None and attr not in _module(base).defs else None


def _resolve(mod: _Module, name: str, local: dict | None = None, depth: int = 0):
    """What `name` means in `mod` (`local`: function-local imports): ('def', module, name), ('module', m), ('stars', name,
    (m, ...)) for a name that may come from `from m import *`, or None (a builtin, a local variable, a library)."""
    ref = (local or {}).get(name) or mod.imports.get(name)
    if ref is None:
        if name in mod.defs: return ('def', mod.name, name)
        stars = tuple(v[1] for k, v in mod.imports.items() if k.startswith('*'))
        return ('stars', name, stars) if stars else None
    if ref[0] == 'module': return ref
    _, base, attr = ref
    if sub := _submodule(base, attr): return ('module', sub)
    target = _module(base)
    if attr in target.defs or depth > 20: return ('def', base, attr)
    return _resolve(target, attr, None, depth+1)   # re-exported by base


def _references(node, mod: _Module):
    """The resolution of every name and module attribute chain that a statement uses."""
    local = {}
    for n in ast.walk(node):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for k, v in _import_names(n, mod.name, mod.is_package).items():
                if v[0] == 'star': yield ('module', v[1])
                else: local[k] = v
    chained = set()
    for n in ast.walk(node):   # outermost attribute first
        if not isinstance(n, ast.Attribute) or id(n) in chained: continue
        chain = []; base = n
        while isinstance(base, ast.Attribute): chain.append(base.attr); base = base.value
        if not isinstance(base, ast.Name): continue
        r = _resolve(mod, base.id, local)
        if r is None or r[0] != 'module': continue
        chained |= {id(a) for a in ast.walk(n)}
        m = r[1]
        for attr in reversed(chain):
            if sub := _submodule(m, attr): m = sub; continue
            yield _resolve(_module(m), attr); break
        else:
            yield ('module', m)   # the chain ends on a module: used as a value
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and id(n) not in chained:
            yield ('module', mod.name) if n.id in _DYNAMIC else _resolve(mod, n.id, local)


def dependencies(*roots: str) -> dict[str, list[int]]:
    """module -> indices of its module-level statements that the roots reach. A root is 'module:name' (a definition)
    or 'module' (the whole module)."""
    included: dict[str, set[int]] = {}; todo: list[tuple[str, int]] = []
    def touch(m: str):
        parts = m.split('.')
        for i in range(1, len(parts)+1):   # importing a.b.c runs a and a.b too
            pkg = '.'.join(parts[:i])
            if pkg in included or _module_path(pkg) is None: continue
            included[pkg] = set(); todo.extend((pkg, k) for k in _module(pkg).always)
    def push(ref):
        if ref is None: return
        if ref[0] == 'def':
            if f'{ref[1]}:{ref[2]}' in _OPAQUE: return
            touch(ref[1]); todo.extend((ref[1], k) for k in _module(ref[1]).defs[ref[2]])
        elif ref[0] == 'module':
            touch(ref[1]); todo.extend((ref[1], k) for k in range(len(_module(ref[1]).nodes)))
        else:   # 'stars': wherever the name is defined among the star-imported modules
            for m in ref[2]: push(_resolve(_module(m), ref[1]))
    for r in roots:
        m, _, name = r.partition(':')
        push(('def', m, name) if name else ('module', m))
    while todo:
        m, k = todo.pop()
        if k in included[m]: continue
        included[m].add(k); mod = _module(m)
        for ref in _references(mod.nodes[k], mod): push(ref)
    return {m: sorted(v) for m, v in sorted(included.items())}


def code_digest(*roots: str) -> str:
    """sha256 of the AST of every statement the roots reach (`dependencies`), module by module in source order."""
    h = hashlib.sha256()
    for m, idx in dependencies(*roots).items():
        dumps = _module(m).dumps
        for k in idx:
            d = dumps[k].encode(); h.update(f'{m}:{len(d)}:'.encode()); h.update(d)
    return h.hexdigest()


@lru_cache(maxsize=1)
def environment() -> tuple:
    return (platform.python_version(), platform.system(), platform.machine(),
            *(f'{n}=={importlib.metadata.version(n)}' for n in LIBRARIES))


def _params_root(params) -> tuple[str, ...]:
    cls = type(params)
    return (f'{cls.__module__}:{cls.__qualname__}',) if _module_path(cls.__module__) is not None else ()


def key(kind: str, params, roots: tuple[str, ...], **extra) -> str:
    """The content address of `kind` made from `params` by the code that `roots` reach (see the module docstring)."""
    h = hashlib.sha256()
    def put(label, data: bytes): h.update(f'{label}:{len(data)}:'.encode()); h.update(data)
    put('format', str(FORMAT).encode()); put('kind', kind.encode()); put('params', repr(params).encode())
    put('code', code_digest(*roots, *_params_root(params)).encode())
    put('env', repr(environment()).encode())
    for k in sorted(extra): put(k, repr(extra[k]).encode())
    return h.hexdigest()


# --------------------------------------------------------------------------------------------------------------------
# Serialization: every Manifold field as its full Mesh64, the rest pickled


def _pack_manifold(m: mf.Manifold) -> dict:
    r = m.to_mesh64()
    d = dict(vert_properties=np.asarray(r.vert_properties), tri_verts=np.asarray(r.tri_verts), tolerance=m.get_tolerance())
    for f in _MESH_FIELDS:
        a = np.asarray(getattr(r, f))
        if a.size: d[f] = a
    return d


def _unpack_manifold(d: dict) -> mf.Manifold:
    arr = lambda a, t: np.array(a, dtype=t, order='C', copy=True)   # noqa: E731  (nanobind wants writable C arrays)
    kw = {f: arr(d[f], t) for f, t in _MESH_FIELDS.items() if f in d}
    m = mf.Manifold(mf.Mesh64(arr(d['vert_properties'], np.float64), arr(d['tri_verts'], np.uint64), **kw, tolerance=d['tolerance']))
    assert m.status() == mf.Error.NoError, m.status()
    return m


def _pack(solids) -> bytes:
    data = {f.name: ('manifold', _pack_manifold(v)) if isinstance(v, mf.Manifold) else ('value', v)
            for f in fields(solids) for v in [getattr(solids, f.name)]}
    return pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)


def _unpack(cls, blob: bytes):
    return cls(**{k: _unpack_manifold(v) if tag == 'manifold' else v for k, (tag, v) in pickle.loads(blob).items()})


@contextmanager
def _lock(path: Path):
    """Hold an exclusive lock on the entry `path` (a sibling .lock file) across processes, e.g. pytest-xdist workers:
    the second process asking for an entry being made waits for it instead of making it again."""
    lock = path.with_name(path.name+'.lock'); lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, 'a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(f, fcntl.LOCK_UN)


def _write_atomic(path: Path, payload: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.tmp-')
    with os.fdopen(fd, 'wb') as f: f.write(payload)
    os.replace(tmp, path)


# --------------------------------------------------------------------------------------------------------------------
# Solids

_SERIAL = ('duct.cache:_pack', 'duct.cache:_unpack')   # how solids are stored: part of what an entry depends on
_KINDS = {'duct': (_build_duct, DuctSolids, ('duct.cad.geometry:build_duct', *_SERIAL)),
          'collector': (_build_collector, CollectorSolids, ('duct.cad.exhaust:build_collector', *_SERIAL))}
_fresh: dict[str, object] = {}    # key -> solids built by this process
_loaded: dict[str, object] = {}   # key -> solids rebuilt from the disk cache


def _mark(s, kind, k):
    object.__setattr__(s, _MARK, (kind, k))   # frozen dataclasses: bypass __setattr__, the fields stay untouched
    return s


def _solids(kind: str, params):
    build, cls, roots = _KINDS[kind]
    if not enabled(): return build(params)
    k = key(kind, params, roots)
    if k in _fresh: return _fresh[k]
    if k in _loaded: return _loaded[k]
    path = cache_dir()/'solids'/f'{kind}-{k}.pkl'
    if not path.exists():
        with _lock(path):   # another process may be building it: wait, then load it
            if not path.exists(): return _faithful(kind, params, k)
    _loaded[k] = _mark(_unpack(cls, path.read_bytes()), kind, k)
    return _loaded[k]


def _faithful(kind: str, params, k: str):
    """Solids built in this process (never rebuilt from a mesh), stored on disk for later processes."""
    if k not in _fresh:
        build, _, _ = _KINDS[kind]
        s = _fresh[k] = _mark(build(params), kind, k)
        path = cache_dir()/'solids'/f'{kind}-{k}.pkl'
        if not path.exists(): _write_atomic(path, _pack(s))
    return _fresh[k]


def build_duct(g) -> DuctSolids:
    """duct.cad.geometry.build_duct(g), from the cache when the same params, code and environment were built before."""
    return _solids('duct', g)


def build_collector(c) -> CollectorSolids:
    """duct.cad.exhaust.build_collector(c), cached as build_duct."""
    return _solids('collector', c)


# --------------------------------------------------------------------------------------------------------------------
# Exports

_RUN = ('duct.cache:_run_export', 'duct.cache:_copy_named')   # the export as the cache makes and serves it
_EXPORTS = {'duct': (_export_duct, ('duct.cad.export:export_duct', 'duct.cad.geometry:build_duct', *_RUN)),
            'collector': (_export_collector, ('duct.cad.export:export_collector', 'duct.cad.exhaust:build_collector', *_RUN))}
# Registries whose contents (the builders and exporters) are roots of each kind's key on their own: not followed, or
# every key would reach every builder
_OPAQUE = {'duct.cache:_KINDS', 'duct.cache:_EXPORTS', 'duct.cache:_fresh', 'duct.cache:_loaded'}
_CHECKS = '.checks.pkl'; _DONE = '.complete'
_VERSIONED = '.versioned'   # marks a token export whose contents name the version: exported per version instead
_TOKEN = 'duct-cache-version'   # exports are made under this version name; it is replaced by the asked one on the way out


def _publish(out: Path, fill) -> Path:
    """Create the cache directory `out` atomically: fill(tmp) writes it, then it appears under its name (or another
    process's identical entry is kept)."""
    if (out/_DONE).exists(): return out
    with _lock(out):   # another process may be making it: wait for it
        if (out/_DONE).exists(): return out
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(dir=out.parent, prefix='.tmp-'))
        try:
            fill(tmp); (tmp/_DONE).write_text(out.name+'\n')
            if out.exists() and not (out/_DONE).exists(): shutil.rmtree(out)   # an interrupted entry
            tmp.rename(out)
        except OSError:
            if not (out/_DONE).exists(): raise
        finally:   # on success tmp is gone; on failure, or when another process finished the entry first, remove it
            shutil.rmtree(tmp, ignore_errors=True)
    return out


def _run_export(kind: str, params, tol: tuple, out: Path, version: str):
    """The exporter on solids built in this process (never on solids reloaded from disk); its checks into .checks.pkl."""
    export, _ = _EXPORTS[kind]
    build, _, roots = _KINDS[kind]
    s = _faithful(kind, params, key(kind, params, roots)) if enabled() else build(params)
    if tol != tuple(params.export_tolerances):
        s = replace(s, params=replace(params, export_tolerances=tol))
    (out/_CHECKS).write_bytes(pickle.dumps(export(s, out, version), protocol=pickle.HIGHEST_PROTOCOL))


def _entry(kind: str, params, tol: tuple) -> Path:
    """The export of `params` at `tol`, made under the version name _TOKEN. The version name only names the files, so one
    entry serves every name. An export whose contents mention the name is marked _VERSIONED, and callers then export
    under the asked name instead (keyed by it)."""
    _, roots = _EXPORTS[kind]
    k = key(f'{kind}-export', params, roots, tolerances=tol)
    def fill(tmp: Path):
        _run_export(kind, params, tol, tmp, _TOKEN)
        named = [p.name for p in tmp.iterdir() if _TOKEN.encode() in p.read_bytes()]
        if named:
            (tmp/_VERSIONED).write_text('\n'.join(named))
    return _publish(cache_dir()/'exports'/f'{kind}-{k[:32]}', fill)


def _copy_named(src: Path, out: Path, version: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    for p in src.iterdir():
        if p.name not in (_CHECKS, _DONE, _VERSIONED): shutil.copyfile(p, out/p.name.replace(_TOKEN, version))
    return pickle.loads((src/_CHECKS).read_bytes())


def _export_dir(kind: str, params, version: str, tolerances) -> Path:
    """Directory with the export of `params` under `version` at `tolerances` (the exporter's checks in .checks.pkl)."""
    tol = tuple(tolerances)
    if not enabled():
        out = Path(tempfile.mkdtemp(prefix=f'duct-{kind}-{version}-')); _run_export(kind, params, tol, out, version); return out
    src = _entry(kind, params, tol)
    def fill(tmp: Path):
        if (src/_VERSIONED).exists():
            _run_export(kind, params, tol, tmp, version)
        else:
            _copy_named(src, tmp, version); shutil.copyfile(src/_CHECKS, tmp/_CHECKS)
    return _publish(cache_dir()/'exports'/'named'/f'{src.name}-{version}', fill)


def duct_export_dir(g, version: str = 'v23', tolerances: tuple[float, ...] | None = None) -> Path:
    """Directory with export_duct(build_duct(g), dir, version)'s files: STL, fit check, profiles, checks.
    `tolerances` replaces g.export_tolerances (e.g. a coarse preview export)."""
    return _export_dir('duct', g, version, g.export_tolerances if tolerances is None else tolerances)


def collector_export_dir(c, version: str = 'collector-v1', tolerances: tuple[float, ...] | None = None) -> Path:
    """Directory with export_collector(build_collector(c), dir, version)'s files; `tolerances` as duct_export_dir."""
    return _export_dir('collector', c, version, c.export_tolerances if tolerances is None else tolerances)


def _copy_export(kind, s, out_dir, version):
    mark = getattr(s, _MARK, None)
    if not enabled() or mark is None or mark[0] != kind:   # solids that did not come through the cache: export them
        return _EXPORTS[kind][0](s, out_dir, version)
    tol = tuple(s.params.export_tolerances)
    if (_entry(kind, s.params, tol)/_VERSIONED).exists():
        return _copy_named(_export_dir(kind, s.params, version, tol), Path(out_dir), version)
    return _copy_named(_entry(kind, s.params, tol), Path(out_dir), version)


def export_duct(s: DuctSolids, out_dir, version: str = 'v23') -> dict:
    """duct.cad.export.export_duct, served from the export cache when `s` came from build_duct here."""
    return _copy_export('duct', s, out_dir, version)


def export_collector(s: CollectorSolids, out_dir, version: str = 'collector-v1') -> dict:
    """duct.cad.export.export_collector, served from the export cache when `s` came from build_collector here."""
    return _copy_export('collector', s, out_dir, version)


def clear():
    """Remove the whole cache directory."""
    shutil.rmtree(cache_dir(), ignore_errors=True)
