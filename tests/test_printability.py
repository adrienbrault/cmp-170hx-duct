"""Printability and seal gates (duct.print.printability): small synthetic parts for each gate, and the released V25 STL."""
from pathlib import Path

import manifold3d as mf
import numpy as np
import pytest

from duct.env import BAMBU
from duct.params import V24, V25, V27, V28
from shapely.geometry import box
from duct.print import printability as pr
from duct.print.release import PrintabilityError, _gate, _note_override

REL = Path(__file__).resolve().parents[1]/'releases'
T = pr.Thresholds()


def cube(size, origin): return mf.Manifold.cube(size).translate(origin)


def frustum(half0, half1, z0, z1):
    """Square frustum centred on the z axis: half width half0 at z0, half1 at z1."""
    cs = mf.CrossSection.square([2*half0, 2*half0]).translate([-half0, -half0])
    return mf.Manifold.extrude(cs, z1-z0, scale_top=[half1/half0, half1/half0]).translate([0, 0, z0])


def tube(half=10.0, wall=1.2, height=10.0):
    return cube([2*half, 2*half, height], [-half, -half, 0])-cube([2*half-2*wall, 2*half-2*wall, height+2], [-half+wall, -half+wall, -1])


def conduit_spec(wall=1.2, height=10.0, **kw):
    """A straight conduit open at both ends, like the duct: one passage, capped at both ends for the 3-D check."""
    return pr.PartSpec('conduit', wall=wall, openings=(pr.Opening('passage', (0, height), min_area=50.0, max_count=1, end_opening=True),),
                       passage_seeds=((0.0, 0.0, .5),), caps=((.1, -.25), (height-.1, height+.25)), **kw)


def near(f, xyz, tol):
    return all(abs(a-b) <= tol for a, b in zip(f['worst_layer'], xyz))


# --- unsupported_overhang ---------------------------------------------------------------------------------------------

def test_45deg_chamfer_passes():
    part = frustum(5, 10, 0, 5)+cube([20, 20, 2], [-10, -10, 5])   # every side flares at exactly 45 deg
    r = pr.unsupported_overhang(part, pr.PartSpec('chamfer', wall=1.2))
    assert r.passed, r.failures
    assert r.summary['worst_layer_area_mm2']['50deg'] < .01


def test_shelf_fails_with_location():
    part = cube([5, 5, 12], [0, 0, 0])+cube([15, 5, 1], [0, 0, 10])   # a 10 mm horizontal shelf at z = 10
    r = pr.unsupported_overhang(part, pr.PartSpec('shelf', wall=1.2))
    assert not r.passed
    f = r.summary['tier_a_failures'][0]
    assert f['max_island_mm2'] > 40 and 10 <= f['z_range'][0] <= 10.3 and f['bbox_xy'][0] >= 5 and f['bbox_xy'][2] == pytest.approx(15, abs=.01)


def test_small_steep_tip_fails_tier_b_only():
    # a 0.6 x 0.3 mm ledge: too small for tier A, but steeper than the slicer's 60 deg rule (V25's return tip)
    part = cube([5, 5, 10], [0, 0, 0])+cube([.6, .3, 4], [5, 2, 5])
    r = pr.unsupported_overhang(part, pr.PartSpec('tip', wall=1.2))
    assert not r.passed and not r.summary['tier_a_failures']
    f = r.summary['tier_b_failures'][0]
    assert f['max_angle_deg'] > 60 and 5 <= f['bbox_xy'][0] and f['bbox_xy'][2] <= 5.61 and 5 <= f['z_range'][0] <= 5.5


def test_floating_island():
    arch = cube([2, 2, 12], [0, 0, 0])+cube([2, 2, 12], [10, 0, 0])+cube([12, 2, 2], [0, 0, 10])
    part = arch+cube([2, 2, 4.5], [5, 0, 6])   # a pendant hanging from the beam starts in mid-air at z = 6
    r = pr.unsupported_overhang(part, pr.PartSpec('pendant', wall=1.2))
    fl = r.summary['floating_islands']
    assert not r.passed and len(fl) == 1 and fl[0]['z_range'][0] == pytest.approx(6.1) and fl[0]['bbox_xy'] == [5, 0, 7, 2]


def test_allowed_bridge():
    part = cube([2, 2, 12], [0, 0, 0])+cube([2, 2, 12], [10, 0, 0])+cube([12, 2, 2], [0, 0, 10])
    bridge = pr.Allowed('beam', (2, 0, 9.9), (10, 2, 10.5), 'an 8 mm bridge')
    assert not pr.unsupported_overhang(part, pr.PartSpec('arch', wall=1.2)).passed
    r = pr.unsupported_overhang(part, pr.PartSpec('arch', wall=1.2, overhang_allowed=(bridge,)))
    assert r.passed and r.allowed[0]['allowed_as'] == 'beam'


