"""Case / card reference hardware at the cards' rear (duct.cad.hardware) and the collectors' fit against it.

v1 predates the hardware model: its +y flange band lands on the slot ledge, tabs and screws (pinned here as the reason
for v2). v2 must clear every hard part, leave every slot screw reachable and seal on steel all round, but only with
covers in the empty slots (CASE_COVERED): its single gasket loop encloses the middle slot. The author's case (CASE) has no
covers: every slot without a card is open. v3 seals per card: one gasket loop per card on the ribs either side of its
opening pair, the middle and outer slots outside both loops, whatever they hold.

Two slot layouts follow the duct's card pitch (params.slot_layout): 5-slot (60.96, one empty slot between the cards: slots
-3 ... 3) and 4-slot (40.64, adjacent cards: slots -2.5 ... 2.5). The 4-slot duct (A29) is on branch adjacent-slots; until it
lands, G4 stands in for it (the hardware only reads pitch and chamber_length).
"""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import manifold3d as mf
import numpy as np
import pytest
from shapely.geometry import box

from duct.cad.exhaust import FIN_END_GAP, bare_fan_air, build_collector, card_mouths, gasket_loops, section, web_x
from duct.cad.export import collector_names, export_collector
from duct.cad.export import _hub_shadow
from duct.cad.hardware import (BRACKET, CASE, CASE_COVERED, CaseParams, bracket_z, build_hardware, bypass_leaks, fit_check, gasket_band,
                                 hardware_meshes, windows)
from duct.cfd.domain import DOMAIN
from duct import params as P
from duct.params import COLLECTOR_V1, COLLECTOR_V2, COLLECTOR_V3, COLLECTOR_V3L, V27, V28, V29, slot_layout
from duct.print.verify import verify_collector

REL2 = Path(__file__).resolve().parents[1]/'releases/collector-v2'
REL3 = Path(__file__).resolve().parents[1]/'releases/collector-v3'
BLANK = CASE_COVERED   # v1 / v2's assumption: solid covers in slots -3, 0, +3 (v2's PRINT-NOTES: cover or tape them)
G4 = getattr(P, 'A29', None) or SimpleNamespace(pitch=40.64, chamber_length=62.0)   # the 4-slot duct (A29: V29 at 2-slot pitch)


@pytest.fixture(scope='module')
def v1():
    return build_collector(COLLECTOR_V1)


@pytest.fixture(scope='module')
def v2():
    return build_collector(COLLECTOR_V2)


@pytest.fixture(scope='module')
def fit1(v1):
    return fit_check(v1, V27)


@pytest.fixture(scope='module')
def fit2(v2):
    return fit_check(v2, V27, BLANK)


@pytest.fixture(scope='module')
def v3():
    return build_collector(COLLECTOR_V3)


@pytest.fixture(scope='module')
def fit3(v3):
    return fit_check(v3, V27)


def test_bracket_plane_follows_the_duct_and_the_cfd():
    """Bracket outer face = chamber length + card length, the CFD's bracket plane, for every chamber length."""
    assert CASE.card_length == DOMAIN.card_envelope
    for g in (V27, V28):
        assert bracket_z(g) == g.chamber_length+DOMAIN.card_envelope
    assert COLLECTOR_V1.inlet_z == bracket_z(V27)


def test_hardware_solids_and_cem_dimensions():
    hw = build_hardware(V27, COLLECTOR_V1)
    for name, m in hw.parts.items():
        assert m.volume() > 0 and m.status() == mf.Error.NoError, name
    assert len(hw.openings) == len(CASE.slots) == 7
    for k in (-1, 0, 1):    # 20.32 mm slot pitch (CEM Fig 1-3)
        assert abs(hw.openings[k+1][0]-hw.openings[k][0]-CASE.slot_pitch) < 1e-9
    # Dual bracket 38.74 wide (CEM Fig 9-13), top tab reaching 11.43 from the plate's inner face
    bb = hw.parts['bracket_A'].bounding_box()
    assert abs(bb[3]-bb[0]-BRACKET.width_dual) < 1e-6 and abs(bb[5]-(hw.z_b-BRACKET.sheet+BRACKET.tab_depth)) < 1e-6
    assert abs(bb[4]-COLLECTOR_V1.bracket_top_y) < 1e-6
    # Openings stop under the ledge; the ledge is the panel folded outward
    assert max(o[3] for o in hw.openings.values()) < hw.ledge_bottom
    lb = hw.parts['slot_ledge'].bounding_box()
    assert abs(lb[2]-hw.z_b) < 1e-6 and lb[5] > hw.panel_face


