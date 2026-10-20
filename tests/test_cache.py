"""The build cache (duct.cache): keys cover every input, entries are served only for the same key, and what it serves
matches a fresh build."""
import hashlib
import shutil
from dataclasses import dataclass, fields, replace
from pathlib import Path

import manifold3d as mf
import numpy as np
import pytest

from duct import cache
from duct.params import COLLECTOR_V3, COLLECTOR_V4A, V23, V29

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setenv('DUCT_CACHE', '1')
    monkeypatch.setenv('DUCT_CACHE_DIR', str(tmp_path/'cache'))
    monkeypatch.setattr(cache, '_fresh', {}); monkeypatch.setattr(cache, '_loaded', {})
    return tmp_path/'cache'


# --- keys ---------------------------------------------------------------------------------------------------------------

DUCT = cache._KINDS['duct'][2]; COLLECTOR = cache._KINDS['collector'][2]
DUCT_EXPORT = cache._EXPORTS['duct'][1]; COLLECTOR_EXPORT = cache._EXPORTS['collector'][1]


def test_key_follows_params_and_tolerance():
    base = cache.key('duct', V29, DUCT)
    assert base == cache.key('duct', replace(V29), DUCT)
    assert base != cache.key('duct', replace(V29, upper_radius=V29.upper_radius+1e-9), DUCT)
    assert base != cache.key('collector', V29, DUCT)
    exp = lambda tol: cache.key('duct-export', V29, DUCT_EXPORT, version='v29', tolerances=tol)  # noqa: E731
    assert exp((.0025, .002)) != exp((.02,)) and exp((.02,)) == exp((.02,))
    assert exp((.02,)) != cache.key('duct-export', V29, DUCT_EXPORT, version='v28', tolerances=(.02,))


def _perturb(v):
    if isinstance(v, bool): return not v
    if isinstance(v, int): return v+1
    if isinstance(v, float): return v+1e-9 if v else 1e-9
    if isinstance(v, str): return v+'x'
    if isinstance(v, tuple): return (_perturb(v[0]), *v[1:]) if v else (0.0,)
    if v is None: return 1.0
    raise TypeError(type(v))


@pytest.mark.parametrize('params, roots', [(V29, DUCT), (COLLECTOR_V4A, COLLECTOR)], ids=['duct', 'collector'])
def test_key_follows_every_param_field(params, roots):
    """The params enter the key as the dataclass repr: every field is in it (none is repr=False), and a change to any
    one of them is a new key."""
    assert all(f.repr for f in fields(params))
    seen = {cache.key('part', params, roots)}
    for f in fields(params):
        p = replace(params); object.__setattr__(p, f.name, _perturb(getattr(params, f.name)))   # no __post_init__ checks
        k = cache.key('part', p, roots)
        assert k not in seen, f.name
        seen.add(k)


@pytest.fixture
def pkg(tmp_path, monkeypatch):
    """A copy of the duct package that the keys read instead of the real one: edit it to see what a key follows."""
    pkg = tmp_path/'duct'; shutil.copytree(ROOT/'duct', pkg, ignore=shutil.ignore_patterns('__pycache__'))
    monkeypatch.setattr(cache, 'PACKAGE', pkg); monkeypatch.setattr(cache, 'ROOT', tmp_path)
    return pkg


def _keys():
    return dict(duct=cache.key('duct', V29, DUCT), collector=cache.key('collector', COLLECTOR_V4A, COLLECTOR),
                duct_export=cache.key('duct-export', V29, DUCT_EXPORT, tolerances=(.02,)),
                collector_export=cache.key('collector-export', COLLECTOR_V4A, COLLECTOR_EXPORT, tolerances=(.02,)))


def _edit(pkg, rel, old, new):
    p = pkg/rel; text = p.read_text(); assert text.count(old) == 1, (rel, old)
    p.write_text(text.replace(old, new))


