"""Independent checks of a serialized duct STL against the intended CAD (the same checks every release runs)."""
import hashlib
from pathlib import Path

import manifold3d as mf
import numpy as np
import shapely
import trimesh
from shapely.geometry import GeometryCollection, LineString, Point, Polygon
from shapely.ops import unary_union

from ..cad.geometry import DuctSolids, build_duct, splitter_half_width
from ..params import GeometryParams


def polygon_section(solid, z):
    p = GeometryCollection()
    for ring in solid.slice(z).to_polygons():
        p = p.symmetric_difference(Polygon(ring))
    return p


def layer_audit(solid, top, layer=.28) -> dict:
    """Geometric layer-overlap screen: area beyond a 45 degree overhang and floating islands, per layer."""
    prev = None; rows = []
    for z in np.arange(layer/2, top, layer):
        p = GeometryCollection()
        for a in solid.slice(float(z)).to_polygons():
            q = Polygon(a)
            if q.is_valid and q.area > 1e-7: p = p.symmetric_difference(q)
        if prev is not None:
            extra = p.difference(prev.buffer(layer, quad_segs=8))
            parts = list(p.geoms) if p.geom_type == 'MultiPolygon' else [p]
            islands = [c.area for c in parts if c.area > .05 and c.intersection(prev.buffer(.02)).area < .001]
            rows.append(dict(z=float(z), beyond_45deg_area_mm2=extra.area, floating_islands_mm2=islands))
        prev = p
    return dict(layer_height_mm=layer, overhang_horizontal_allowance_mm=layer, maximum_beyond_45deg_area_mm2=max(x['beyond_45deg_area_mm2'] for x in rows),
                layers_beyond_45deg=[x for x in rows if x['beyond_45deg_area_mm2'] > .1], floating_layers=[x for x in rows if x['floating_islands_mm2']],
                note='Geometric layer overlap screen, not a physical print test. Small bridge spans may print without supports; material, cooling and speed matter.')


def normal_audit(m: trimesh.Trimesh, g: GeometryParams) -> list[dict]:
    """Sliver triangles along the pocket wall/floor seams: adjacent-face edges above 35 degrees, by smaller triangle area."""
    a = m.area_faces; c = m.triangles_center
    localx = c[:, 0]-np.where(c[:, 0] < 0, g.card_x[0], g.card_x[1])
    region = (c[:, 2] > 5) & (c[:, 2] < g.chamber_length-5) & (c[:, 1] > 20) & (localx > -23) & (localx < 12)
    adj = m.face_adjacency; angles = np.rad2deg(m.face_adjacency_angles); edge_region = region[adj].any(axis=1)
    rows = []
    for lo, hi in [(0, 1e-4), (1e-4, .001), (.001, .01), (.01, .1), (.1, 1000)]:
        chosen = edge_region & (np.min(a[adj], axis=1) >= lo) & (np.min(a[adj], axis=1) < hi)
        rows.append(dict(min_triangle_area_mm2=[lo, hi], adjacent_edges=int(chosen.sum()), edges_above_35deg=int((chosen & (angles > 35)).sum())))
    return rows


def mesh_quality(m: trimesh.Trimesh) -> dict:
    """Folded edge pairs (dihedral above 120 degrees; they render as flecks) and needle faces."""
    a = np.degrees(m.face_adjacency_angles); small = m.area_faces[m.face_adjacency].min(axis=1)
    longest = np.max(np.linalg.norm(np.diff(m.triangles[:, [0, 1, 2, 0]], axis=1), axis=2), axis=1)
    return dict(folded_edges_above_120deg=int((a > 120).sum()), folded_edges_visible=int(((a > 120) & (small > .05)).sum()),
                folded_edges_above_160deg=int((a > 160).sum()), needle_faces=int((2*m.area_faces/np.maximum(longest, 1e-12) < 1e-3).sum()))