def test_slot_screws_are_outside_the_case():
    hw = build_hardware(V27, COLLECTOR_V1)
    assert CASE.covers == () and CASE.open_slots == (-3, 0, 3)     # the author's case: every slot without a card is open
    assert len(hw.screws) == 2+2 and len(build_hardware(V27, COLLECTOR_V1, BLANK).screws) == 7
    for s in hw.screws:   # 7.24 mm from the plate (CEM Fig 9-5): the head clears the panel's outer face
        assert abs(s['z']-(hw.z_b-BRACKET.sheet+BRACKET.slot_depth)) < 1e-9 and s['outside_by'] > 2.0
        assert s['head_y'][0] == pytest.approx(COLLECTOR_V1.bracket_top_y)


def test_preview_meshes():
    ms = hardware_meshes(V27, COLLECTOR_V2)
    assert {'rear_panel', 'slot_ledge', 'bracket_A', 'bracket_B', 'screw_heads', 'screw_shanks',
            'window_bezels'} == set(ms)
    assert {'blank_middle', 'slot_covers'} <= set(hardware_meshes(V27, COLLECTOR_V2, BLANK))
    assert set(hardware_meshes(V27, COLLECTOR_V2, CaseParams(covers=(3,)))) & {'blank_middle', 'slot_covers'} == {'slot_covers'}
    for name, m in ms.items():
        assert m.is_watertight and len(m.faces) > 0, name
    assert ms['rear_panel'].bounds[0][2] == pytest.approx(bracket_z(V27))


def test_v1_lands_on_the_slot_ledge(fit1):
    """v1's +y flange band (to y 57) sits on the ledge, tabs and screws: why v2 exists."""
    p = fit1['parts']
    assert p['slot_ledge']['intersection_mm3'] > 300 and p['screw_heads']['intersection_mm3'] > 10
    assert fit1['gasket_path_mm']['ledge'] > 100


def test_v2_clears_the_hardware(fit2):
    assert fit2['total_intersection_mm3'] == 0
    p = fit2['parts']
    assert p['slot_ledge']['min_clearance_mm'] >= .4 and p['screw_heads']['min_clearance_mm'] >= 1.5
    assert p['screw_shanks']['min_clearance_mm'] >= .2      # 6-32 x 1/4" tips, 4.7 mm under the ledge
    for b in ('bracket_A', 'bracket_B', 'blank_middle', 'slot_covers'):
        assert p[b]['min_clearance_mm'] >= .7, b            # the plates sit one panel thickness behind the flange face


def test_v2_leaves_every_slot_screw_reachable(v2):
    for case in (BLANK, CaseParams(screw='thumb', covers=(-3, 0, 3)), CaseParams(ledge_depth=15.0, lip_down=4.0), CaseParams(ledge_bend_radius=.5)):
        r = fit_check(v2, V27, case, density=2.0)
        assert all(s['outside_case'] and s['access_column_blocked_mm3'] == 0 for s in r['screws']), case
        assert r['total_intersection_mm3'] == 0, case


def test_v2_gasket_and_vents(fit2):
    """The gasket runs on steel all round (flush panel, or the plates at the opening tops) and both vent windows open."""
    g = fit2['gasket_path_mm']
    assert g['open'] == 0 and g['ledge'] == 0 and g['off_panel'] == 0 and g['flush'] > 300
    assert all(v['outside_mouth_mm2'] == 0 for v in fit2['vents'])
    assert all(m['open'] == 0 and m['ledge'] == 0 for m in fit2['magnets'])
    assert sum(m['flush'] == 1 for m in fit2['magnets']) == 2   # the lower pair; the rest sit on the side slots' covers


def test_v2_bypass_leaks(v2):
    """Plate-to-panel slits are the only bypass a solid middle blank leaves: < 4 % of the fin flow at a 0.3 mm gap."""
    r = bypass_leaks(v2, V27, BLANK)
    rows = {x['path']: x for x in r['paths']}
    assert rows['plate slits, 0.3 mm gap']['bypass_fraction'] < .04
    assert rows['plate slits, 0.1 mm gap']['bypass_fraction'] < .005
    assert not any(e['edge'] == 'top' for e in r['slit_edges'])     # pressed shut by the gasket band
    assert rows['vented middle blank, if fitted (400 mm2 open)']['bypass_fraction'] > rows['plate slits, 0.3 mm gap']['bypass_fraction']


