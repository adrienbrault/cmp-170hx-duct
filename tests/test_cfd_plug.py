"""CFD collector kinds 'plug' / 'plug-nohub' / 'plug-slit' / 'plug140' (+ CollectorParams overrides): the plug collector in
CASE_FRACTAL's recessed bay."""
import json

import pytest
import shapely
import shapely.ops

from duct import params as P
from duct.cad import plug
from duct.cad.exhaust import section
from duct.cfd import collector as cc
from duct.cfd.domain import DOMAIN

G = P.V29
Z = G.chamber_length+DOMAIN.card_envelope   # the bracket plane


@pytest.mark.parametrize('kind', list(cc.PLUG_KINDS))
def test_plug_air(kind):
    """Genus 0; given relative to the panel face (CaseOptions adds the panel); placed, the layer starts on the bracket
    plates and the collector's mouths open from its top at the plug face; the bars are not air; the layer ends at the top dam
    (none past it) unless the kind has the slits."""
    air, src, solids, rules, info = cc.plug_air(G, kind=kind)
    c, case = cc.plug_collector(G, hub=cc.PLUG_KINDS[kind]['hub'], base=cc.PLUG_KINDS[kind].get('base', 'COLLECTOR_PLUG_BASE'))
    assert air.genus() == 0 and 'CASE_FRACTAL' in src
    placed = air.translate([0, 0, case.panel]); bb = placed.bounding_box()
    assert bb[2] == pytest.approx(Z, abs=1e-6)
    fz = Z+plug.plug_placement(c, case)
    assert bb[5] == pytest.approx(fz+c.plenum_depth, abs=1e-6)   # the fan face, plenum_depth past the plug face
    layer = section(placed, Z+1.0); crowns = plug.divider_x(c)
    for x in crowns:   # each bar's crown (3 mm proud of the plates) is solid at 1 mm above them
        assert not layer.contains(shapely.geometry.Point(x, 0.0))
    floor = section(placed, Z+case.panel/2)   # within the panel floor: air only in the slot openings (to the bar feet)
    ops = shapely.ops.unary_union([shapely.geometry.box(a, -30, b, 30) for a, b in plug.slot_openings_x(c)])
    assert floor.intersection(shapely.geometry.box(-200, -30, 200, 30)).difference(ops.buffer(.1, join_style="mitre")).area < 1.0
    slit = cc.PLUG_KINDS[kind].get('slit', False)
    d0, d1 = plug.top_dam(c, case)
    assert layer.intersection(shapely.geometry.box(-200, d0+.01, 200, d1)).is_empty != slit   # the dam closes the layer
    if slit:
        assert len(info) == 4 and sum(i['area_mm2'] for i in info) == pytest.approx(cc.PLUG_AIR.slit_mm2) and rules[0][0] == cc.CASE_AIR
        under = section(placed, Z+.5)   # each slit opens wholly into the layer (no lip past its walls)
        for i in info:
            x0, x1, y0, y1 = i['slit_mm']
            assert under.buffer(1e-6).contains(shapely.geometry.box(x0, y0, x1, y1)), i
    else:
        assert not info and not solids and not rules


@pytest.mark.parametrize('kind', ['plug', 'plug-slit'])
def test_plug_case_patches(kind, tmp_path):
    """The built case: slots -3 / 0 / +3 covered (no open-slot case air: 0 is under the plug face, -3 / +3 open outside its
    seal, off the duct's flow path), caseAir only from the slits."""
    import argparse
    from duct.cli import _case_options
    from duct.cfd.case import build
    args = argparse.Namespace(base_cell=None, rpm=2500.0, fans=1, stack_efficiency=1.0, fan_model='boundary', swirl=0.0,
                              grille_open_area=None, bracket=True, panel=True, covered_slots=None, pull_rpm=2500.0,
                              collector=kind, side_port_coupling=1.0)
    build(tmp_path/'case', G, _case_options(args, G))
    m = json.loads((tmp_path/'case'/'case.json').read_text())
    assert m['open_slots']['slots'] == [] and sorted(m['open_slots']['covers']) == [-3, 0, 3]
    assert ('caseAir' in m['patches']) == (kind == 'plug-slit')
    assert {'walls', 'inlet', 'exhaust'} <= set(m['patches'])


def test_plug_overrides():
    """'plug:plenum_depth=55,corner_end=30': the overrides reach the collector (fan face 8 mm further out)."""
    assert cc.split_kind('plug:plenum_depth=55,corner_end=30') == ('plug', {'plenum_depth': 55.0, 'corner_end': 30.0})
    assert cc.is_plug('plug-slit:plenum_depth=63') and not cc.is_plug('v3')
    c0, _ = cc.plug_collector(G); c1, case = cc.plug_collector(G, plenum_depth=c0.plenum_depth+8)
    a0 = cc.plug_air(G, kind='plug')[0].bounding_box(); a1 = cc.plug_air(G, kind=f'plug:plenum_depth={c0.plenum_depth+8:g}')[0].bounding_box()
    assert a1[5]-a0[5] == pytest.approx(8.0, abs=1e-6) and c1.plenum_depth == c0.plenum_depth+8


def test_plug140():
    """'plug140': COLLECTOR_PLUG_140 (named in the source), its 140 mm P14 Pro Reverse on the collector's bore and hub; the
    120 mm kinds keep the P12 Pro (on the domain's annulus: cli._case_options sets no exhaust_fan for them)."""
    from duct.cfd import fan
    src = cc.plug_air(G, kind='plug140')[1]
    assert src.startswith('duct.cad.plug COLLECTOR_PLUG_140 in CASE_FRACTAL')
    pf = cc.plug_fan(G, 'plug140')
    assert pf.name == fan.P14_PRO_REVERSE.name and (pf.tip_radius, pf.hub_radius) == (.068, .028)
    assert cc.plug_fan(G, 'plug') == cc.plug_fan(G, 'plug-slit') == fan.P12_PRO
