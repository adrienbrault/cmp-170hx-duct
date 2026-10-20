"""CASE_FRACTAL (recessed slot bay) and the plug fit gauge."""
import pytest
import shapely
import trimesh

from duct.cad import plug
from duct.cad.exhaust import card_windows, snap_dims, snap_sites
from duct.cad.hardware import CASE_FRACTAL
from duct.params import COLLECTOR_V4A_SNAP, V29
from duct.print import printability as pr

C = COLLECTOR_V4A_SNAP.for_duct(V29)


def test_bay_geometry():
    rec = plug.recess_outline(C, CASE_FRACTAL); W, H, _, _ = CASE_FRACTAL.recess
    x0, y0, x1, y1 = rec.bounds
    assert abs((x1-x0)-W) < 1e-6 and abs((y1-y0)-H) < 1e-6
    ops = plug.slot_openings_x(C); assert len(ops) == 7 and x0 < ops[0][0] and ops[-1][1] < x1   # all 7 slots inside the bay
    xs = plug.divider_x(C); assert len(xs) == 6
    for (mx0, mx1, _, my1), (wx0, wx1, _, wy1) in zip(plug.card_mouths_plug(C, CASE_FRACTAL), card_windows(C)):
        assert mx0 in xs and mx1 in xs and mx0 < wx0 and wx1 < mx1 and my1 > wy1   # each mouth: bar to bar, around its window


def test_gauge(tmp_path):
    p = plug.plug_gauge_parts(C, CASE_FRACTAL)
    assert p['outline'].within(plug.recess_outline(C, CASE_FRACTAL).buffer(-plug.GAUGE['clearance']+1e-3))
    ops = plug.slot_openings_x(C); y0, y1 = p['mouths'][0][2], C.bracket_top_y
    assert p['plate'].covers(shapely.geometry.box(ops[3][0], y0, ops[3][1], y1))   # the slot between the cards: under the plate
    for a, b in (ops[0], ops[-1]):   # the outer slots: left open, the plate's edge short of them
        assert p['outline'].distance(shapely.geometry.box(a, y0, b, y1)) >= plug.PLUG['edge_margin']-1e-6
    gauge = plug.build_plug_gauge(C, CASE_FRACTAL); stl = tmp_path/'g.stl'; pr.export_stl(gauge, stl)
    # as fitted: the print frame turned back (y -> -y, z -> case side down), the gauge face on the bare bar crowns
    hw = plug.build_recess_hardware(V29, C, CASE_FRACTAL); T = plug.GAUGE['plate']
    fitted = gauge.mirror([0, 1, 0]).mirror([0, 0, 1]).translate([0, 0, hw['z_b']+CASE_FRACTAL.divider[1]+T])
    steel = {k: m for k, m in hw['parts'].items() if k != 'border'}
    assert sum((fitted ^ m).volume() for m in steel.values()) < 1e-3   # the hooks clear the plates, bezels, Torx heads, bars
    cp = plug.plug_params(C, CASE_FRACTAL)   # each catch: within the clip's catch_gap behind the bracket plate
    pulled = fitted.translate([0, 0, cp.snap_catch_gap+.05])
    hooked = (pulled ^ steel['bracket_plates']).volume(); assert hooked > 1e-2, hooked   # all four barbs bear on the plates
    assert snap_sites(cp) == snap_sites(plug.plug_params(COLLECTOR_PLUG_BASE.for_duct(V29), CASE_FRACTAL))   # the collector's sites
    tw, L = plug.GAUGE['tongue']   # the tongue's bending strain with the barb pushed in past the window edge
    assert 1.5*snap_dims(cp)['barb_u']*tw/L**2 < .012
    m = trimesh.load(stl); assert m.is_watertight and m.body_count == 1 and m.bounds[0][2] == pytest.approx(0)
    g = pr.run_gates(stl, plug.plug_gauge_spec(C, CASE_FRACTAL))
    assert g['passed'], pr.failure_lines(g)