def test_v2_draws_case_air_through_the_open_slots(v2):
    """The author's case: no covers. v2's single loop encloses the middle slot, so the fan pulls case air through the whole
    13.25 x 100.7 mm opening (a quarter of the flow at the CFD suction); its groove also runs ~1 mm over slots +-3."""
    r = bypass_leaks(v2, V27)
    assert r['open_slots'] == [-3, 0, 3] and r['open_slots_inside_loops'] == [0]
    row = next(x for x in r['paths'] if x['path'].startswith('open slots inside'))
    assert row['area_mm2'] > 700 and row['bypass_fraction'] > .2
    band = fit_check(v2, V27, density=2.0)['gasket_path_mm']['band']
    assert band['open_slots_inside_loops'] == [0] and band['groove_over_open_slots_mm2'] > 100 and band['foam_land_to_open_slots_mm'] < 2.1


def test_v3_seals_per_card(v3, fit3):
    """One gasket loop per card; the groove's straight side bands sit on the 7.07 mm ribs with ~2 mm to each opening,
    nothing of the groove over an open hole, the middle and outer slots outside both loops."""
    loops = gasket_loops(COLLECTOR_V3); hw = build_hardware(V27, COLLECTOR_V3)
    assert len(loops) == 2
    for k in (-3, 0, 3):
        o = hw.openings[k]
        assert not any(p.intersects(box(o[0], o[2], o[1], o[3])) for p in loops), k
    band = fit3['gasket_path_mm']['band']
    assert band['open_slots'] == [-3, 0, 3] and band['open_slots_inside_loops'] == [] and band['groove_over_open_slots_mm2'] == 0
    assert band['foam_land_to_open_slots_mm'] >= 5.0                # the whole 3 mm band on steel, 2 mm short of slots -3 / 0 / +3
    assert band['over_open_mm2'] == 0 and band['side_bands_over_openings_mm2'] == 0
    assert band['side_band_margin_to_openings_mm'] >= 2.0 and band['margin_to_open_mm'] >= 1.0
    g = fit3['gasket_path_mm']
    assert g['open'] == 0 and g['ledge'] == 0 and g['off_panel'] == 0
    assert all(v['outside_mouth_mm2'] == 0 for v in fit3['vents'])
    # With slots +-3 open, four of the six magnets (x +-61.3, y -15 / 25) sit over the open holes: only the lower pair holds
    assert sum(m['open'] == 1 for m in fit3['magnets']) == 4 and sum(m['flush'] == 1 for m in fit3['magnets']) == 2


def test_v3_clears_the_hardware_and_every_screw(v3, fit3):
    assert fit3['total_intersection_mm3'] == 0
    p = fit3['parts']
    assert p['slot_ledge']['min_clearance_mm'] >= .4 and p['screw_heads']['min_clearance_mm'] >= 1.5
    assert p['screw_shanks']['min_clearance_mm'] >= .2      # 6-32 x 1/4" tips: the mouth top 0.25 mm over the vent window, then a 1 mm dip
    for case in (CASE, BLANK, CaseParams(screw='thumb'), CaseParams(ledge_depth=15.0, lip_down=4.0), CaseParams(ledge_bend_radius=.5)):
        r = fit_check(v3, V27, case, density=2.0)
        assert all(s['outside_case'] and s['access_column_blocked_mm3'] == 0 for s in r['screws']), case
        assert r['total_intersection_mm3'] == 0, case


def test_v3_bypass_with_the_middle_slot_open(v3):
    rows = {x['path']: x for x in bypass_leaks(v3, V27)['paths']}
    assert next(x for p, x in rows.items() if p.startswith('open slots inside'))['q_lps'] == 0
    assert rows['vented middle blank, if fitted (400 mm2 open)']['q_lps'] == 0
    assert rows['plate slits, 0.3 mm gap']['bypass_fraction'] < .04


@pytest.mark.parametrize('c', [COLLECTOR_V3, COLLECTOR_V3L], ids=['v3', 'v3l'])
def test_v3_air_volume_contract(c):
    """Same CFD contract as v1/v2: inner from the bracket plane (inlet_z) to the fan face, the two card mouths at the
    bracket plane, the bore about the fan axis at inlet_z + plenum_depth; the fan sits higher than v2's."""
    s = build_collector(c); inner = s.inner
    assert inner.status() == mf.Error.NoError and inner.genus() == 0
    m = section(inner, c.inlet_z+.5)
    assert m.geom_type == 'MultiPolygon' and len(m.geoms) == 2
    for (x0, x1, y0, y1), g in zip(card_mouths(c), sorted(m.geoms, key=lambda p: p.centroid.x)):
        assert g.bounds == pytest.approx((x0, y0, x1, y1), abs=.05)
    from shapely.geometry import LineString
    cut = section(inner, c.inlet_z+10).intersection(LineString([(web_x(c), -300), (web_x(c), 300)]))
    assert cut.length == pytest.approx(2*FIN_END_GAP, abs=.1)     # the splitter fin is in the air volume: only its end gaps are air
    f = section(inner, c.inlet_z+c.plenum_depth-.5)
    assert f.centroid.x == pytest.approx(c.fan_axis[0], abs=.05) and f.centroid.y == pytest.approx(c.fan_axis[1], abs=.05)
    assert f.area == pytest.approx(np.pi*c.fan_radius**2, rel=.01)
    below = lambda c: (c.bracket_top_y-108.21)-(c.fan_axis[1]-c.fan_size/2)   # noqa: E731 frame bottom under the board plane
    assert below(c) < below(COLLECTOR_V2)-8