BUILD_DUCT = 'def build_duct(g: GeometryParams) -> DuctSolids:\n'


def test_key_ignores_what_the_part_does_not_depend_on(pkg):
    """A new preset, a comment, a docstring, a reformatted line, an unrelated module or an unused function keep every key."""
    before = _keys()
    with open(pkg/'params.py', 'a') as f:
        f.write('\nV99 = replace(V30, pitch=50.0)   # a new preset\nCOLLECTOR_V9 = replace(COLLECTOR_V4A, plenum_depth=50.0)\n'
                'PRESETS["v99"] = V99\n')
    _edit(pkg, 'cad/geometry.py', BUILD_DUCT, BUILD_DUCT+'    """A new docstring."""\n    # a new comment\n')
    _edit(pkg, 'cad/geometry.py', 'def smooth01(t):\n    t = np.clip(t, 0, 1)', 'def smooth01(t):\n    t = np.clip(t,   0, 1)  # spaced')
    _edit(pkg, 'params.py', '"""Geometric inputs of the duct.', '"""Geometric inputs of the duct (edited).')
    with open(pkg/'cfd/run.py', 'a') as f: f.write('\nX = 1\n')
    with open(pkg/'cad/geometry.py', 'a') as f: f.write('\n\ndef unused_helper():\n    return 1\n')
    with open(pkg/'cad/exhaust.py', 'a') as f: f.write('\n\nUNUSED = 2\n')
    assert _keys() == before


ALL = {'duct', 'duct_export', 'collector', 'collector_export'}


@pytest.mark.parametrize('rel, old, new, changed', [
    ('cad/geometry.py', BUILD_DUCT, BUILD_DUCT+'    g = g\n', {'duct', 'duct_export'}),   # the duct builder
    ('cad/geometry.py', 'def smooth01(t):\n    t = np.clip(t, 0, 1)', 'def smooth01(t):\n    t = np.clip(t, 0, 1.0)', ALL),  # shared
    ('cad/exhaust.py', 'def card_mouths(c: CollectorParams) -> list[tuple[float, float, float, float]]:\n',   # also imported by
     'def card_mouths(c: CollectorParams) -> list[tuple[float, float, float, float]]:\n    c = c\n',          # a function in export
     {'collector', 'collector_export'}),
    ('cad/export.py', "def export_duct(s: DuctSolids, out_dir: Path, version: str = 'v23') -> dict:\n",       # the duct exporter
     "def export_duct(s: DuctSolids, out_dir: Path, version: str = 'v23') -> dict:\n    s = s\n", {'duct_export'}),
    ('params.py', 'class GeometryParams:\n', 'class GeometryParams:\n    def extra(self): return 1\n', ALL),   # a params method
    ('cad/exhaust.py', 'FIN_END_GAP = 2.0', 'FIN_END_GAP = 2.5', {'collector', 'collector_export'}),            # a module constant
    ('cache.py', 'd = dict(vert_properties=np.asarray(r.vert_properties)',                                      # how solids are stored
     "d = dict(vert_properties=np.asarray(r.vert_properties, order='C')", ALL),
])
def test_key_follows_the_code_the_part_depends_on(pkg, rel, old, new, changed):
    """A changed statement in the builder, the exporter or anything they reach (helpers in other modules, function-local
    imports, the params class, module constants, the cache's serialization) is a new key, for exactly the parts that
    reach it."""
    before = _keys()
    _edit(pkg, rel, old, new)
    after = _keys()
    assert {k for k in before if before[k] != after[k]} == changed
    _edit(pkg, rel, new, old)
    assert _keys() == before


def test_key_follows_all_of_a_module_used_as_a_value(pkg):
    """A module used other than as `module.name` (here: getattr on it) brings in all of it."""
    _edit(pkg, 'cad/geometry.py', BUILD_DUCT, BUILD_DUCT+'    from . import hardware as hw; getattr(hw, "BRACKET")\n')
    before = _keys()
    with open(pkg/'cad/hardware.py', 'a') as f: f.write('\nNEVER_NAMED = 1\n')
    assert _keys()['duct'] != before['duct'] and _keys()['collector'] == before['collector']