from duct.cad import exhaust as ex  # noqa: E402

_PLUG = {}


def plug_built():
    if 'b' not in _PLUG:
        base = COLLECTOR_PLUG_BASE.for_duct(V29)
        cp = plug.plug_params(base, CASE_FRACTAL); _PLUG['b'] = ex.build_collector(cp)
    return _PLUG['b']


from duct.params import COLLECTOR_PLUG_140, COLLECTOR_PLUG_BASE  # noqa: E402


def test_plug_collector_fits_and_gates():
    """The plug collector (B-style plenum, hub fairing, snap clips) for CASE_FRACTAL: every dimension from the case, zero
    intersection with the bay (floor, bars, plates, bezels, Torx heads, border) and the keep-outs, the clips included; the
    plug top flush with the border plane; the three geometric printability gates pass."""
    s = plug_built(); c = s.params; W, H, depth, r = CASE_FRACTAL.recess
    assert c.flange_mode == 'plug' and c.mount == 'snap' and not c.rib_fins and c.hub_fairing
    assert c.snap_catch_depth == pytest.approx(CASE_FRACTAL.divider[1]+plug.PLUG['foam_gap']+0.86)
    fit = plug.plug_fit_check(s, V29, CASE_FRACTAL)
    assert fit['total_mm3'] == 0 and fit['plug_top_above_border_mm'] == pytest.approx(0, abs=1e-6), fit
    assert s.inner.genus() == 0
    assert ex.flange_outline(c).within(plug.recess_outline(c, CASE_FRACTAL).buffer(-plug.PLUG['clearance']+.05))
    ops = plug.slot_openings_x(c)
    for a, b in (ops[0], ops[-1]):   # slots -3 / +3 stay open: the plug (and its clips) stop short of their openings
        assert ex.flange_outline(c).distance(shapely.geometry.box(a, -200, b, 200)) >= plug.PLUG['edge_margin']-1e-6
        assert s.clips is None or not (a < s.clips.bounding_box()[0] < b or a < s.clips.bounding_box()[3] < b)
    for w in c.vent_rects:   # every vent window opening stays open, inside its mouth
        assert any(m[0] <= w[0] and w[1] <= m[1] and m[2] <= w[2] and w[3] <= m[3] for m in ex.card_mouths(c))
    w = ex.air_wall_angles(c)   # every plenum air wall within the 45 deg design limit, by triangle normals (no xfail here)
    assert max(w['ceiling']['peak_deg'], w['floor']['peak_deg']) <= c.max_wall_angle, w
    assert not ex.plug_pockets(c).is_empty and s.final.volume() < 100e3   # hollow plug: ~92 cm3, not 133
    sol = s.final.translate([0, 0, -c.inlet_z]); spec = pr.collector_spec(c)
    for gate in (pr.unsupported_overhang, pr.solid_regions, pr.seal):
        r_ = gate(sol, spec); assert r_.passed, (gate.__name__, r_.failures[:3])


def test_plug_collector_140_fits_and_gates():
    """The plug with the 140 mm pull fan: zero intersection with the bay, its plate inside the recess's x span (clear of the
    PSU and the I/O side), every plenum wall within 45 deg, the three geometric gates."""
    c = plug.plug_params(COLLECTOR_PLUG_140.for_duct(V29), CASE_FRACTAL); s = ex.build_collector(c)
    fit = plug.plug_fit_check(s, V29, CASE_FRACTAL); assert fit['total_mm3'] == 0, fit
    assert s.inner.genus() == 0 and c.fan_size == 140
    rx0, _, rx1, _ = plug.recess_outline(c, CASE_FRACTAL).bounds; px0, _, px1, _ = ex.plate_outline(c).bounds
    assert rx0 <= px0 and px1 <= rx1
    w = ex.air_wall_angles(c); assert max(w['ceiling']['peak_deg'], w['floor']['peak_deg']) <= c.max_wall_angle, w
    sol = s.final.translate([0, 0, -c.inlet_z]); spec = pr.collector_spec(c)
    for gate in (pr.unsupported_overhang, pr.solid_regions, pr.seal):
        r_ = gate(sol, spec); assert r_.passed, (gate.__name__, r_.failures[:3])