def test_bare_fan_baseline():
    air, meta = bare_fan_air(COLLECTOR_V3)
    assert air.status() == mf.Error.NoError and air.volume() > 0
    assert meta['fan_axis'][1]+COLLECTOR_V3.fan_size/2 <= 45.5          # the frame top clears the slot-screw tips
    assert air.bounding_box()[2] == pytest.approx(COLLECTOR_V3.inlet_z)


def test_v3_release_matches_build(v3, tmp_path):
    if not (REL3/collector_names('collector-v3')[0]).exists(): pytest.skip('no release yet')
    export_collector(v3, tmp_path, 'collector-v3')
    stl = tmp_path/collector_names('collector-v3')[0]
    r = verify_collector(stl, v3)
    assert r['stl_sha256'] == hashlib.sha256((REL3/collector_names('collector-v3')[0]).read_bytes()).hexdigest()


def test_v2_release_matches_build(v2, tmp_path):
    if not (REL2/collector_names('collector-v2')[0]).exists(): pytest.skip('no release yet')
    export_collector(v2, tmp_path, 'collector-v2')
    stl = tmp_path/collector_names('collector-v2')[0]
    r = verify_collector(stl, v2)
    assert r['stl_sha256'] == hashlib.sha256((REL2/collector_names('collector-v2')[0]).read_bytes()).hexdigest()


# Slot layouts: 5-slot (V*) and 4-slot (A*), from the duct's card pitch

def test_slot_layout_follows_the_card_pitch():
    assert slot_layout(60.96) == dict(cards=((-2, -1), (1, 2)), span=(-2.0, -1.0, 0.0, 1.0, 2.0), slots=(-3, -2, -1, 0, 1, 2, 3))
    assert slot_layout(40.64) == dict(cards=((-1.5, -0.5), (0.5, 1.5)), span=(-1.5, -0.5, 0.5, 1.5), slots=(-2.5, -1.5, -0.5, 0.5, 1.5, 2.5))
    with pytest.raises(AssertionError): slot_layout(50.0)
    assert CASE.slots == (-3, -2, -1, 0, 1, 2, 3) and CASE.open_slots == (-3, 0, 3) and CASE_COVERED.covers == (-3, 0, 3)
    c4 = CASE.for_pitch(40.64)
    assert c4.card_slots == ((-1.5, -0.5), (0.5, 1.5)) and c4.open_slots == (-2.5, 2.5) and c4.covered().covers == (-2.5, 2.5)
    with pytest.raises(AssertionError): CASE_COVERED.for_pitch(40.64)     # covers -3 / 0 / +3 are not slots of the 4-slot layout
    with pytest.raises(AssertionError): CaseParams(covers=(-1,))           # a card slot


def test_collector_for_duct():
    """for_duct: the bracket plane from the duct's chamber length (V28 / V29: 62 + 267), the slot block, openings and vents
    from its card pitch. The presets keep V27's 337 (the released STLs' frame) and their absolute numbers."""
    c = COLLECTOR_V3.for_duct(V29)
    assert c.inlet_z == 62+267 == bracket_z(V29) and c.card_pitch == V29.pitch and c.openings == COLLECTOR_V3.openings
    assert COLLECTOR_V1.slot_positions == (-2.0, -1.0, 0.0, 1.0, 2.0) and COLLECTOR_V1.window_x == (-50.8, 50.8)
    for got, want in zip(COLLECTOR_V2.must_open, [(-42.98, -17.98, -36.65, 44.35), (17.98, 42.98, -36.65, 44.35)]):
        assert got == pytest.approx(want, abs=1e-12)                      # the vent windows, now derived from the card pitch
    assert COLLECTOR_V2.vent_rects == windows(COLLECTOR_V2)               # = the hardware's bracket vent windows
    c4 = COLLECTOR_V3.for_duct(G4)
    assert c4.slot_positions == (-1.5, -0.5, 0.5, 1.5) and c4.window_x == pytest.approx((-40.64, 40.64))
    np.testing.assert_allclose([o[:2] for o in c4.openings], [(-36.385, -23.135), (-16.065, -2.815), (4.255, 17.505), (24.575, 37.825)], atol=1e-9)
    np.testing.assert_allclose([v[:2] for v in c4.must_open], [(-32.82, -23.135), (-16.065, -7.82), (7.82, 17.505), (24.575, 32.82)], atol=1e-9)
    np.testing.assert_allclose([m[:2] for m in card_mouths(c4)], [(-36.885, -2.315), (3.755, 38.325)], atol=1e-9)
    assert web_x(c4) == pytest.approx(.72)