def test_key_follows_the_environment(monkeypatch):
    before = cache.key('duct', V23, DUCT)
    monkeypatch.setattr(cache, 'environment', lambda: ('3.12.0', 'Darwin', 'arm64', 'manifold3d==0.0.0'))
    assert cache.key('duct', V23, DUCT) != before


# --- entries (a small stand-in part: the same machinery as the duct and collector) ------------------------------------

@dataclass(frozen=True)
class Part:
    a: float = 10.0
    export_tolerances: tuple = (0.01,)


@dataclass(frozen=True)
class PartSolids:
    params: Part
    final: mf.Manifold
    profile: list


def _build(calls):
    def build(p):
        calls.append(p)
        return PartSolids(p, mf.Manifold.cube([p.a, 2, 3])-mf.Manifold.cylinder(5, .5, circular_segments=64).translate([1, 1, -1]),
                          [dict(z=1.0)])
    return build


def _export(s, out, version):
    from duct.print.printability import export_stl
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    export_stl(s.final.simplify(s.params.export_tolerances[0]), out/f'{version}.stl')
    return dict(volume=s.final.volume(), tol=s.params.export_tolerances)


@pytest.fixture
def part_kind(tmp_cache, monkeypatch):
    calls = []
    monkeypatch.setitem(cache._KINDS, 'part', (_build(calls), PartSolids, ('duct.params',)))
    monkeypatch.setitem(cache._EXPORTS, 'part', (_export, ('duct.params',)))
    return calls


def test_hit_miss_and_reload(part_kind, tmp_cache):
    calls = part_kind
    s = cache._solids('part', Part())
    assert len(calls) == 1 and cache._solids('part', Part()) is s and len(calls) == 1        # in-process hit
    cache._fresh.clear(); cache._loaded.clear()
    t = cache._solids('part', Part())                                                       # disk hit: no build
    assert len(calls) == 1 and t is not s and t.profile == s.profile
    assert t.final.volume() == pytest.approx(s.final.volume(), rel=1e-12)
    cache._solids('part', Part(a=11.0)); assert len(calls) == 2                              # other params: a build
    assert len(list((tmp_cache/'solids').glob('*.pkl'))) == 2


def test_exports_come_from_built_solids(part_kind, tmp_cache):
    calls = part_kind
    s = cache._solids('part', Part())
    d = cache._export_dir('part', Part(), 'x', (0.01,))
    assert len(calls) == 1 and (d/'x.stl').exists()
    cache._fresh.clear(); cache._loaded.clear()
    loaded = cache._solids('part', Part())
    out = Path(tmp_cache.parent/'copy'); checks = cache._copy_export('part', loaded, out, 'x')   # served: no export, no build
    assert len(calls) == 1 and checks['volume'] == pytest.approx(s.final.volume())
    assert (out/'x.stl').read_bytes() == (d/'x.stl').read_bytes()
    d2 = cache._export_dir('part', Part(), 'z', (0.01,))   # another version name: the same entry, renamed files
    assert len(calls) == 1 and (d2/'z.stl').read_bytes() == (d/'x.stl').read_bytes() and not (d2/'x.stl').exists()
    cache._export_dir('part', Part(), 'x', (0.2,))     # a new export of solids loaded from disk is made from a fresh build
    assert len(calls) == 2
    cache._copy_export('part', replace(loaded), out, 'y')   # solids that did not come through the cache: exported as given
    assert len(calls) == 2 and (out/'y.stl').exists()