# --- solid_regions ----------------------------------------------------------------------------------------------------

def test_plain_tube_has_no_solid():
    assert pr.solid_regions(tube(), pr.PartSpec('tube', wall=1.2)).passed


def test_corner_wedge_fails_with_location():
    wedge = mf.Manifold.extrude(mf.CrossSection([np.array([[-8.8, 8.8], [-8.8, 4.8], [-4.8, 8.8]])]), 10)   # fills an inside corner
    r = pr.solid_regions(tube()+wedge, pr.PartSpec('tube', wall=1.2))
    assert not r.passed
    f = r.failures[0]
    assert f['bbox_xy'][0] < -8 and f['bbox_xy'][3] > 8 and f['max_island_mm2'] > 5 and f['max_width_mm'] > 1.6


def test_sloped_wall_is_not_solid():
    # 1.2 mm normal wall leaning 45 deg: its horizontal section is 1.7 mm wide, but no 1.6 mm ball fits
    inset = 1.2*np.sqrt(2)
    part = frustum(10, 18, 0, 8)-frustum(10-inset-1, 18-inset+1, -1, 9)
    sec = pr.to_shapely(part.slice(4.0))
    assert sec.area/sec.length*2 > 1.6   # mean horizontal width of the ring
    assert pr.solid_regions(part, pr.PartSpec('cone', wall=1.2)).passed


# --- seal -------------------------------------------------------------------------------------------------------------

def test_conduit_seals():
    r = pr.seal(tube(), conduit_spec())
    assert r.passed and r.summary['b_voxels']['passage_components'] == 1


def test_wall_pinhole_leaks():
    hole = mf.Manifold.cylinder(4, .6, circular_segments=24).rotate([0, 90, 0]).translate([7.5, 0, 5])
    r = pr.seal(tube()-hole, conduit_spec())
    assert not r.passed and not r.summary['a_undesigned_voids']
    leak = r.summary['b_voxels']['leaks'][0]
    assert leak['leaves_part_at'][0] > 8.5 and abs(leak['leaves_part_at'][2]-5) < 1


def test_cavity_open_at_top_fails_a():
    # a blind 1 x 1 mm cavity in a 3 mm wall, open at the top face (the trial V26 band/shell gaps)
    r = pr.seal(tube(wall=3)-cube([1, 1, 4], [8, -.5, 7]), conduit_spec(wall=3))
    assert not r.passed and not r.summary['b_voxels']['leaks']
    f = r.summary['a_undesigned_voids'][0]
    assert f['bbox_xy'] == pytest.approx([8, -.5, 9, .5], abs=.01) and f['z_range'] == [7.1, 9.9]


def test_enclosed_void_fails_a_and_b():
    r = pr.seal(tube(wall=3)-cube([1.5, 1.5, 2], [7.75, -.75, 4]), conduit_spec(wall=3))
    assert not r.passed and r.summary['a_undesigned_voids'] and r.summary['b_voxels']['enclosed_voids']


# --- seat coverage --------------------------------------------------------------------------------------------------------

def seat_spec(region, openings=(), covers=()):
    return conduit_spec(seats=(pr.SeatFace('seat', 10.0, region, openings, covers),))


def test_seat_covered_by_wall_and_passage():
    r = pr.seat_coverage(tube(), seat_spec(box(-10, -10, 10, 10)))
    assert r.passed and r.summary['seats'][0]['uncovered_mm2'] < 1e-3


def test_seat_exposed_strip_fails_with_location_and_opening_allows_it():
    region = box(-10, -10, 12, 10)   # the seated face reaches 2 mm past the tube: a 2 x 20 mm strip of it is exposed
    r = pr.seat_coverage(tube(), seat_spec(region))
    assert not r.passed
    f = r.failures[0]
    assert f['uncovered_mm2'] == pytest.approx(40, abs=.01) and f['bbox_xy'] == pytest.approx([10, -10, 12, 10], abs=.01)
    assert pr.seat_coverage(tube(), seat_spec(region, (('strip', box(10, -10, 12, 10), 'test'),)), pr.Thresholds(max_seat_open_mm2=40.1)).passed


