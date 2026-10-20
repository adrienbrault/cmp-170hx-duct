import hashlib
import json
from pathlib import Path

import manifold3d as mf
import numpy as np
import pytest
import trimesh

from duct.cad.export import FIT_CHECK, STL, export_duct, fit_check_name, stl_name, to_tri
from duct.cad.geometry import build_duct
from duct.params import V23, V24, V27, V29, from_toml, parse_overrides
from duct.print.verify import mesh_quality, polygon_section, verify

ROOT = Path(__file__).resolve().parents[1]
RELEASED = ROOT/'releases/v23'                 # the V23 STL and fit check, as released
REFERENCE = ROOT/'fixtures/v23'                # the original generator's fillet profiles and checks

# From exec'ing the original V23 generator (generate_continuous_v23.py, pre-restructure) up to '# The first draft offset'
# (its rounding-study path, L=70, upper radius 6) and reading `inner`.
OLD_INNER_VOLUME = 583895.7036284208
OLD_INNER_MESH_SHA256 = '98f1541dc8e4f4b1463a981a40d3a68aa132001b2ce9c2fdbc27b0eb759d81fc'


def sha256(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    solids = build_duct(V23)
    out = tmp_path_factory.mktemp('cad')
    return solids, out, export_duct(solids, out)


def test_inner_matches_old_exec_path(built):
    inner = built[0].inner
    assert inner.status().name == 'NoError' and not inner.is_empty()
    assert inner.volume() == pytest.approx(OLD_INNER_VOLUME, rel=1e-12)
    m = inner.to_mesh64()
    data = np.asarray(m.vert_properties)[:, :3].tobytes()+np.asarray(m.tri_verts).astype(np.int64).tobytes()
    assert hashlib.sha256(data).hexdigest() == OLD_INNER_MESH_SHA256


def test_stl_byte_identical_to_release(built):
    out = built[1]
    assert sha256(out/STL) == sha256(RELEASED/STL)
    assert sha256(out/FIT_CHECK) == sha256(RELEASED/FIT_CHECK)


def test_final_mesh(built):
    m = trimesh.load(built[1]/STL)
    assert m.is_watertight and m.is_winding_consistent and len(m.split()) == 1
    np.testing.assert_allclose(m.bounds, [[-60, -60, 0], [60, 60, 82]], atol=1e-6)
    released = trimesh.load(RELEASED/STL)
    assert m.volume == pytest.approx(released.volume, rel=1e-6)
    assert m.area == pytest.approx(released.area, rel=1e-6)


def test_profiles_and_checks_match_release(built):
    out, checks = built[1], built[2]
    for name in ['v23-upper-fillet-profile.json', 'v23-passage-fillet-profile.json']:
        assert (out/name).read_bytes() == (REFERENCE/name).read_bytes()
    # The released checks were later extended by verification; the generator's keys must agree.
    released = json.loads((REFERENCE/'v23-checks.json').read_text())
    assert {k: released[k] for k in checks} == checks


def test_dilation_memo_is_byte_identical(tmp_path):
    """The shell dilation is computed once per process for the same meshes (geometry.dilate): a build that reuses it
    exports byte for byte the released V23, and other inputs are not served the memo."""
    from duct import cache
    from duct.cad import geometry as G
    a, b = mf.Manifold.cube([2, 2, 2]), mf.Manifold.sphere(.5, 16)
    assert G.dilate(a, b) is G.dilate(mf.Manifold.cube([2, 2, 2]), mf.Manifold.sphere(.5, 16))   # same meshes, new ids
    assert G.dilate(a, mf.Manifold.sphere(.5, 8)) is not G.dilate(a, b) and G.dilate(a.translate([1e-6, 0, 0]), b) is not G.dilate(a, b)
    cache._build_duct(V23)   # the real builder (the suite's build_duct is the cache's): the dilation is now memoised
    n = len(G._DILATIONS)
    cache._export_duct(cache._build_duct(V23), tmp_path, 'v23')
    assert len(G._DILATIONS) == n
    assert sha256(tmp_path/STL) == sha256(RELEASED/STL) and sha256(tmp_path/FIT_CHECK) == sha256(RELEASED/FIT_CHECK)


def test_params():
    assert V23.card_x == (-30.48, 30.48)
    assert V23.port_boxes[0] == (0, 0, (-30.48-5.4, -30.48+17.8, -47.4, 47.4))
    g = parse_overrides(['upper_radius=3', 'bore=(39, 99)'])
    assert g.upper_radius == 3.0 and isinstance(g.upper_radius, float) and g.bore == (39.0, 99.0) and isinstance(g.bore[0], float)
    assert from_toml({'chamber_length': 60}).chamber_length == 60.0
    with pytest.raises(KeyError):
        from_toml({'nope': 1})
    with pytest.raises(AssertionError):
        from_toml({'chamber_length': 80})


# V24: uniform 1.6 mm shell around the rounded air volume.
V23_VOLUME_MM3 = 85039.0          # released V23 STL
V23_PORT_OBSTRUCTION_MM2 = 149.37


@pytest.fixture(scope='module')
def built24(tmp_path_factory):
    solids = build_duct(V24)
    out = tmp_path_factory.mktemp('cad24')
    return solids, out, export_duct(solids, out, 'v24')


def test_v24_verifies(built24):
    """Every release check (fit, sweeps, fan coverage, splitter, collar, fillets) on the serialized STL."""
    solids, out, checks = built24
    stl = out/stl_name('v24')
    m = trimesh.load(stl)
    assert m.is_watertight and m.is_winding_consistent and len(m.split()) == 1
    np.testing.assert_allclose(m.bounds, [[-60, -60, 0], [60, 60, 82]], atol=1e-6)
    assert (out/fit_check_name('v24')).exists() and checks['GPU_opening_mm'] == [38.5, 98.5]
    r = verify(stl, V24, solids)
    assert r['total_estimated_port_obstruction_mm2'] <= V23_PORT_OBSTRUCTION_MM2+.01
    assert r['layer_audit']['floating_layers'] == []


def test_v24_less_material(built24):
    m = trimesh.load(built24[1]/stl_name('v24'))
    assert m.volume < .97*V23_VOLUME_MM3


def test_v24_inner_is_sealed_air(built24):
    inner = built24[0].inner
    m = to_tri(inner)
    assert m.is_watertight and len(m.split()) == 2      # one sealed passage per card
    assert 575e3 < inner.volume() < 590e3


def test_v24_sectionwise_wall(built24):
    """Cheap thickness proxy: per section, shell area / air perimeter is the mean wall, which V23's corner wedges inflate."""
    s = built24[0]
    for z in [15., 25., 35., 45., 55.]:
        air = polygon_section(s.inner, z)
        shell = polygon_section(s.final, z).difference(air)
        assert shell.area/air.length < 1.75, z


def test_v24_mesh_quality(built24):
    """No folded edge pairs (they render as flecks) between faces large enough to see."""
    q = mesh_quality(trimesh.load(built24[1]/stl_name('v24')))
    assert q['folded_edges_visible'] == 0, q


# V27: the skin follows the bay fillets to the seat; the returns are only the chamfered seat frame.
@pytest.fixture(scope='module')
def built27(tmp_path_factory):
    solids = build_duct(V27)
    out = tmp_path_factory.mktemp('cad27')
    return solids, out, export_duct(solids, out, 'v27')


def test_v27_verifies(built27):
    solids, out, checks = built27
    stl = out/stl_name('v27')
    r = verify(stl, V27, solids)   # fit, plug/latch sweeps, fan coverage, splitter, collar, fillets
    assert r['total_estimated_port_obstruction_mm2'] <= V23_PORT_OBSTRUCTION_MM2+.01
    assert solids.plug_latch_collisions_mm3 == [0.0, 0.0]
    assert mesh_quality(trimesh.load(stl))['folded_edges_visible'] == 0
    released = json.loads((Path(__file__).resolve().parents[1]/'releases/v25/checks.json').read_text())
    assert solids.inner.volume() == pytest.approx(released['internal_air_volume_mm3'], rel=1e-12)   # same air passage as V25


def test_v27_printable(built27):
    """No overhang beyond 45 deg, no section void or leak, and solid (a 1.6 mm ball fits) only in the seat frame's last 3.5 mm."""
    from duct.print import printability as P
    solid = P.load_manifold(built27[1]/stl_name('v27')); spec = P.duct_spec(V27); L = V27.chamber_length
    assert P.unsupported_overhang(solid, spec).passed
    assert P.seal(solid, spec).passed
    lumps = P.solid_regions(solid, spec).failures
    assert all(f['z_range'][0] >= L-3.5 and f['volume_mm3'] < 20 for f in lumps), lumps


# The sealed seat (V29): the card face over the fin stack is closed beside the plug pockets, down to the latch lever's envelope.
SEALED = V29


@pytest.fixture(scope='module')
def built_sealed(tmp_path_factory):
    solids = build_duct(SEALED)
    out = tmp_path_factory.mktemp('cad-sealed')
    return solids, out, export_duct(solids, out, 'sealed')


def test_sealed_seat_passes_every_geometric_gate(built_sealed):
    from duct.print import printability as P
    solids, out, _ = built_sealed
    stl = out/stl_name('sealed')
    verify(stl, SEALED, solids)
    assert solids.plug_latch_collisions_mm3 == [0.0, 0.0]
    assert mesh_quality(trimesh.load(stl))['folded_edges_visible'] == 0
    solid, spec = P.load_manifold(stl), P.duct_spec(SEALED)
    for gate in (P.unsupported_overhang, P.solid_regions, P.seal, P.seat_coverage):
        r = gate(solid, spec)
        assert r.passed, (r.name, r.failures)
    seats = P.seat_coverage(solid, spec).summary['seats']
    assert max(s['uncovered_mm2'] for s in seats) < .05 and max(s['open_mm2'] for s in seats) < 22
