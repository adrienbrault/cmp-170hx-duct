"""The adjacent-slot family (A29: two cards in four consecutive slots, 2-slot pitch) next to the 3-slot family (V28, V29: one
empty slot between the cards). A29 must pass every geometric gate; V28 and V29 must not change."""
import hashlib
from dataclasses import fields
from pathlib import Path

import pytest
import trimesh

from duct.cad.export import export_duct, fit_check_name, stl_name
from duct.cad.geometry import build_duct
from duct.params import A29, PRESETS, V28, V29
from duct.print.verify import mesh_quality, verify

ROOT = Path(__file__).resolve().parents[1]
SLOT = 20.32   # PCI slot pitch, CEM Fig 1-3


def sha256(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_families():
    assert V29.pitch == pytest.approx(3*SLOT) and A29.pitch == pytest.approx(2*SLOT)
    assert PRESETS['a29'] is A29 and PRESETS['v29'] is V29
    assert [f.name for f in fields(V29) if getattr(V29, f.name) != getattr(A29, f.name)] == ['pitch']
    assert V28.shared_wall == V29.shared_wall == 0.0                # two separate 1.2 mm inner collar walls
    assert A29.shared_wall == pytest.approx(A29.pitch-A29.bore[0])  # one 2.14 mm wall between the cards
    assert A29.shared_wall < 2*A29.collar_wall


@pytest.fixture(scope='module')
def built_a29(tmp_path_factory):
    solids = build_duct(A29)
    out = tmp_path_factory.mktemp('cad-a29')
    return solids, out, export_duct(solids, out, 'a29')


def test_a29_passes_every_geometric_gate(built_a29):
    from duct.print import printability as P
    solids, out, _ = built_a29
    stl = out/stl_name('a29')
    r = verify(stl, A29, solids)   # fit, plug/latch sweeps, fan coverage, splitter, collar, fillets
    assert solids.plug_latch_collisions_mm3 == [0.0, 0.0] and max(solids.bay_collisions_mm3) < 1e-6   # float noise (A29: ~1e-8 mm3)
    assert r['fan_face_uncovered_area_mm2'] < .01
    assert mesh_quality(trimesh.load(stl))['folded_edges_visible'] == 0
    solid, spec = P.load_manifold(stl), P.duct_spec(A29)
    for gate in (P.unsupported_overhang, P.solid_regions, P.seal, P.seat_coverage):
        g = gate(solid, spec)
        assert g.passed, (g.name, g.failures)
    seats = P.seat_coverage(solid, spec).summary['seats']
    assert max(s['uncovered_mm2'] for s in seats) < .05 and max(s['open_mm2'] for s in seats) < 22   # as V29
    assert trimesh.load(out/fit_check_name('a29')).body_count == 1   # the shared wall joins the two collars (V29: 2)


def test_a29_inner_plug_clears_the_neighbour(built_a29):
    """Card B's plug pocket faces card A: card A's inner collar wall stays outside card B's plug and latch."""
    solids = built_a29[0]
    hx = A29.card_x[1]+A29.plug[0]                        # card B's plug housing, inner (card A) side
    collar_a = A29.card_x[0]+A29.bore[0]/2+A29.collar_wall  # card A's inner collar wall, outer face
    assert hx-collar_a == pytest.approx(.94, abs=.01)
    assert solids.plug_latch_collisions_mm3[1] == 0.0


@pytest.mark.parametrize('version, g', [('v28', V28), ('v29', V29), ('a29', A29)])
def test_released_presets_rebuild_byte_identical(tmp_path, version, g):
    """Released ducts do not change (e.g. with the hub fairing and its options off): V28, V29 and A29 rebuild to their
    released STL and fit check, byte for byte."""
    export_duct(build_duct(g), tmp_path, version)
    for name in (stl_name(version), fit_check_name(version)):
        assert sha256(tmp_path/name) == sha256(ROOT/'releases'/version/name), name