def test_four_slot_hardware():
    """Adjacent cards: four consecutive slots, the neighbours either side open, no slot between the cards. Ribs stay
    7.07 mm; the slot screws move with the brackets; the dual brackets keep their 1.9 mm gap."""
    c = COLLECTOR_V2.for_duct(G4); hw = build_hardware(G4, c)
    assert hw.z_b == 62+267 and hw.case.card_pitch == 40.64 and hw.case.open_slots == (-2.5, 2.5)
    xs = sorted(hw.openings.values())
    np.testing.assert_allclose([o[:2] for o in xs], [(-56.705, -43.455), (-36.385, -23.135), (-16.065, -2.815), (4.255, 17.505),
                                                     (24.575, 37.825), (44.895, 58.145)], atol=1e-9)
    assert all(abs(b[0]-a[1]-7.07) < 1e-9 for a, b in zip(xs, xs[1:]))
    assert [round(s['x'], 2) for s in hw.screws] == [-26.52, -6.2, 14.12, 34.44]
    assert [round(s['x'], 2) for s in build_hardware(G4, c, CASE.for_pitch(40.64).covered()).screws][4:] == [-46.84, 54.76]
    a, b = hw.parts['bracket_A'].bounding_box(), hw.parts['bracket_B'].bounding_box()
    assert b[0]-a[3] == pytest.approx(1.9, abs=.01)
    np.testing.assert_allclose([w[:2] for w in hw.windows], [(-32.82, -7.82), (7.82, 32.82)], atol=1e-9)
    assert not {'blank_middle', 'slot_covers'} & set(hardware_meshes(G4, c))
    # The hardware follows the duct, whatever collector preset is passed: v2 (5-slot) on the 4-slot duct
    assert build_hardware(G4, COLLECTOR_V2).openings == hw.openings


def test_four_slot_seals_and_leaks():
    """With no slot between the cards, nothing open lies inside either the single (v2-type) or the per-card (v3-type)
    loop; the outer open slots +-2.5 sit outside both. (The v1-v3 presets don't build at 2-slot pitch: their 120 mm fan and
    mount pattern overhang the 81 mm window; v4 will be designed for both layouts.)"""
    for c, land in ((COLLECTOR_V2.for_duct(G4), 2.0), (COLLECTOR_V3.for_duct(G4), 5.0)):
        hw = build_hardware(G4, c); band = gasket_band(c, hw)
        assert band['open_slots'] == [-2.5, 2.5] and band['open_slots_inside_loops'] == [] and band['foam_land_to_open_slots_mm'] >= land
        r = bypass_leaks(SimpleNamespace(params=c), G4)      # the leak model reads only the collector's 2-D layout
        rows = {x['path']: x for x in r['paths']}
        assert r['open_slots_inside_loops'] == [] and next(x for p, x in rows.items() if p.startswith('open slots inside'))['q_lps'] == 0
        assert rows['plate slits, 0.3 mm gap']['bypass_fraction'] < .03
    c3 = COLLECTOR_V3.for_duct(G4); band = gasket_band(c3, build_hardware(G4, c3))
    assert band['side_band_margin_to_openings_mm'] == pytest.approx(2.035) and band['over_open_mm2'] == 0


def test_hub_shadow_by_layout():
    """5-slot: the hub sits over the empty middle slot. 4-slot: the openings are even in number, the hub sits on the rib
    between the cards and shadows both cards' inner vents (about 29 % of v3's open strips)."""
    c5, c4 = COLLECTOR_V3.for_duct(V29), COLLECTOR_V3.for_duct(G4)
    h5 = _hub_shadow(c5, c5.openings[2]); h4 = _hub_shadow(c4, None)
    assert h5['hub_covers_middle_opening_width'] and 'middle_opening_x_mm' not in h4
    assert h4['live_vents_under_hub_mm2'] > 2*h5['live_vents_under_hub_mm2'] > 0