def test_plug_foam_layouts():
    c = plug_built().params
    bars = plug.plug_foam(c, CASE_FRACTAL)
    assert len([f for f in bars if 'bar crown' in f['name']]) == 4
    face = ex.flange_outline(c)
    for f in bars:   # every strip under the face lies on it, the outer crown foam to the plug's top included
        assert face.buffer(1e-6).contains(shapely.geometry.box(f['box'][0], f['box'][2], f['box'][1], f['box'][3])), f['name']
    xs = sorted(f['x'] for f in bars if 'bar crown' in f['name'])
    assert xs == pytest.approx(sorted(x for pair in plug.bounding_bars(c) for x in pair), abs=.01)
    assert not any(f['name'].startswith('top run') for f in bars)   # the dam replaces the lateral top run
    lat = plug.plug_foam(c, CASE_FRACTAL, 'bars-lateral'); assert any(f['name'].startswith('top run') for f in lat)


def test_top_dam_closes_the_top():
    """The dam lies on the bracket plates (inside their top edge), clear of the window bezels and their Torx heads and of the
    mouths, and with the crown foam it spans each card from bounding bar to bounding bar: nothing from the openings above
    the bracket tops reaches a mouth under the face."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    from duct.cad.hardware import BRACKET
    c = plug_built().params; g = V29; case = CASE_FRACTAL
    d0, d1 = plug.top_dam(c, case); hw = plug.build_recess_hardware(g, c, case)
    assert d1 <= c.bracket_top_y-.25 and d0 >= c.mouth_y[1] and d0 >= hw['parts']['window_bezels'].bounding_box()[4]
    fs = plug.plug_foam(c, case)
    band = unary_union([box(f['box'][0], f['box'][2], f['box'][1], f['box'][3]) for f in fs if 'box' in f]).intersection(box(-200, d0, 200, d1))
    for a, b in plug.bounding_bars(c):   # foam all across the card, bar flanks included (the soft blocks ride over them)
        across = box(a, d0, b, d1).difference(band)
        assert across.area < 1e-6, across.bounds
    blocks = [f for f in fs if 'dam block' in f['name']]
    assert len(blocks) == 4 and all(f['compressed'] == pytest.approx(plug.plug_placement(c, case)) for f in blocks)
    assert BRACKET.torx_head[1] < plug.plug_placement(c, case)



def test_plug_release_dry_run(tmp_path):
    """What release_collector runs, short of slicing: export, the CAD checks (JSON), verify (walls, openings left open)
    and the geometric gates on the exported STL."""
    import json
    from duct.cad.export import collector_names, export_collector
    from duct.print.verify import verify_collector
    s = plug_built(); r = export_collector(s, tmp_path, 'plug'); json.dumps(r, default=float)
    stl = tmp_path/collector_names('plug')[0]
    v = verify_collector(stl, s); assert v['openings_blocked_mm2'] < .01 and v['openings_outside_mouth_mm2'] < .01
    g = pr.run_gates(stl, pr.collector_spec(s.params)); assert g['passed'], pr.failure_lines(g)


def test_fractal_gauge_release_matches_build(tmp_path):
    """releases/fractal-fit-gauge is what the code builds: a CASE_FRACTAL change (the measurements) forces a regen."""
    import hashlib
    from pathlib import Path
    rel = Path(__file__).resolve().parents[1]/'releases'/'fractal-fit-gauge'/'fractal-plug-fit-gauge.stl'
    stl = tmp_path/'g.stl'; pr.export_stl(plug.build_plug_gauge(C, CASE_FRACTAL), stl)
    assert hashlib.sha256(stl.read_bytes()).hexdigest() == hashlib.sha256(rel.read_bytes()).hexdigest()