def test_seat_open_area_budget_counts_openings_beyond_covers():
    region = box(-10, -10, 12, 10); strip = (('strip', box(10, -10, 12, 10), 'test'),)
    r = pr.seat_coverage(tube(), seat_spec(region, strip))   # the opening leaves 40 mm2 of the face open: over the 24 mm2 budget
    assert not r.passed and r.summary['seats'][0]['uncovered_mm2'] < 1e-3 and r.summary['seats'][0]['open_mm2'] == pytest.approx(40, abs=.01)
    assert r.failures[0]['open_mm2'] == pytest.approx(40, abs=.01) and r.failures[0]['bbox_xy'] == pytest.approx([10, -10, 12, 10], abs=.01)
    covered = seat_spec(region, strip, (('plug', box(10, -10, 12, 0), 'test'),))   # the mating part covers half of it
    r = pr.seat_coverage(tube(), covered)
    assert r.passed and r.summary['seats'][0]['open_mm2'] == pytest.approx(20, abs=.01)


def test_seat_breach_exposes_the_passage():
    # a slot through the wall at the seat: the passage is no longer an enclosed opening, so it no longer counts as covered
    r = pr.seat_coverage(tube()-cube([3, 1, 2], [8, -.5, 9]), seat_spec(box(-10, -10, 10, 10)))
    assert not r.passed and r.failures[0]['uncovered_mm2'] > 250


# --- slicer gate --------------------------------------------------------------------------------------------------------

def test_support_from_gcode(tmp_path):
    g = tmp_path/'p.gcode'
    g.write_text('; filament_density: 1.27\n; filament_diameter: 1.75\n'
                 '; CHANGE_LAYER\n; Z_HEIGHT: 0.2\n; FEATURE: Outer wall\nG1 X100 Y100\nG1 X120 Y100 E1\nG1 X120 Y120 E1\nG1 X100 Y120 E1\nG1 X100 Y100 E1\n'
                 '; FEATURE: Support\nG1 X105 Y105\nG1 X106 Y105 E.5\n'
                 '; CHANGE_LAYER\n; Z_HEIGHT: 0.48\n; FEATURE: Support\nG1 X105 Y105\nG1 X106 Y105 E.5\n; FEATURE: Inner wall\nG1 X110 Y110 E2\n')
    r = pr.support_from_gcode(g, [[-10, -10, 0], [10, 10, 5]])
    assert r['plate_offset_xy'] == [110, 110] and r['support_filament_mm'] == 1.0
    assert r['support_g'] == pytest.approx(np.pi*.875**2*1.27/1000, abs=5e-4)
    assert r['islands'][0]['z_range'] == [.2, .48] and r['islands'][0]['top_contact_bbox_xy'] == [-5, -5, -4, -5]


@pytest.mark.skipif(not BAMBU.exists(), reason='Bambu Studio not installed')
def test_slicer_supports_the_shelf(tmp_path):
    stl = tmp_path/'shelf.stl'
    pr.export_stl(cube([5, 5, 12], [0, 0, 0])+cube([15, 5, 1], [0, 0, 10]), stl)
    r = pr.slicer_support(stl, tmp_path/'slice')
    assert not r.passed and r.summary['support_g'] > 0
    isl = r.failures[0]
    assert isl['z_range'][1] < 10 and isl['top_contact_bbox_xy'][0] > 4


# --- the release gate -----------------------------------------------------------------------------------------------------

def test_release_gate_refuses_and_override_is_noted(tmp_path):
    stl = tmp_path/'wedge.stl'
    wedge = mf.Manifold.extrude(mf.CrossSection([np.array([[-8.8, 8.8], [-8.8, 4.8], [-4.8, 8.8]])]), 10)
    pr.export_stl(tube()+wedge, stl)
    with pytest.raises(PrintabilityError, match='solid_regions'):
        _gate(stl, conduit_spec(), None, None)
    gates = _gate(stl, conduit_spec(), None, 'test override')
    notes = tmp_path/'PRINT-NOTES.md'; notes.write_text('# hand-written\n')
    _note_override(notes, gates); _note_override(notes, gates)
    text = notes.read_text()
    assert text.startswith('# hand-written') and text.count('## Printability override') == 1 and 'test override' in text


# --- released STLs ----------------------------------------------------------------------------------------------------

@pytest.fixture(scope='module')
def v25():
    return pr.load_manifold(REL/'v25/dual-170hx-continuous-v25.stl')


def test_v25_fails_on_the_pocket_wedges(v25):
    r = pr.solid_regions(v25, pr.duct_spec(V25))
    assert not r.passed
    for cx in V25.card_x:   # the corner wedge at the bay floor, 18 mm outward of each card centre, below and beside the return
        f = next(f for f in r.failures if f['bbox_xy'][0] < cx-17 < f['bbox_xy'][2] and f['bbox_xy'][1] < 24 < f['bbox_xy'][3])
        assert f['z_range'][0] < 56 and f['z_range'][1] > 69 and f['max_width_mm'] > 3
    assert set(r.summary['allowed_solid_volume_mm3']) >= {'fan plate', 'flange fillet', 'splitter web', 'connector return, floor strip'}


