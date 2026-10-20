"""Push-duct aero refinements (docs/push-aero-plan.md): the hub fairing's shell of revolution, the duct with it on (V29 and
A29), its CFD domain, and the approach lip."""
from dataclasses import replace

import numpy as np
import pytest
import shapely
import trimesh
from shapely.geometry import Point

from duct.cad.export import export_duct, stl_name
from duct.cad.geometry import build_duct, cylinder, hub_fairing, shell_of_revolution, splitter_half_width
from duct.cfd import disk, domain
from duct.params import A29, PRESETS, V29
from duct.print import printability as P
from duct.print.verify import polygon_section, verify


def test_presets_leave_it_off():
    assert not any(PRESETS[n].hub_fairing for n in ('v23', 'v24', 'v25', 'v27', 'v28', 'v29', 'a29'))
    assert V29.hub_fairing_d == 50.5 and V29.hub_fairing_angle == 44.0


def test_v30_a30_are_v29_a29_with_the_fairing():
    assert PRESETS['v30'] == replace(V29, hub_fairing=1.0) and PRESETS['a30'] == replace(A29, hub_fairing=1.0)


def _radius(solid, z):
    """Largest radius of the section at z (0 if empty)."""
    pts = [np.asarray(p) for p in solid.slice(float(z)).to_polygons()]
    return max((np.hypot(*p.T).max() for p in pts), default=0.0)


def test_shell_of_revolution():
    s = shell_of_revolution(25.25, 1.2, 44.0, 1.35)
    i = s.info
    assert i['cavity_radius_mm'] == pytest.approx(24.05) and i['tip_z_mm'] == pytest.approx(i['cavity_length_mm']+1.2)
    assert i['steepest_ceiling_deg'] <= 44.0
    # outer: base diameter at the fan face, narrowing all the way up (never an overhang printed base down)
    assert s.outer.bounding_box()[2] == pytest.approx(0, abs=1e-9) and s.outer.bounding_box()[5] == pytest.approx(i['tip_z_mm'], abs=.01)
    zs = np.arange(0.05, i['tip_z_mm'], .1); ro = np.array([_radius(s.outer, z) for z in zs])
    assert ro[0] == pytest.approx(25.25, abs=.01) and np.all(np.diff(ro) <= 1e-6)
    # cavity: open below the base, closing on the axis at <= the angle (a point: its last sections shrink to nothing)
    assert s.cavity.bounding_box()[2] < -1
    rc = np.array([_radius(s.cavity, z) for z in zs])
    inside = zs < i['cavity_length_mm']
    steep = np.degrees(np.arctan(-np.diff(rc[inside])/.1))
    assert steep.max() <= 44.0+.05 and rc[inside][-1] < .2 and not rc[~inside].any()
    # wall: the radial gap is >= wall (the normal offset is the wall; radial >= normal), and = wall at the base
    assert np.all(ro[inside]-rc[inside] >= 1.2-.01) and ro[0]-rc[0] == pytest.approx(1.2, abs=.01)
    # printed base down, the shell alone passes the overhang and solid gates
    spec = P.PartSpec('fairing', wall=1.2, openings=(P.Opening('cavity', (0, 40), region=Point(0, 0).buffer(24.05, quad_segs=64), tol=.1),))
    shell = s.outer-s.cavity
    for gate in (P.unsupported_overhang, P.solid_regions, P.seal):
        assert gate(shell, spec).passed


def test_write_stl_zero_area_facet_has_a_finite_normal(tmp_path):
    """The faired V29 flow surface has zero-area facets; a nan normal makes snappyHexMesh's STL reader fail."""
    m = trimesh.Trimesh([[0, 0, 0], [1, 0, 0], [0, 1, 0], [2, 0, 0]], [[0, 1, 2], [0, 1, 3]], process=False)
    domain.write_stl(m, {"walls": np.arange(2)}, tmp_path/"f.stl")
    text = (tmp_path/"f.stl").read_text()
    assert "nan" not in text and "facet normal 0 0 1" in text and "facet normal 0 0 0" in text


def test_fluid_bridge_is_an_annulus_with_the_fairing():
    g = replace(V29, hub_fairing=1.0)
    f = hub_fairing(g)
    inner = cylinder(g.fan_radius, g.chamber_length, 0)-f.outer
    d = replace(domain.DOMAIN, hub_radius=g.hub_fairing_d/2)
    fluid = domain.fluid_solid(g, inner, d)
    for z in (-.004, 1e-3):
        hub = fluid.slice(z) ^ P._cs(Point(0, 0).buffer(g.hub_fairing_d/2-.05, quad_segs=64))
        assert hub.area() < 1e-3, z
    # off: the bridge is the whole fan disk
    plain = domain.fluid_solid(V29, cylinder(V29.fan_radius, V29.chamber_length, 0))
    assert (plain.slice(0.0) ^ P._cs(Point(0, 0).buffer(20))).area() > 1000