def verify(stl_path, params: GeometryParams, solids: DuctSolids | None = None) -> dict:
    """Raise AssertionError on any failed check; otherwise return the measurements."""
    g = params; L = g.chamber_length; stl_path = Path(stl_path)
    s = solids or build_duct(g)
    inner = s.inner
    m = trimesh.load(stl_path)
    assert m.is_watertight and m.is_winding_consistent and len(m.split()) == 1
    solid = mf.Manifold(mf.Mesh(m.vertices.astype(np.float32), m.faces.astype(np.uint32)))
    assert solid.status() == mf.Error.NoError

    # A material mesh being watertight is not enough: the fan aperture must be covered by material or intended fluid
    # (the hub fairing's cavity, open toward the fan's hub, is intended: dead air behind the hub).
    eps = 1e-4
    fan_aperture = Point(0, 0).buffer(g.fan_radius, quad_segs=32)
    if s.hub_fairing_cavity is not None: fan_aperture = fan_aperture.difference(polygon_section(s.hub_fairing_cavity, eps))
    uncovered = fan_aperture.difference(polygon_section(solid, eps).union(polygon_section(inner, eps))).area
    assert uncovered < .01, uncovered

    # Both flow-facing splitter surfaces, measured from the serialized mesh: on y = 0, or beside the hub fairing (the web
    # is unchanged there; on the axis it is the fairing's cavity) up to its tip, on the -y side (card B's bay is at +y).
    rows = []
    for z in [eps, .14, .28, .5, 1., 1.5, 2., 5., 10., 20., 30., 40., 50., 54.99, 60., L-.01]:
        h = splitter_half_width(g, z)
        y = -g.hub_fairing_d/2-2 if s.hub_fairing and z < s.hub_fairing['tip_z_mm']+1 else 0
        cut = polygon_section(solid, z).intersection(LineString([[-h-.3, y], [h+.3, y]]))
        assert not cut.is_empty
        measured = [float(cut.bounds[0]), float(cut.bounds[2])]
        error = max(abs(measured[0]+h), abs(measured[1]-h))
        assert error < .025, (z, h, measured, error)
        rows.append(dict(z_mm=z, expected_half_width_mm=h, measured_x_bounds_mm=measured, error_mm=error, **({'y_mm': y} if y else {})))

    # Collar section of the serialized STL (mid-collar) against the in-memory CAD solid.
    zc = L+g.collar_length/2
    section = lambda mesh: unary_union([LineString(x[:, :2]) for x in mesh.section(plane_origin=[0, 0, zc], plane_normal=[0, 0, 1]).discrete])  # noqa: E731
    ref = s.final.to_mesh64()
    cad = trimesh.Trimesh(np.asarray(ref.vert_properties)[:, :3], np.asarray(ref.tri_verts), process=False)
    collar_error = section(cad).hausdorff_distance(section(m))
    assert collar_error < .01, collar_error

    # The three measured/estimated card flow-port rectangles must stay open at the seat face.
    flow_end = polygon_section(inner, L-eps)
    ports = unary_union([shapely.geometry.box(x0, y0, x1, y1) for _, _, (x0, x1, y0, y1) in g.port_boxes])
    port_obstruction = ports.difference(flow_end).area

    # The serialized STL must contain the intended rounded air boundary, not only the source radius labels.
    z_end = L-g.pocket_transition
    retained = [x for x in s.passage_fillet_profile if x['z_mm'] >= z_end]
    min_radius = min(x['radius_mm'] for x in retained)
    assert min_radius > g.passage_radius-g.passage_radius_drop-.1
    rounding = []
    for z in [z_end, z_end+6, z_end+16, L-.01]:
        actual = polygon_section(solid, z).boundary
        intended = polygon_section(inner, z)
        for side, cx in enumerate(g.card_x):
            corner = next(x for x in s.passage_fillet_profile if x['side'] == side and abs(x['z_mm']-z) < .4)
            R, x, y = corner['radius_mm'], corner['corner_x_mm'], corner['corner_y_mm']
            curve = intended.boundary.intersection(shapely.geometry.box(x-.15, y-R-.5, x+R+.5, y+.15))
            error = max(curve.interpolate(t, normalized=True).distance(actual) for t in np.linspace(0, 1, 81))
            assert error < .025, (z, cx, error)
            rounding.append(dict(z_mm=z, side=side, actual_STL_curve_error_mm=error))

    assert max(map(abs, s.plug_latch_collisions_mm3)) < 1e-4 and max(map(abs, s.bay_collisions_mm3)) < 1e-4
    return dict(serialized_fillet_checks=rounding, watertight=True, consistent_winding=True, connected_solids=1, fan_face_uncovered_area_mm2=uncovered,
                splitter_profile_measurements=rows, collar_section_difference_from_cad_mm=collar_error, stl_sha256=hashlib.sha256(stl_path.read_bytes()).hexdigest(),
                total_estimated_port_obstruction_mm2=port_obstruction, passage_fillet_min_radius_service_region_mm=min_radius,
                layer_audit=layer_audit(solid, float(m.bounds[1, 2])))


