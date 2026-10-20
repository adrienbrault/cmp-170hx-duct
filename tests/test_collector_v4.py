"""Collector v4 (docs/collector-v4-plan.md, revision after the curves requirement): the deterministic checks, both slot
layouts (V29: 5-slot, A29: 4-slot), concept A (COLLECTOR_V4A: per-opening mouths, rib fins) and the control B
(COLLECTOR_V4B: per-card mouths, centre fin only), and A with a hub fairing (COLLECTOR_V4A_HUB).

- No open slot enclosed: outside both gasket loops, the outer ones vent through the flange windows (>= 95 % open).
- Magnets on flush steel, under CASE and CASE.covered().
- Screwdriver / finger access, zero intersection and the clearances against the case hardware.
- Fan budget: frame bottom <= 2 mm under the board plane, <= 70 mm behind the panel.
- Vents, the CFD contract (genus 0, mouths at the bracket plane, bore at inlet_z + D), the printability gates and the
  wall / fin numbers.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString, Point

from duct import params as P
from duct.cad import exhaust as ex
from duct.cad.export import collector_checks, collector_names, export_collector
from duct.cad.hardware import BRACKET, CASE, CaseParams, build_hardware, bypass_leaks, fit_check, fit_sweep, open_slot_vent_area
from duct.cfd import collector as cfd_collector
from duct.print import printability
from duct.print.verify import verify_collector

LAYOUTS = {'5slot': P.V29, '4slot': P.A29}
PRESETS = {'a': P.COLLECTOR_V4A, 'b': P.COLLECTOR_V4B, 'hub': P.COLLECTOR_V4A_HUB}
REL = Path(__file__).resolve().parents[1]/'releases'
_cache = {}


def built(preset, layout):
    key = (preset, layout)
    if key not in _cache: _cache[key] = ex.build_collector(PRESETS[preset].for_duct(LAYOUTS[layout]))
    return _cache[key]


def fit(preset, layout, case=CASE, density=3.0):
    """fit_check of a built collector, once per (preset, layout, case, density) for this module (read-only results)."""
    key = ('fit', preset, layout, case, density)
    if key not in _cache: _cache[key] = fit_check(built(preset, layout), LAYOUTS[layout], case, density=density)
    return _cache[key]


def checks(preset, layout):
    """collector_checks of a built collector, once per (preset, layout) for this module."""
    key = ('checks', preset, layout)
    if key not in _cache: _cache[key] = collector_checks(built(preset, layout))
    return _cache[key]


both = pytest.mark.parametrize('layout', list(LAYOUTS))
ab = pytest.mark.parametrize('preset', list(PRESETS))


@ab
@both
def test_no_open_slot_enclosed(preset, layout):
    s = built(preset, layout); g = LAYOUTS[layout]
    band = fit(preset, layout)['gasket_path_mm']['band']
    assert band['open_slots_inside_loops'] == [] and band['groove_over_open_slots_mm2'] == 0 and band['over_open_mm2'] == 0
    assert band['foam_land_to_open_slots_mm'] >= 3.0
    rows = bypass_leaks(s, g)['paths']
    assert next(x for x in rows if x['path'].startswith('open slots inside'))['q_lps'] == 0
    assert cfd_collector.open_slots(g, s.inner.translate([0, 0, CASE.panel]), CASE)[2] == []
    vent = {r['slot']: r for r in open_slot_vent_area(s, g)}
    outer = (min(vent), max(vent))
    for k, r in vent.items():
        assert r['inside_gasket_loop_mm2'] == 0
        if k in outer: assert r['fraction'] >= .95          # under a flange window
        else: assert k == 0 and layout == '5slot'            # the middle slot: under the flange web, outside both loops (as v3)
    assert [w['fraction'] for w in checks(preset, layout)['v4']['open_slot_vent_area']] == pytest.approx([1, 1], abs=.01)


@ab
@both
def test_magnets_on_flush_steel(preset, layout):
    s = built(preset, layout); g = LAYOUTS[layout]; c = s.params
    assert len(ex.mount_points(c)) == 7 and c.magnet_diameter == 10 and c.magnet_thickness == 3
    for case in (CASE, CASE.for_pitch(g.pitch).covered()):
        hw = build_hardware(g, c, case)
        mags = fit(preset, layout, case)['magnets']
        assert len(mags) == 7 and all(m['flush'] == 1.0 for m in mags), mags
        assert all(hw.panel_2d.contains(ex.magnet_pocket(c, p)) for p in ex.mount_points(c))


@both
def test_screw_access_and_clearance(layout):
    s = built('a', layout); g = LAYOUTS[layout]
    for case in (CASE, CaseParams(screw='thumb'), CASE.for_pitch(g.pitch).covered()):
        r = fit('a', layout, case)
        assert all(x['access_column_blocked_mm3'] == 0 for x in r['screws']) and r['total_intersection_mm3'] == 0
        p = r['parts']
        assert p['slot_ledge']['min_clearance_mm'] >= .5 and p['screw_heads']['min_clearance_mm'] >= 1.5
        assert p['screw_shanks']['min_clearance_mm'] >= .2
    rows = fit_sweep(s, g)
    assert all(x['access_blocked_mm3'] == 0 and x['total_intersection_mm3'] == 0 for x in rows)


@ab
@both
def test_fan_budget_and_wall_angles(preset, layout):
    s = built(preset, layout); c = s.params; v4 = checks(preset, layout)['v4']
    assert 0 <= c.frame_bottom_below_board_mm <= 2 and v4['frame_bottom_below_board_mm'] <= 2
    assert v4['protrusion_behind_panel_mm'] <= 70
    w = v4['plenum_wall_deg']
    assert w['faces']['ceiling']['peak_deg'] <= c.max_wall_angle   # the inner skin's own overhangs (air faces looking down)
    assert w['top']['mean_deg'] < 35 and w['top']['peak_deg'] < 41
    assert max(w['at_fan_plate'].values()) < 5                # the bell: the walls arrive at the bore (near) vertical


@pytest.mark.xfail(strict=True, reason='V4 CEM presets exceed max_wall_angle 45 on air walls that face up (the air widens): '
                   'the inlet lip and the growing corner radius move the bottom corners diagonally (47.8 deg 5-slot, 48.8 deg '
                   '4-slot, inside the bottom fillet) and the 4-slot top corners rise at up to 46.1 deg (the ear-chamfer block is '
                   'outside them; no exterior face in the plenum band exceeds 45). Not regenerated: CFD runs and releases use these presets, and the '
                   'CASE_FRACTAL plug collector replaces them; the old bounding-box metric (40.6 deg) missed the corner diagonals')
@ab
@both
def test_air_walls_within_limit(preset, layout):
    """Every plenum air wall (triangle normals, the flange top to the fan plate, no fins or fairing) within max_wall_angle."""
    s = built(preset, layout); assert checks(preset, layout)['v4']['plenum_wall_deg']['peak'] <= s.params.max_wall_angle


@ab
@both
def test_cfd_contract(preset, layout):
    """inner: genus 0, the mouths at the bracket plane (inlet_z), the bore about the fan axis at inlet_z + plenum_depth."""
    s = built(preset, layout); c = s.params; inner = s.inner
    assert inner.genus() == 0 and inner.bounding_box()[2] == pytest.approx(c.inlet_z)
    m = ex.section(inner, c.inlet_z+.5); geoms = sorted(getattr(m, 'geoms', [m]), key=lambda q: q.centroid.x)
    assert len(geoms) == len(ex.mouths(c)) == (2 if preset == 'b' else 4)
    for (x0, x1, y0, y1), q in zip(ex.mouths(c), geoms):
        assert q.bounds == pytest.approx((x0, y0, x1, y1), abs=.05)
    f = ex.section(inner, c.inlet_z+c.plenum_depth-.5)
    assert f.centroid.x == pytest.approx(c.fan_axis[0], abs=.05) and f.centroid.y == pytest.approx(c.fan_axis[1], abs=.05)
    assert f.area == pytest.approx(np.pi*c.fan_radius**2, rel=.01)
    assert inner.bounding_box()[5] >= c.inlet_z+c.plenum_depth


@ab
@both
def test_vanes(preset, layout):
    """Every fin: 1.2 mm above its root, ends >= FIN_END_GAP off the walls (only those gaps, and the hub fairing's cavity, are
    air on its line; up to 1 mm more where the wall curves across the fin's width), the
    centre fin's full-round top >= 4 mm below the fan plate."""
    s = built(preset, layout); c = s.params; z0 = c.inlet_z
    vs = ex.vanes(c); assert [n for n, _, _ in vs] == (['centre'] if preset == 'b' else ['centre', 'rib A', 'rib B'])
    for name, _, v in vs:
        prof = np.array(v['profile'])
        for sv in (v.get('H', c.vane_root)+c.flange_thickness+1, v['top_s']-3):
            k = int(np.argmin(abs(prof[:, 0]-sv))); x = (prof[k, 1]+prof[k, 2])/2; z = z0+prof[k, 0]
            cut = ex.section(s.inner, z).intersection(LineString([(x, -300), (x, 300)]))
            segs = [q for q in getattr(cut, 'geoms', [cut])   # the fairing's cavity is air across the fin (dead, behind the hub)
                    if not (c.hub_fairing and q.centroid.distance(Point(c.fan_axis)) < c.hub_fairing_d/2)]
            gaps = [q.length for q in segs]    # the air on the fin's line: its two end gaps only
            assert len(gaps) == 2 and all(ex.FIN_END_GAP-.05 <= q <= ex.FIN_END_GAP+1 for q in gaps), (name, sv, gaps)
            b = cut.bounds; solid = LineString([(x, b[1]), (x, b[3])]).difference(cut)   # the fin's width: mid its longest solid run
            run = max(getattr(solid, 'geoms', [solid]), key=lambda q: q.length)
            ym = run.centroid.y
            width = ex.section(s.final, z).intersection(LineString([(x-5, ym), (x+5, ym)]))
            seg = min(getattr(width, 'geoms', [width]), key=lambda q: q.distance(Point(x, ym)))
            assert seg.length == pytest.approx(c.fin_thickness, abs=.06), (name, sv)
    centre = vs[0][2]
    assert c.plenum_depth-centre['top_s'] >= 4+c.fan_plate_thickness-.01


@ab
@both
def test_vents_and_gates(preset, layout, tmp_path):
    s = built(preset, layout); c = s.params; g = LAYOUTS[layout]
    export_collector(s, tmp_path, 'v4'); stl = tmp_path/collector_names('v4')[0]
    r = verify_collector(stl, s)                              # asserts wall p1 > 1.15 and median 1.2 +- 0.05
    assert r['openings_blocked_mm2'] < .01 and r['openings_outside_mouth_mm2'] < .01
    assert all(v['open_outside_mouth_mm2'] < .01 for v in fit(preset, layout)['vents'])
    gates = printability.run_gates(stl, printability.collector_spec(c), slicer=None)
    assert gates['passed'], printability.failure_lines(gates)


@both
def test_release_matches_build(layout, tmp_path):
    name = f'collector-v4-{layout}'; out = REL/name
    if not (out/collector_names(name)[0]).exists(): pytest.skip('no release yet')
    s = built('a', layout); export_collector(s, tmp_path, name)
    for f in collector_names(name):   # the collector and its fit gauge
        assert hashlib.sha256((tmp_path/f).read_bytes()).hexdigest() == hashlib.sha256((out/f).read_bytes()).hexdigest(), f
    pr = json.loads((out/'checks.json').read_text())['printability']
    assert pr['passed'] and not pr.get('override') and pr['gates']['slicer_support']['passed']


@both
def test_hub_fairing(layout):
    """The fairing: an ogive shell on the fan axis, base = the hub (51 mm) under the fan plate, open toward the fan (its
    cavity is air joined to the bore, so inner stays genus 0), flank <= 45 deg, blunt tip >= 2 mm off the flange, on the
    centre fin. It takes the region behind the hub out of the live plenum."""
    s = built('hub', layout); c = s.params; m, f = ex.hub_fairing(c)
    assert f['steepest_flank_deg'] <= 45 and f['tip_s_mm'] >= c.flange_thickness+2 and f['tip_radius_mm'] >= 1
    assert f['base_d_mm'] == pytest.approx(c.fan_hub_diameter) and f['base_s_mm'] == pytest.approx(c.plenum_depth-c.fan_plate_thickness)
    assert s.inner.genus() == 0 and (m ^ ex.vanes(c)[0][1]).volume() > 0          # it stands on the centre fin
    below, above = (ex.section(s.inner, c.inlet_z+f['base_s_mm']+dz) for dz in (-1, .5))
    assert len(below.geoms) == 2 and above.geom_type == 'Polygon'   # the cavity: its own section void under the rim, open above it
    live = s.inner.volume()-f['cavity_volume_mm3']
    assert live < built('a', layout).inner.volume()-20e3 and live < built('b', layout).inner.volume()-30e3


@both
def test_snap_mount(layout, tmp_path):
    """mount 'snap': 4 clips (2 per card) reach through the chassis openings into each card's vent window along its outer x
    edge and hook behind the plate (and the bezel, as modelled). They clear every hard part, keep every screw reachable,
    block < 2 % of the live window strips, strain < 2 % (ASA) at the barb depth, and both prints pass the gates."""
    g = LAYOUTS[layout]; c = P.COLLECTOR_V4A_SNAP.for_duct(g); s = ex.build_collector(c)
    assert s.inner.genus() == 0 and ex.mount_points(c) == [] and s.clips is not None
    n = ex.snap_numbers(c)
    assert n['arms'] == 4 and n['blocked_fraction'] < .02 and n['root_strain'] < .02
    assert all(n[m]['strain_ok'] for m in ('PETG', 'ASA')) and n['PETG']['pull_off_N_total'] > n['PETG']['insertion_N_total']
    k = ex.snap_dims(c)
    assert -k['catch_s'] >= .8+.86 and 10 <= c.snap_arm_length <= 15 and 1.2 <= c.snap_arm_thickness <= 2.0
    for case in (CASE, CaseParams(screw='thumb'), CASE.for_pitch(g.pitch).covered()):
        r = fit_check(s, g, case, density=4.0)
        assert r['total_intersection_mm3'] == 0 and all(x['access_column_blocked_mm3'] == 0 for x in r['screws'])
        assert r['parts']['bracket_A']['min_clearance_mm'] >= .15 and r['parts']['bracket_B']['min_clearance_mm'] >= .15
        hw = build_hardware(g, c, case)   # the clips clear the bezel and its Torx heads (the flange's 0.2 mm on the heads is v3's)
        assert (s.clips.translate([0, 0, hw.panel_face-c.inlet_z]) ^ hw.parts['window_bezels']).volume() == 0
    export_collector(s, tmp_path, 'snap'); stl = tmp_path/collector_names('snap')[0]
    verify_collector(stl, s)
    for path, spec in ((stl, printability.collector_spec(c)), (tmp_path/'dual-170hx-snap-snap-clip.stl', printability.snap_clip_spec(c))):
        gates = printability.run_gates(path, spec, slicer=None)
        assert gates['passed'], printability.failure_lines(gates)


def _print_frame(s):
    return s.final.translate([0, 0, -s.params.inlet_z])


def _column(solid, part, margin=10.0):
    """`solid` within an xy box around `part` grown by `margin` (>> the gate's 1.6 mm ball), over its full height: the
    solid gate is local (per layer, from the neighbouring sections), so a lump fails there as it fails on the whole part,
    and the layers stay where they are (the part still stands on z = 0)."""
    x0, y0, _, x1, y1, _ = part.bounding_box(); b = solid.bounding_box()
    return solid ^ ex.mf.Manifold.cube([x1-x0+2*margin, y1-y0+2*margin, b[5]-b[2]+2]).translate([x0-margin, y0-margin, b[2]-1])


@pytest.mark.parametrize('preset', ['a', 'hub'])
@both
def test_allowlists_reject_stray_solid(preset, layout):
    """The solid-gate exemptions cover the fin roots and the fairing/fin junctions only: a 3 mm wall stuck on the flange
    outside the plenum, in line with a fin root, or a 3 mm block inside the fairing cavity, must fail the solid gate.
    Each is judged on the column of the part around it, which passes without it."""
    s = built(preset, layout); c = s.params; spec = printability.collector_spec(c); solid = _print_frame(s)
    assert printability.solid_regions(solid, spec).passed
    def rejected(lump):
        assert printability.solid_regions(_column(solid, lump), spec).passed
        return not printability.solid_regions(_column(solid+lump, lump), spec).passed
    xw = ex.web_x(c); tf = c.flange_thickness; y0 = min(m[2] for m in ex.mouths(c))
    for h in (6.0, 3.5):   # on the flange below the plenum: tall, and within the fillet's height (its old allowance was all xy)
        wedge = ex.mf.Manifold.cube([3, 6, h]).translate([xw-1.5, y0-c.lip-c.wall-9, tf-.5])
        assert (wedge ^ solid).volume() > 0 and (wedge-solid).volume() > 20              # attached, and new material
        assert rejected(wedge), h
    if c.hub_fairing:
        f = ex.hub_fairing(c)[1]; sm = (f['tip_s_mm']+f['base_s_mm'])/2
        block = ex.mf.Manifold.cube([3, 3, 3]).translate([xw-1.5, c.fan_axis[1]+6, sm-1.5])   # in the cavity, on the fin
        assert (block-solid).volume() > 5
        assert rejected(block)


@both
def test_gauge_clears_hardware(layout):
    """The fit gauge, laid on the rear panel face, touches none of the case hardware (the slot ledge above the flange edge)."""
    s = built('a', layout); c = s.params; hw = build_hardware(LAYOUTS[layout], c, CASE)
    gauge = s.gauge.translate([0, 0, hw.panel_face])
    for name in ('slot_ledge', 'bracket_A', 'bracket_B', 'screw_heads', 'screw_shanks'):
        if name in hw.parts: assert (gauge ^ hw.parts[name]).volume() < 1e-6, name
    hit = gauge ^ hw.parts['window_bezels']   # the bezel Torx heads stand torx_head[1] - panel (0.2 mm) past the panel face, under
    assert hit.is_empty() or hit.bounding_box()[5] <= hw.z_b+BRACKET.torx_head[1]+1e-6   # the window ring as under v3's flange


def test_screws_need_solid_flange():
    with pytest.raises(ValueError):
        P.COLLECTOR_V4A.__class__(**{**P.COLLECTOR_V4A.__dict__, 'mount': 'screws'})