def test_v25_return_tip_needs_support(v25):
    r = pr.unsupported_overhang(v25, pr.duct_spec(V25))
    assert not r.passed and not r.summary['tier_a_failures'] and not r.summary['floating_islands']
    tips = r.summary['tier_b_failures']
    assert len(tips) == 2   # where the slicer grows its two support trees (releases/v25: 1.75 g, contact at y 50.4-51.3, z 63.2)
    for f, cx in zip(sorted(tips, key=lambda f: f['centre'][0]), V25.card_x):
        assert near(f, (cx-1.4, 50.5, 63.3), .3) and f['max_angle_deg'] > 60


def test_v25_seals_and_a_seat_face_cavity_fails(v25):
    spec = pr.duct_spec(V25)
    assert pr.seal(v25, spec).passed
    cx = V25.card_x[0]   # trial-V26 reproducer: a 2 x 0.8 mm hole down from the seat face into the return's floor strip
    r = pr.seal(v25-cube([2, .8, 5], [cx-15, 25.9, 65.5]), spec)
    assert not r.passed and not r.summary['b_voxels']['leaks']
    f = r.summary['a_undesigned_voids'][0]
    assert f['bbox_xy'] == pytest.approx([cx-15, 25.9, cx-13, 26.7], abs=.02) and f['z_range'][0] < 65.7 and f['z_range'][1] > 69.8


def test_v24_overhangs_pass():
    assert pr.unsupported_overhang(pr.load_manifold(REL/'v24/dual-170hx-continuous-v24.stl'), pr.duct_spec(V24)).passed


def test_seat_coverage_v25_and_v28_latch_notch_v27_leaks(v25):
    # V23-V25 and V28 cover everything outside the connector clearances, but the 3 x 8.6 mm latch notch beside the housing
    # leaves ~35.5 mm2 per card open (V29's lever-shaped notch: 21.5)
    for solid, g in ((v25, V25), (pr.load_manifold(REL/'v28/dual-170hx-continuous-v28.stl'), V28)):
        r = pr.seat_coverage(solid, pr.duct_spec(g))
        assert not r.passed and len(r.failures) == 2 and all('open_mm2' in f for f in r.failures)
        for seat, cx in zip(r.summary['seats'], g.card_x):
            assert seat['uncovered_mm2'] < .2 and 35 < seat['open_mm2'] < 36
    r = pr.seat_coverage(pr.load_manifold(REL/'v27/dual-170hx-continuous-v27.stl'), pr.duct_spec(V27))
    assert not r.passed and len([f for f in r.failures if 'uncovered_mm2' in f]) == 2
    for seat, cx in zip(r.summary['seats'], V27.card_x):   # beside the latch wall, between the housing clearance and the rounded bay wall
        assert seat['uncovered_mm2'] > 30
        b = seat['patches'][0]['bbox_xy']
        assert b[0] == pytest.approx(cx-5.95, abs=.02) and b[2] < cx-2.8 and b[1] == pytest.approx(27.2, abs=.02) and b[3] == pytest.approx(47.4, abs=.02)


def test_parallel_gates_match_serial():
    """run_gates in a process pool (an STL path, or a trimesh) gives the serial result, key order included; the slicer
    gate runs after slicer_after()."""
    import json
    import trimesh
    from duct.params import COLLECTOR_V2
    from duct.cad.export import collector_names
    stl = REL/'collector-v2'/collector_names('collector-v2')[0]; spec = pr.collector_spec(COLLECTOR_V2)
    serial = json.dumps(pr.run_gates(stl, spec, workers=1))
    assert json.dumps(pr.run_gates(stl, spec, workers=4)) == serial
    assert json.dumps(pr.run_gates(trimesh.load(stl), spec, workers=2)) == serial
    order = []
    def slicer_after(): order.append('waited')
    def fake_slicer(stl, t, spec, **kw): order.append('slicer'); return pr.GateResult('slicer_support', True, {})
    import unittest.mock
    with unittest.mock.patch.object(pr, 'slicer_support', fake_slicer):
        r = pr.run_gates(stl, spec, slicer={}, workers=2, slicer_after=slicer_after)
    assert order == ['waited', 'slicer'] and list(r['gates']) == [*json.loads(serial)['gates'], 'slicer_support']