def verify_collector(stl_path, s) -> dict:
    """Independent checks of a serialized exhaust-collector STL (print frame) against its CAD (duct.cad.exhaust.CollectorSolids).

    Raise AssertionError on a failed check; otherwise return the measurements.
    """
    from scipy.spatial import cKDTree

    from ..cad import exhaust as ex
    c = s.params; z0 = c.inlet_z; D = c.plenum_depth; ax = np.asarray(c.fan_axis)
    stl_path = Path(stl_path); m = trimesh.load(stl_path)
    assert m.is_watertight and m.is_winding_consistent and len(m.split()) == 1
    solid = mf.Manifold(mf.Mesh(m.vertices.astype(np.float32), m.faces.astype(np.uint32)))
    assert solid.status() == mf.Error.NoError
    inner = s.inner.translate([0, 0, -z0])
    assert inner.genus() == 0 and len(trimesh.Trimesh(*_mesh(inner)).split()) == 1

    # The case face: material must leave every derived chassis opening (and V24's card ports) open
    face = polygon_section(solid, 1e-3)
    openings = unary_union([shapely.geometry.box(x0, y0, x1, y1) for x0, x1, y0, y1 in c.must_open])   # bracket vents (v2) or chassis openings
    if c.mount == 'snap': openings = openings.difference(unary_union(ex.snap_arm_footprints(c)))   # the clips' arms, by design
    mouth = polygon_section(inner, 1e-3)
    openings_blocked = openings.intersection(face).area; openings_outside_mouth = openings.difference(mouth).area
    assert openings_blocked < .01 and openings_outside_mouth < .01, (openings_blocked, openings_outside_mouth)
    # The fan face: the bore is open air
    top = float(m.bounds[1, 2]); assert abs(top-D) < 1e-3
    bore = Point(*ax).buffer(c.fan_radius-.05, quad_segs=64)
    bore_blocked = bore.intersection(polygon_section(solid, D-1e-3)).area
    assert bore_blocked < .01, bore_blocked

    # Fan holes from the mesh: interiors of the plate section that are small circles
    plate = polygon_section(solid, D-c.fan_plate_thickness/2)
    holes = [Polygon(r) for p in getattr(plate, 'geoms', [plate]) for r in p.interiors if Polygon(r).area < 50]
    centres = np.array([[h.centroid.x, h.centroid.y] for h in holes])
    assert len(centres) == 4, len(centres)
    pitch_x = float(np.ptp(centres[:, 0])); pitch_y = float(np.ptp(centres[:, 1]))
    diameter = float(2*np.sqrt(np.mean([h.area for h in holes])/np.pi))
    assert abs(pitch_x-2*c.fan_hole_offset) < .02 and abs(pitch_y-2*c.fan_hole_offset) < .02 and np.allclose(centres.mean(0), ax, atol=.02)

    # Wall thickness of the plenum skin: distance from outer-skin samples to the air surface (normal thickness)
    air = trimesh.Trimesh(*_mesh(inner)); side = np.abs(air.face_normals[:, 2]) < .999
    P, _ = trimesh.sample.sample_surface(air.submesh([np.flatnonzero(side)], append=True), 400000, seed=1)
    Q, _ = trimesh.sample.sample_surface(m, 200000, seed=2)
    d, _ = cKDTree(P).query(Q)
    ang = np.degrees(np.arctan2(Q[:, 1]-ax[1], Q[:, 0]-ax[0])) % 90
    skin = (d > .5) & (Q[:, 2] > c.flange_thickness+c.flange_fillet+.5) & (Q[:, 2] < D-c.fan_plate_thickness-.5) & (np.hypot(*(Q[:, :2]-ax).T) < c.fan_size/2+2)
    if c.split and c.vane_style == 'v4':   # not the vanes (inside the plenum): their x span below their top
        for _, _, v in ex.vanes(c):
            xs = [q for _, l, r in v['profile'] for q in (l, r)]
            skin &= ~((Q[:, 0] > min(xs)-.05) & (Q[:, 0] < max(xs)+.05) & (Q[:, 2] < v['top_s']+.1))
        if c.hub_fairing:   # nor the hub fairing (inside the plenum)
            skin &= ~((np.hypot(*(Q[:, :2]-ax).T) < c.hub_fairing_d/2+.1) & (Q[:, 2] < D-c.fan_plate_thickness+.1))
    elif c.split: skin &= np.abs(Q[:, 0]-ex.web_x(c)) > c.fin_thickness/2+.05   # not the splitter fin (inside the plenum)
    plain = skin & ((ang < 10) | (ang > 80))     # away from the fan-plate ear chamfers
    wall = dict(samples=int(plain.sum()), p0_p5_p50_p95_mm=np.percentile(d[plain], [0, 5, 50, 95]).round(3).tolist(),
                all_skin_p50_p95_p99_mm=np.percentile(d[skin], [50, 95, 99]).round(3).tolist(),
                note='plain skin: polar angle within 10 deg of x/y; the rest includes the 45 deg chamfers under the fan-plate corner ears')
    assert abs(np.median(d[plain])-c.wall) < .05 and np.percentile(d[plain], 1) > c.wall-.05, wall

    # Folded edges away from the fan-screw pilots (where a vertical pilot leaves the 45 deg ear chamfer by design)
    q = mesh_quality(m); a = np.degrees(m.face_adjacency_angles); small = m.area_faces[m.face_adjacency].min(axis=1)
    centre = m.triangles_center[m.face_adjacency[:, 0]][:, :2]
    pilot = np.min([np.hypot(*(centre-np.asarray(h)).T) for h in ex.fan_holes(c)], axis=0) < c.fan_hole_radius+2
    q['folded_edges_visible_outside_fan_pilots'] = int(((a > 120) & (small > .05) & ~pilot).sum())

    # Layer screen; and again with the gasket groove and magnet pockets filled, i.e. without their deliberate short bridges
    filled = solid+ex._extrude(ex.gasket_ring(c), -.1, c.gasket_depth+.1)
    if c.mount == 'magnets':
        for p in s.features['mount_points']: filled += ex._extrude(ex.magnet_pocket(c, p), -.1, c.magnet_thickness+.3)
    layers = layer_audit(solid, top); bridges_filled = layer_audit(filled, top)
    return dict(stl_sha256=hashlib.sha256(stl_path.read_bytes()).hexdigest(), watertight=True, consistent_winding=True, connected_solids=1,
                inner_air=dict(watertight=True, bodies=1, genus=0, volume_mm3=float(inner.volume()), triangles=int(inner.num_tri())),
                openings_blocked_mm2=openings_blocked, openings_outside_mouth_mm2=openings_outside_mouth, fan_bore_blocked_mm2=bore_blocked,
                fan_holes_measured=dict(pitch_x_mm=pitch_x, pitch_y_mm=pitch_y, diameter_mm=diameter, centres_mm=centres.round(3).tolist()),
                wall_thickness=wall, mesh_quality=q, layer_audit=layers,
                layer_audit_without_groove_and_pocket_bridges=dict(maximum_beyond_45deg_area_mm2=bridges_filled['maximum_beyond_45deg_area_mm2'],
                                                                     layers_beyond_45deg=bridges_filled['layers_beyond_45deg'], floating_layers=bridges_filled['floating_layers']))


def _mesh(s):
    raw = s.to_mesh64()
    return np.asarray(raw.vert_properties)[:, :3], np.asarray(raw.tri_verts)