def test_export_naming_its_version_is_exported_per_version(part_kind, monkeypatch):
    """An export whose contents name the version (the snap collector's) is not shared across names: each name gets
    its own export, with its own name inside."""
    def export(s, out, version):
        Path(out).mkdir(parents=True, exist_ok=True); (Path(out)/'log.txt').write_text(f'exported as {version}')
        return {}
    monkeypatch.setitem(cache._EXPORTS, 'part', (export, ('duct.params',)))
    for name in ('x', 'y'):
        assert (cache._export_dir('part', Part(), name, (0.01,))/'log.txt').read_text() == f'exported as {name}'


def test_concurrent_requests_build_once(part_kind, monkeypatch):
    """Two requests for an entry being made (threads here; pytest-xdist workers are processes, the lock is the same
    flock) build or export it once: the second waits for the first and is served its entry."""
    import threading
    import time
    calls = part_kind; build = cache._KINDS['part'][0]
    def slow(p): time.sleep(.5); return build(p)
    monkeypatch.setitem(cache._KINDS, 'part', (slow, PartSolids, ('duct.params',)))
    run = lambda f: [t.start() or t for t in [threading.Thread(target=f) for _ in range(2)]]  # noqa: E731
    for t in run(lambda: cache._solids('part', Part())): t.join()
    assert len(calls) == 1
    exports = []
    def export(s, out, version): exports.append(version); time.sleep(.5); return _export(s, out, version)
    monkeypatch.setitem(cache._EXPORTS, 'part', (export, ('duct.params',)))
    for t in run(lambda: cache._export_dir('part', Part(), 'x', (0.01,))): t.join()
    assert exports == [cache._TOKEN] and len(calls) == 1


def test_disabled(part_kind, monkeypatch):
    monkeypatch.setenv('DUCT_CACHE', '0')
    calls = part_kind
    cache._solids('part', Part()); cache._solids('part', Part())
    assert len(calls) == 2


# --- the real parts -------------------------------------------------------------------------------------------------------

def _mesh_sha(m):
    r = m.to_mesh64()
    return hashlib.sha256(np.asarray(r.vert_properties)[:, :3].tobytes()+np.asarray(r.tri_verts).astype(np.int64).tobytes()).hexdigest()


def test_duct_from_disk_matches_a_fresh_build(tmp_cache, tmp_path):
    """V23 through a cold cache, then from disk in a 'new process': the air volume's mesh is identical, and the export
    served for it is byte for byte the export of a fresh build."""
    fresh = cache.build_duct(V23)          # cold: built here
    cache._fresh.clear(); cache._loaded.clear()
    loaded = cache.build_duct(V23)
    assert _mesh_sha(loaded.inner) == _mesh_sha(fresh.inner)
    assert loaded.final.volume() == pytest.approx(fresh.final.volume(), rel=1e-12)
    cache._export_duct(fresh, tmp_path/'fresh', 'v23')
    cache.export_duct(loaded, tmp_path/'cached', 'v23')
    for p in (tmp_path/'fresh').iterdir():
        if p.suffix != '.npz': assert p.read_bytes() == (tmp_path/'cached'/p.name).read_bytes(), p.name


def test_collector_export_served_matches_a_fresh_build(tmp_cache, tmp_path):
    """v3: its `final` rebuilt from the mesh does not even export (no watertight simplification), so the export served
    for solids loaded from disk must be the one made from the built solids."""
    fresh = cache.build_collector(COLLECTOR_V3)   # cold: built here
    cache._export_collector(fresh, tmp_path/'fresh', 'collector-v3')
    cache.export_collector(fresh, tmp_path/'warm', 'collector-v3')   # exported into the cache
    cache._fresh.clear(); cache._loaded.clear()
    cache.export_collector(cache.build_collector(COLLECTOR_V3), tmp_path/'cached', 'collector-v3')   # from disk
    for p in (tmp_path/'fresh').iterdir():
        assert p.read_bytes() == (tmp_path/'cached'/p.name).read_bytes() == (tmp_path/'warm'/p.name).read_bytes(), p.name