@pytest.mark.parametrize('lip', [0.0, 4.0])
def test_approach_lip(lip):
    d = replace(domain.DOMAIN, approach_lip=lip); r = disk.ROOM
    inner = cylinder(V29.fan_radius, V29.chamber_length, 0)
    mesh = domain.to_metres(domain.fluid_solid(V29, inner, d, (disk.intake_room(d, r),)))
    groups = domain.classify(mesh, V29, d, disk.intake_rules(d))
    area = lambda idx: mesh.area_faces[idx].sum()*1e6  # noqa: E731
    z0 = -d.approach_depth
    # the far field: the room's far face and its side, which the lip shortens by lip
    assert area(groups['inlet']) == pytest.approx(np.pi*r.radius**2+2*np.pi*r.radius*(r.depth-lip), rel=2e-3)
    tri = mesh.triangles[groups['walls']]*1e3
    near = (tri[:, :, 2].min(1) > z0-lip-1e-3) & (tri[:, :, 2].max(1) < z0+.02) & (np.hypot(tri[:, :, 0], tri[:, :, 1]).min(1) > d.approach_radius-1e-3)
    lip_area = mesh.area_faces[groups['walls']][near].sum()*1e6
    flat = np.pi*(r.radius**2-d.approach_radius**2)
    if lip:   # quarter round (area of a torus quarter) plus the moved flat face
        a = d.approach_radius; quarter = np.pi*lip*(np.pi*(a+lip)-2*lip)
        assert lip_area == pytest.approx(quarter+np.pi*(r.radius**2-(a+lip)**2), rel=5e-3)
    else:
        assert lip_area == pytest.approx(flat, rel=1e-3)


@pytest.fixture(scope='module', params=['v29', 'a29'])
def faired(request, tmp_path_factory):
    g = replace(PRESETS[request.param], hub_fairing=1.0)
    s = build_duct(g)
    out = tmp_path_factory.mktemp(f'{request.param}-fairing')
    export_duct(s, out, request.param)
    return g, s, out/stl_name(request.param)


def test_faired_duct(faired):
    g, s, stl = faired
    f = s.hub_fairing; R = g.hub_fairing_d/2
    assert f['steepest_ceiling_deg'] <= g.hub_fairing_angle
    # no air in front of the hub at the fan face; the cavity is open there
    hub = Point(0, 0).buffer(R-.05, quad_segs=64)
    assert polygon_section(s.inner, 1e-3).intersection(hub).area < 1e-3
    solid = P.load_manifold(stl)
    face = polygon_section(solid, 1e-3)
    # the mouth is open; with a parted web (V29) the web's nose crosses it, as it crosses the fan face
    web = shapely.box(-g.nose_tip_half_width-.05, -R, g.nose_tip_half_width+.05, R) if not g.shared_wall else shapely.Polygon()
    assert face.intersection(Point(0, 0).buffer(f['cavity_radius_mm']-.05, quad_segs=64)).difference(web).area < 1e-3
    assert face.intersection(hub.difference(Point(0, 0).buffer(f['cavity_radius_mm']+.05))).area > .9*np.pi*(R**2-(R-1.2)**2)
    # the cavity stays sealed from the passage and the outside up to its apex: a void inside the shell in every section, one
    # cone through the shared wall (A29), a half cone each side of the parted web (V29), whose gap the fairing leaves alone
    probes = [(0, 0)] if g.shared_wall else [(-1, 0), (1, 0)]
    for z in np.arange(1.0, f['cavity_length_mm']-.5, 2.0):
        sec = polygon_section(solid, z); voids = [shapely.Polygon(r) for p in getattr(sec, 'geoms', [sec]) for r in p.interiors]
        for sx, _ in probes:
            x = sx*(splitter_half_width(g, z)+.3) if not g.shared_wall else 0
            if not g.shared_wall and abs(x) > f['cavity_radius_mm']*(1-(z/f['cavity_length_mm'])**g.hub_fairing_power)-.3: continue
            assert any(v.contains(Point(x, 0)) for v in voids), (z, x)
    if not g.shared_wall:   # the gap between the skins stays empty: no fairing tip in it
        for z in np.arange(f['tip_z_mm']-8, f['tip_z_mm']+1, 1.0):
            gap = Point(0, 0).buffer(splitter_half_width(g, z)-g.wall_dilation-.05)
            assert polygon_section(solid, z).intersection(gap).area < 1e-3, z
    r = verify(stl, g, s)
    assert r['fan_face_uncovered_area_mm2'] < .01
    gates = P.run_gates(stl, P.duct_spec(g))
    assert gates['passed'], P.failure_lines(gates)
    assert trimesh.load(stl).is_watertight
