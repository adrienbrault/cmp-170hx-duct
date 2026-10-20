"""Exhaust collector: frame, watertightness, walls, fan holes, window coverage, printability (one ~25 s build)."""
import hashlib
from pathlib import Path

import numpy as np
import pytest
import shapely
import trimesh
from shapely.geometry import box

from duct.cad.exhaust import build_collector, section
from duct.cad.export import collector_names, export_collector, to_tri
from duct.cad.geometry import cube, union
from duct.cfd.domain import DOMAIN
from duct.params import COLLECTOR_V1, V24
from duct.print.verify import verify_collector

REL = Path(__file__).resolve().parents[1]/'releases/collector-v1'
C = COLLECTOR_V1


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    s = build_collector(C)
    out = tmp_path_factory.mktemp('collector')
    checks = export_collector(s, out, 'collector-v1')
    stl, gauge = (out/n for n in collector_names('collector-v1'))
    return s, stl, gauge, checks, verify_collector(stl, s)


def test_frame_shared_with_duct_and_cfd():
    """The inlet face sits on the CFD domain's card-exit plane, and the five slots are centred between the cards."""
    assert C.inlet_z == V24.chamber_length+DOMAIN.card_envelope
    assert C.card_pitch == V24.pitch == 3*C.slot_pitch
    assert C.window_x == (-2.5*C.slot_pitch, 2.5*C.slot_pitch) and C.fan_axis[0] == 0


def test_watertight(built):
    s, stl, gauge, checks, r = built
    m = trimesh.load(stl)
    assert m.is_watertight and m.is_winding_consistent and len(m.split()) == 1
    np.testing.assert_allclose(m.bounds[:, 2], [0, C.plenum_depth], atol=1e-6)
    air = to_tri(s.inner)
    assert air.is_watertight and len(air.split()) == 1 and s.inner.genus() == 0
    assert s.inner.num_tri() < 150_000
    g = trimesh.load(gauge)
    assert g.is_watertight and len(g.split()) == 1 and abs(g.bounds[1, 2]-C.gauge_thickness) < 1e-6


def test_released_stl_matches_build(built):
    if not (REL/collector_names()[0]).exists(): pytest.skip('no release yet')
    assert built[4]['stl_sha256'] == hashlib.sha256((REL/collector_names()[0]).read_bytes()).hexdigest()


def test_wall_thickness(built):
    """Normal thickness: outer-skin samples to the air surface. (A horizontal-section proxy reads wall/cos(slope) on the flared walls.)"""
    p0, p5, p50, p95 = built[4]['wall_thickness']['p0_p5_p50_p95_mm']
    assert C.wall-.05 < p5 and abs(p50-C.wall) < .05 and p95 < C.wall+.1


def test_fan_hole_pitch(built):
    h = built[4]['fan_holes_measured']
    assert abs(h['pitch_x_mm']-105) < .02 and abs(h['pitch_y_mm']-105) < .02
    assert built[4]['fan_bore_blocked_mm2'] < .01


def test_window_covers_openings_and_card_ports(built):
    s, *_, r = built
    assert r['openings_blocked_mm2'] < .01 and r['openings_outside_mouth_mm2'] < .01
    mouth = section(s.inner, C.inlet_z+1e-3)
    ports = shapely.unary_union([box(x0, y0, x1, y1) for _, _, (x0, x1, y0, y1) in V24.port_boxes])
    assert ports.difference(mouth).area < 1e-6
    assert built[3]['hub_shadow']['hub_covers_middle_opening_width']


def test_air_joins_cfd_ports():
    """The CFD domain's card port boxes end on the bracket plane; unioned with the collector air they form one body."""
    from duct.cad.exhaust import air_volume
    L = V24.chamber_length
    ports = [cube([x1-x0, y1-y0, DOMAIN.card_envelope+.005], [x0, y0, L-.005]) for _, _, (x0, x1, y0, y1) in V24.port_boxes]
    u = union(*ports, air_volume(C))
    m = to_tri(u)
    assert m.is_watertight and len(m.split()) == 1 and u.genus() == 0


def test_printable(built):
    r = built[4]
    assert r['mesh_quality']['folded_edges_visible_outside_fan_pilots'] == 0, r['mesh_quality']
    assert r['layer_audit']['floating_layers'] == []
    assert r['layer_audit_without_groove_and_pocket_bridges']['maximum_beyond_45deg_area_mm2'] < 1.0


def test_screw_mode_clears_thumb_screws():
    """mount='screws' asserts in build that each thumb-screw head clears body and fillet; the slots go through the flange."""
    from dataclasses import replace
    s = build_collector(replace(C, mount='screws'))
    for x, y in s.features['mount_points']:
        assert section(s.final, C.inlet_z+C.flange_thickness/2).intersection(shapely.geometry.Point(x, y).buffer(C.screw_slot_width/2-.1)).area < 1e-6
