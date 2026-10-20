"""Continuous twin-passage dual-170HX duct (V23 algorithm). Pure: no file I/O.

Experimental: physical fit and cooling performance are unvalidated.
"""
import hashlib
from dataclasses import dataclass

import manifold3d as mf
import numpy as np
import shapely
from scipy.ndimage import gaussian_filter1d, minimum_filter1d
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from ..params import GeometryParams


@dataclass(frozen=True)
class DuctSolids:
    params: GeometryParams
    inner: mf.Manifold                  # internal air manifold: both sealed branches, fan face to seat face
    final: mf.Manifold                  # printable solid, before the export round trip and simplification
    upper_fillet_profile: list[dict]
    passage_fillet_profile: list[dict]
    section_areas: list[dict]
    splitter_profile: list[dict]
    plug_latch_collisions_mm3: list[float]
    bay_collisions_mm3: list[float]
    hub_fairing: dict | None = None     # shell_of_revolution info of the hub fairing (GeometryParams.hub_fairing), else None
    hub_fairing_cavity: mf.Manifold | None = None


def cube(size, origin): return mf.Manifold.cube(size).translate(origin)
def cylinder(radius, depth, z): return mf.Manifold.cylinder(depth, radius, circular_segments=128).translate([0, 0, z])
def union(*solids): return mf.Manifold.batch_boolean(solids, mf.OpType.Add)


_DILATIONS: dict[str, mf.Manifold] = {}   # dilate()'s results in this process, by the exact meshes of its inputs


def _mesh_digest(h, m: mf.Manifold):
    """Feed everything of m's mesh into h: vertices, triangles, tolerance and its relation to the originals, with the
    original ids (process-wide counters) replaced by their rank."""
    r = m.to_mesh64()
    ids = np.asarray(r.run_original_id)
    arrays = [r.vert_properties, r.tri_verts, r.merge_from_vert, r.merge_to_vert, r.run_index, np.unique(ids, return_inverse=True)[1],
              r.run_transform, r.face_id, r.halfedge_tangent]
    for a in arrays:
        a = np.ascontiguousarray(np.asarray(a)); h.update(f'{a.dtype}{a.shape}'.encode()); h.update(a.tobytes())
    h.update(repr(m.get_tolerance()).encode())


def dilate(tool: mf.Manifold, kernel: mf.Manifold) -> mf.Manifold:
    """tool.minkowski_sum(kernel), once per process for the same meshes: the shell dilation is most of a V24+ build, and
    presets that differ only downstream of it (V29 and V30: the hub fairing) share it."""
    h = hashlib.sha256(); _mesh_digest(h, tool); _mesh_digest(h, kernel); k = h.hexdigest()
    if k not in _DILATIONS: _DILATIONS[k] = tool.minkowski_sum(kernel)
    return _DILATIONS[k]


def rr(w, h, r, n=24):
    p = []
    for cx, cy, start in [(w/2-r, h/2-r, 0), (-w/2+r, h/2-r, 90), (-w/2+r, -h/2+r, 180), (w/2-r, -h/2+r, 270)]:
        for theta in np.linspace(start, start+90, n+1):
            t = np.radians(theta); p.append([cx+r*np.cos(t), cy+r*np.sin(t)])
    return np.array(p)


def plate(w, h, r, z, depth):
    return mf.Manifold.extrude(mf.CrossSection([rr(w, h, r)]), depth).translate([0, 0, z])


def solid_rings(rings, axis=None):
    """Loft equal-length 3-D rings vertex to vertex; the end caps fan from the ring mean or from `axis` (x, y)."""
    N = len(rings[0]); v = np.vstack(rings).tolist(); f = []
    for k in range(len(rings)-1):
        for i in range(N):
            j = (i+1) % N; a = k*N+i; b = k*N+j; c = (k+1)*N+j; d = (k+1)*N+i; f.extend([[a, b, c], [a, c, d]])
    for k, inverse in [(0, True), (len(rings)-1, False)]:
        center = np.array(rings[k]).mean(0) if axis is None else np.array([*axis, rings[k][0][2]]); idx = len(v); v.append(center.tolist())
        for i in range(N):
            j = (i+1) % N; f.append([idx, k*N+j, k*N+i] if inverse else [idx, k*N+i, k*N+j])
    s = mf.Manifold(mf.Mesh(np.array(v, dtype=np.float32), np.array(f, dtype=np.uint32)))
    assert s.status() == mf.Error.NoError, s.status()
    return s


def area_inside(cs: mf.CrossSection, region) -> float:
    """Area of a cross-section inside a shapely polygon."""
    return float((cs ^ mf.CrossSection([np.asarray(region.exterior.coords)[:-1]])).area())


def smooth01(t):
    t = np.clip(t, 0, 1)
    return t*t*t*(10+t*(-15+6*t))


def ramp(t, e=.08):
    # Integrated trapezoidal velocity: bounded slope, rounded end transitions.
    t = np.clip(t, 0, 1)
    if t < e: return (t*t/(2*e))/(1-e)
    if t > 1-e: return 1-((1-t)**2/(2*e))/(1-e)
    return (t-e/2)/(1-e)


def polygon_radii(poly, origin, angles):
    result = []
    for t in angles:
        hit = poly.intersection(LineString([origin, np.asarray(origin)+300*np.array([np.cos(t), np.sin(t)])]))
        assert hit.geom_type == 'LineString', (hit.geom_type, origin)
        result.append(np.linalg.norm(np.asarray(hit.coords)[-1]-origin))
    return np.array(result)


def even_loft(rings, origin, n=1536):
    """Loft star-shaped sections resampled to n points at equal arc length from a common seam (polar angle 0).

    Every ring then has the same vertex count and parametrisation, so the loft is regular quads without the
    fan and sliver triangles of zip_loft, which the shell dilation would turn into visible wrinkles.
    """
    out = []
    for poly, z in rings:
        ring = orient(poly, 1).exterior
        s0 = ring.project(Point(origin+[polygon_radii(poly, origin, [0])[0], 0]))
        pts = np.asarray(shapely.get_coordinates(shapely.line_interpolate_point(ring, (s0+np.arange(n)*ring.length/n) % ring.length)))
        out.append(np.c_[pts, np.full(n, z)])
    return solid_rings(out, origin)


def zip_loft(rings, origin):
    """Loft polygon sections with angular zipper triangulation, keeping every real section corner."""
    verts = []; polars = []; offsets = []
    for pts, z in rings:
        # Insert a common seam at angle zero, then retain all real polygon vertices.
        p = Polygon(pts); rad = polygon_radii(p, origin, [0])[0]
        pts = np.vstack([pts, origin+[rad, 0]])
        ang = np.arctan2(pts[:, 1]-origin[1], pts[:, 0]-origin[0]) % (2*np.pi)
        order = np.argsort(ang); pts = pts[order]; ang = ang[order]
        keep = np.r_[True, np.diff(ang) > 1e-9]; pts = pts[keep]; ang = ang[keep]
        offsets.append(len(verts)); polars.append(ang)
        verts.extend(np.c_[pts, np.full(len(pts), z)].tolist())
    faces = []
    for k in range(len(rings)-1):
        a = polars[k]; b = polars[k+1]; na = len(a); nb = len(b); i = j = 0
        while i < na or j < nb:
            aa = a[i+1] if i+1 < na else 2*np.pi
            bb = b[j+1] if j+1 < nb else 2*np.pi
            va = offsets[k]+i % na; vb = offsets[k+1]+j % nb
            if abs(aa-bb) < 1e-10:
                an = offsets[k]+(i+1) % na; bn = offsets[k+1]+(j+1) % nb
                faces.extend([[va, an, bn], [va, bn, vb]]); i += 1; j += 1
            elif aa < bb:
                faces.append([va, offsets[k]+(i+1) % na, vb]); i += 1
            else:
                faces.append([va, offsets[k+1]+(j+1) % nb, vb]); j += 1
    for k, reverse in [(0, True), (len(rings)-1, False)]:
        c = len(verts); verts.append([*origin, rings[k][1]])
        for i in range(len(polars[k])):
            a = offsets[k]+i; b = offsets[k]+(i+1) % len(polars[k])
            faces.append([c, b, a] if reverse else [c, a, b])
    mesh = mf.Mesh(np.array(verts, dtype=np.float32), np.array(faces, dtype=np.uint32))
    result = mf.Manifold(mesh); assert result.status() == mf.Error.NoError, result.status()
    return result


@dataclass(frozen=True)
class Shell:
    outer: mf.Manifold                  # the solid of revolution: the cavity dilated by the wall, z >= 0
    cavity: mf.Manifold                 # the void inside it, open at z = 0 (extended below it so a subtraction leaves the mouth open)
    info: dict


def shell_of_revolution(radius: float, wall: float, angle: float, power: float, mouth: float = 2.0, n: int = 241,
                        segments: int = 128) -> Shell:
    """A wall-thick shell of revolution on the z axis, standing on z = 0 with base outer radius `radius`, open toward -z.

    The cavity is specified and the outer derived from it, so it prints base-down without support: its meridian is
    r = Rc (1 - t^p), Rc = radius - wall, t = z / Lc, with Lc = p Rc / tan(angle), so its ceiling steepens from vertical at
    the base to exactly `angle` from vertical where it closes on the axis (a cone point, never a flat ceiling). It is
    extended down to z = -mouth as a cylinder. The outer is the meridian's 2-D round offset by `wall`, i.e. the exact
    normal offset of the surface of revolution: a uniform wall, the tip rounded by it, and only narrowing going up.
    """
    Rc = radius-wall; k = np.tan(np.radians(angle)); Lc = power*Rc/k
    t = np.linspace(0, 1, n)**2                          # dense near the base, where the curvature of t^p (p < 2) is largest,
    t = t[(t == 0) | (t*Lc >= .1)]                       # but no ring within 0.1 mm of the base (r is within 0.01 mm of Rc there):
    r = Rc*(1-t**power); z = t*Lc                        # export simplification would fold such near-coplanar rings
    half = [(Rc, -mouth), *zip(r, z)]                    # base corner down the cylinder, then up the ogive to the apex (0, Lc)
    meridian = Polygon(half+[(-x, y) for x, y in half[::-1][1:-1]]+[(-Rc, -mouth)])
    assert meridian.is_valid, 'invalid cavity meridian'
    right = box(0, -mouth-wall-1, radius+1, Lc+wall+1)
    def revolve(poly):
        ring = np.asarray(orient(poly.intersection(right), 1).exterior.coords)[:-1]
        return mf.Manifold.revolve(mf.CrossSection([np.maximum(ring, [0, -np.inf])]), segments)
    cavity = revolve(meridian)
    outer = revolve(meridian.buffer(wall, quad_segs=32)).trim_by_plane([0, 0, 1], 0.0)
    slope = np.degrees(np.arctan(np.abs(np.diff(r)/np.diff(z))))
    return Shell(outer, cavity, dict(base_outer_diameter_mm=2*radius, cavity_radius_mm=Rc, cavity_length_mm=float(Lc),
                                     tip_z_mm=float(Lc+wall), wall_mm=wall, power=power, design_angle_deg=angle,
                                     steepest_ceiling_deg=float(slope.max()), segments=segments,
                                     outer_volume_mm3=float(outer.volume()), cavity_volume_mm3=float(cavity.trim_by_plane([0, 0, 1], 0.0).volume())))


def hub_fairing(g: GeometryParams) -> Shell:
    """The hub fairing behind the push fan (GeometryParams.hub_fairing): its base on the fan face, open toward the fan."""
    return shell_of_revolution(g.hub_fairing_d/2, g.wall_dilation, g.hub_fairing_angle, g.hub_fairing_power)


def bay_wall_x(g: GeometryParams, z):
    """Service-bay side wall x from the card centre: narrows smoothly before the GPU seating face."""
    t = np.clip((z-(g.chamber_length-g.bay_narrow_start))/g.bay_narrow_length, 0, 1)
    return g.bay_wall_x-g.bay_wall_narrowing*(t*t*(3-2*t))


def nose_shoulder_z(g: GeometryParams):
    return g.nose_radius_z*np.sqrt(1-(g.nose_tip_half_width/g.nose_radius_x)**2)


def splitter_half_width(g: GeometryParams, z):
    """Elliptical nose cap, then symmetric cubic widening (zero end slopes) to the outlet splitter."""
    L = g.chamber_length; zs = nose_shoulder_z(g); outlet = (g.pitch-g.bore[0])/2
    t = float(np.clip(z/L, 0, 1))
    widening = t*t*(3-2*t)
    if z < zs:
        cap = g.nose_radius_x*np.sqrt(max(0, 1-((z-zs)/g.nose_radius_z)**2))
    else: cap = g.nose_radius_x
    return cap+(outlet-g.nose_radius_x)*widening


def _fan_half(g: GeometryParams, side):
    """Fan aperture half feeding one branch, split at the splitter nose tip."""
    half = box(-100, -100, -g.nose_tip_half_width, 100) if side == 0 else box(g.nose_tip_half_width, -100, 100, 100)
    return Point(0, 0).buffer(g.fan_radius, quad_segs=128).intersection(half)


def _passages(g: GeometryParams):
    """Loft each branch from its fan half to its GPU bore. Returns air lofts, outer-shell lofts and section data."""
    L = g.chamber_length; R = g.fan_radius; bw, bh = g.bore; hw, hh = bw/2, bh/2
    tip = g.nose_tip_half_width; zs = nose_shoulder_z(g); outlet = (g.pitch-bw)/2
    pocket_transition_end = L-g.pocket_transition
    # The web between the branches becomes a double skin at z_sep; at the 2-slot pitch it never does (one shared wall)
    zz = np.linspace(0, L, 701); parted = np.array([splitter_half_width(g, z) >= g.wall_dilation for z in zz])
    z_sep = zz[np.argmax(parted)] if parted.any() else np.inf
    inners = []; outer_tools = []; section_data = []; passage_fillet_data = []; upper_fillet_data = []
    for i, cx in enumerate(g.card_x):
        origin = np.array([cx+g.loft_origin_dx, 0.])
        start = _fan_half(g, i)
        end = box(cx-hw, -hh, cx+hw, hh)
        angles = list(np.linspace(0, 2*np.pi, 384, endpoint=False))
        angles.extend(np.arctan2(*(np.array(p)-origin)[::-1]) % (2*np.pi) for p in np.array(end.exterior.coords)[:-1])
        inner_x = cx+(hw if i == 0 else -hw)
        ek = []; sk = []
        for y in [hh, -hh]:
            ep = np.array([inner_x, y])-origin
            sp = np.array([-tip if i == 0 else tip, np.sign(y)*np.sqrt(R**2-tip**2)])-origin
            ek.append(np.arctan2(ep[1], ep[0]) % (2*np.pi)); sk.append(np.arctan2(sp[1], sp[0]) % (2*np.pi))
        angles.extend(ek); angles = np.unique(np.round(angles, 12))
        start_angles = np.interp(angles, [0, ek[0], np.pi, ek[1], 2*np.pi], [0, sk[0], np.pi, sk[1], 2*np.pi])
        start_pts = origin+polygon_radii(start, origin, start_angles)[:, None]*np.c_[np.cos(start_angles), np.sin(start_angles)]
        end_pts = origin+polygon_radii(end, origin, angles)[:, None]*np.c_[np.cos(angles), np.sin(angles)]
        rings = []; outer_rings = []
        narrow0 = L-g.bay_narrow_start
        extra = np.linspace(0, 12, 61) if g.shell_from_air else []   # the bay and splitter corners change quickly near the fan
        secs = []
        for z in np.unique(np.r_[np.linspace(0, L, 111), np.linspace(0, zs, 33), pocket_transition_end, narrow0, narrow0+g.bay_narrow_length, extra]):
            b = ramp(z/L)
            pts = start_pts*(1-b)+end_pts*b
            # Only reshape the central-wall neighborhood; preserve the outer contraction
            # and the independently constrained connector recess. This smooth x mapping
            # is identical on both sides, without a lateral bias to either GPU.
            sign = -1 if i == 0 else 1
            old_half = tip+(outlet-tip)*b
            distance = sign*pts[:, 0]-old_half
            weight = smooth01(1-np.clip(distance/g.splitter_blend_width, 0, 1))
            pts[:, 0] += sign*(splitter_half_width(g, z)-old_half)*weight
            contour = start if z == 0 else Polygon(pts)
            assert contour.is_valid, 'Invalid splitter section'

            bay_y = R-(R-g.bay_floor_y)*ramp(z/pocket_transition_end, e=g.bay_ramp_ease)
            bay_x = cx+bay_wall_x(g, z)+g.skin_wall
            radius = (g.shoulder_radius-g.shoulder_radius_drop*smooth01((z-g.shoulder_taper_start)/(pocket_transition_end-g.shoulder_taper_start)))*smooth01(z/g.shoulder_ease)
            if radius > 1e-6:
                centre = np.array([bay_x-radius, bay_y+radius])
                arc = [centre+radius*np.array([np.cos(t), np.sin(t)]) for t in np.linspace(0, -np.pi/2, 25)]
                bay = Polygon([[cx-100, 100], [bay_x, 100], *arc, [cx-100, bay_y]])
            else: bay = box(cx-100, bay_y, bay_x, 100)
            base = contour.difference(bay).simplify(.002, preserve_topology=True)
            assert base.geom_type == 'Polygon' and base.is_valid
            line = contour.intersection(LineString([[-100, bay_y], [100, bay_y]]))
            xmin = float(line.bounds[0]) if not line.is_empty else 0.
            floor_length = max(0., bay_x-radius-xmin) if not line.is_empty else 0.
            target_radius = (g.passage_radius-g.passage_radius_drop*smooth01((z-(L-g.passage_taper))/g.passage_taper))*smooth01(z/g.passage_ease)
            passage_radius = min(target_radius, floor_length/g.passage_floor_ratio)
            if floor_length < .01 or base.distance(Point(xmin, bay_y)) > .01: passage_radius = 0.
            # Round the upper shoulder: the corner where the vertical connector-pocket
            # side meets the upper inlet/branch contour (separate from the lower passage-floor corner).
            upper_line = contour.intersection(LineString([[bay_x, -100], [bay_x, 100]]))
            top_y = float(upper_line.bounds[3]) if not upper_line.is_empty else bay_y
            available = max(0., top_y-bay_y-radius)
            outlet_taper = smooth01((z-(L-g.upper_outlet_taper))/g.upper_outlet_taper)
            requested_upper = g.upper_radius*smooth01(z/g.upper_ease)*(1-outlet_taper)+min(g.upper_outlet_radius, g.upper_radius)*outlet_taper
            upper_radius = min(requested_upper, available/g.upper_room_ratio)
            secs.append(dict(z=z, contour=contour, base=base, bay_x=bay_x, bay_y=bay_y, xmin=xmin, top_y=top_y, requested_upper=requested_upper, passage_radius=passage_radius, upper_radius=upper_radius))
        if g.fillet_smoothing:
            # The space limits make the raw fillet radii kink and step along z; the shell follows the fillets,
            # so smooth them: a moving minimum (never larger than the room allows) then a Gaussian.
            for key in ['passage_radius', 'upper_radius']:
                for sec, r in zip(secs, _smooth_profile([x['z'] for x in secs], [x[key] for x in secs], g.fillet_smoothing)): sec[key] = r
        for sec in secs:
            z, contour, base, bay_x, bay_y, xmin, top_y, requested_upper, passage_radius, upper_radius = sec.values()
            fillets = lambda scale: _round_upper(_round_corner(base, passage_radius*scale, 16, Point(xmin, bay_y)), upper_radius*scale, Point(bay_x, top_y))  # noqa: E731
            p = fillets(1)
            assert p.geom_type == 'Polygon' and p.is_valid, (i, z, upper_radius, p.geom_type)
            upper_fillet_data.append(dict(side=i, z_mm=float(z), requested_radius_mm=float(requested_upper), actual_radius_mm=float(upper_radius), corner_x_mm=float(bay_x), corner_y_mm=top_y, remaining_air_area_mm2=p.area))
            skin = base   # V23: the outer shell follows the unfilleted section; only the inside corners are rounded
            if g.shell_from_air:
                # Every convex corner (longitudinal edges included) is rounded by at least r, which fades out
                # before the returns start. The skin (the volume the shell dilates) follows the air, but its bay
                # fillets fade out over a shorter length before the returns, so the returns meet it flush.
                z_ret = L-g.return_depth
                r = g.section_radius*smooth01(z/g.section_ease)*(1-smooth01((z-(z_ret-g.outlet_fade))/g.outlet_fade))
                # V27 (return_frame): the skin follows the bay fillets up to the seat; the frame returns meet it there.
                fade = 1 if g.return_frame else 1-smooth01((z-(z_ret-g.skin_fillet_fade))/g.skin_fillet_fade)
                # The corners beside the splitter keep V23's sharp air corners (the shell's own 1.6 mm round outside):
                # a rounding there would leave a cusp against the solid web near the fan and a lens-shaped blend
                # between web and collar. The bay fillet that meets the splitter only grows once the web is a double skin.
                split = smooth01((z-z_sep)/g.splitter_round_length)
                reach = max(g.section_radius, g.passage_radius, g.upper_radius)
                h = splitter_half_width(g, z); band = box(-h-reach-2, -100, 100, 100) if i == 0 else box(-100, -100, h+reach+2, 100)
                def rounded(fillet_scale, r_scale):
                    # The opening also clears the zero-width needles the selective corner removals can leave.
                    q = p if fillet_scale == 1 else fillets(fillet_scale)
                    rq = max(.05, r*r_scale)
                    return q.buffer(-rq, quad_segs=16).buffer(rq, quad_segs=16).simplify(.002, preserve_topology=True) if z > 0 else q
                def composed(fillet_scale):
                    q = rounded(fillet_scale, 1)
                    q = unary_union([q.difference(band), rounded(fillet_scale*split, 0).intersection(band)]).buffer(0).simplify(.002, preserve_topology=True)
                    assert q.geom_type == 'Polygon' and q.is_valid, (i, z, fillet_scale, split)
                    return q
                p = composed(1)
                skin = p if fade == 1 else composed(fade)
            rings.append((p, float(z)))
            outer_rings.append((skin, float(z)))
            passage_fillet_data.append(dict(side=i, z_mm=float(z), radius_mm=float(passage_radius), corner_x_mm=xmin, corner_y_mm=float(bay_y), removed_flow_area_mm2=float(base.area-p.area)))
            section_data.append(dict(side=i, z_mm=float(z), area_mm2=p.area))
        loft = even_loft if g.shell_from_air else lambda rs, o: zip_loft([(np.asarray(q.exterior.coords)[:-1], z) for q, z in rs], o)
        inners.append(loft(rings, origin))
        outer_tools.append((outer_rings, origin))
    if g.splitter_groove_radius: _fill_groove(g, *[r for r, _ in outer_tools])
    outer_tools = [loft(r, o) for r, o in outer_tools]
    return inners, outer_tools, section_data, passage_fillet_data, upper_fillet_data


def _fill_groove(g: GeometryParams, left, right):
    """Keep the splitter web solid until the gap between the two skins exceeds 2*splitter_groove_radius.

    Where the two branch skins part they would otherwise meet in a knife-edge groove; the
    filled web ends in a short flat that the shell dilation rounds.
    """
    for k, ((a, z), (b, _)) in enumerate(zip(left, right)):
        h = splitter_half_width(g, z)
        if z == 0 or h >= g.wall_dilation+g.splitter_groove_radius: continue
        ya = a.intersection(LineString([[-h-.01, -100], [-h-.01, 100]])).bounds; yb = b.intersection(LineString([[h+.01, -100], [h+.01, 100]])).bounds
        web = box(-h-.01, max(ya[1], yb[1]), h, min(ya[3], yb[3]))
        q = a.union(web).simplify(.002, preserve_topology=True)
        assert q.geom_type == 'Polygon' and q.is_valid, z
        left[k] = (q, z)


def _smooth_profile(z, r, sigma):
    """Smooth r(z) without exceeding it much: moving minimum over 2*sigma, then a Gaussian of sigma (on a 0.1 mm grid)."""
    z = np.asarray(z); grid = np.arange(z[0], z[-1]+.05, .1); n = int(round(2*sigma/.1))
    smooth = gaussian_filter1d(minimum_filter1d(np.interp(grid, z, r), n, mode='nearest'), sigma/.1, mode='nearest')
    return np.interp(z, grid, smooth)


def _round_upper(p, R, corner):
    """V23's upper-shoulder rounding: open `p` by R and remove the pieces touching `corner`."""
    if R <= .01: return p
    opened = p.buffer(-R, quad_segs=24).buffer(R, quad_segs=24)
    delta = p.difference(opened)
    pieces = list(delta.geoms) if hasattr(delta, 'geoms') else [delta]
    removal = unary_union([q for q in pieces if q.distance(corner) < .01])
    return p.difference(removal).buffer(0).simplify(.002, preserve_topology=True)


def _round_corner(p, R, quad_segs, corner):
    """Open `p` by R and remove only the material pieces touching `corner`."""
    if R < .01: return p
    opened = p.buffer(-R, quad_segs=quad_segs).buffer(R, quad_segs=quad_segs)
    assert not opened.is_empty
    delta = p.difference(opened)
    pieces = list(delta.geoms) if hasattr(delta, 'geoms') else [delta]
    removed = unary_union([q for q in pieces if q.distance(corner) < .01])
    result = p.difference(removed).simplify(.002, preserve_topology=True)
    assert result.geom_type == 'Polygon' and result.is_valid
    return result


def _flange_fillet(g: GeometryParams, outer):
    """Concave quarter-round between the fan plate and the body, sampled radially from the fan axis.

    The radius fades where the body reaches the plate edge, so the fillet never needs clipping.
    """
    R = g.flange_fillet; ft = g.flange_thickness
    th = np.linspace(0, 2*np.pi, 1440, endpoint=False); c, s = np.cos(th), np.sin(th)
    edge = g.fan_plate/2/np.maximum(abs(c), abs(s))
    zs = ft+np.linspace(0, R, 9)
    rays = shapely.linestrings(np.stack([np.zeros((len(th), 2)), 300*np.c_[c, s]], axis=1))
    def reach(z):   # furthest boundary point along each ray: robust to tiny non-star-shaped wiggles
        rim = Polygon(max(outer.slice(float(z)).to_polygons(), key=lambda q: Polygon(q).area)).boundary
        pts, idx = shapely.get_coordinates(shapely.intersection(rim, rays), return_index=True)
        out = np.zeros(len(th)); np.maximum.at(out, idx, np.linalg.norm(pts, axis=1))
        return out
    body = np.array([reach(z) for z in zs])
    Rk = np.maximum(R*smooth01((edge-body[0])/(1.5*R)), .3)
    rings = []
    for u in np.linspace(0, 1, 17):
        z = ft+u*Rk
        rb = np.array([np.interp(zk, zs, body[:, k]) for k, zk in enumerate(z)])
        rad = np.minimum(rb+Rk*(1-np.sqrt(1-(1-u)**2))-.05*u, edge)
        rings.append(np.c_[rad*c, rad*s, z])
    return solid_rings([rings[0]*[1, 1, 0]+[0, 0, ft-.2]]+rings)


def _box(cx, rect, z, depth):
    x, y, w, h = rect
    return cube([w, h, depth], [cx+x, y, z])


def _rect_returns(g: GeometryParams, inner):
    """V23-V25 connector returns: the square return_rect outline minus the clearances, extruded return_depth below the seat, with
    ramped undersides growing from the bay floor and bay wall (the skin under them stays square over skin_fillet_fade)."""
    L = g.chamber_length
    # Integral rigid returns, retaining the housing/latch clearance. Each thin
    # return joins the shell directly; a second 2D offset here leaves a
    # sub-nozzle sliver at the rounded outer corner.
    d = g.return_depth
    protected = mf.CrossSection.batch_boolean([inner.slice(float(z)) for z in np.linspace(L-g.return_top_depth, L, 33)], mf.OpType.Add)
    def section(cx, rect):
        x, y, w, h = rect
        return mf.CrossSection.square([w, h]).translate([cx+x, y])
    returns = []
    for cx in g.card_x:
        safe = section(cx, g.return_rect)-protected
        outline = safe-section(cx, g.housing_clear)-section(cx, g.latch_clear)
        if g.return_round:
            # Round the stepped outline: convex corners by half the radius (the 1.3 mm latch wall survives), inside
            # corners by the full radius, which stays inside the 0.3 mm plug/latch clearance (checked below).
            ro, J = g.return_round, mf.JoinType.Round
            outline = (outline-section(cx, g.access_cut)).offset(-ro/2, J, circular_segments=64).offset(ro/2, J, circular_segments=64).offset(ro, J, circular_segments=64).offset(-ro, J, circular_segments=64)
        full_return = mf.Manifold.extrude(outline, d).translate([0, 0, L-d])
        # Grow the underside from the floor and inner wall at a bounded lateral
        # advance per mm of print height, avoiding a cantilevered ledge.
        bottom_rings = []; side_rings = []
        for z in np.linspace(L-d, L, 41):
            advance = g.return_ramp_slope*(z-(L-d))
            ytop = g.bay_floor_y+advance
            xleft = cx+bay_wall_x(g, z)+g.skin_wall-advance
            bottom_rings.append(np.array([[cx-50, 0, z], [cx+30, 0, z], [cx+30, ytop, z], [cx-50, ytop, z]]))
            side_rings.append(np.array([[xleft, 0, z], [cx+30, 0, z], [cx+30, 90, z], [xleft, 90, z]]))
        returns.append(full_return^union(solid_rings(bottom_rings), solid_rings(side_rings)))
    # Open the outer/top L-shaped rim of each return; keep the lower return and
    # the inner wall beside the latch. Neither bore nor air passage moves.
    open_access = []
    for cx in g.card_x:
        cut = _box(cx, g.access_cut, L-d-.01, d+.1)
        assert (cut^inner).volume() < 1e-6, 'Access trim enters main air passage'
        open_access.append(cut)
    ramped_returns = union(*returns)-union(*open_access)
    if g.section_radius: ramped_returns -= inner  # the rounded passage can graze the protected-slice boundary
    assert (ramped_returns^inner).volume() < 1e-4
    return ramped_returns


def _frame_returns(g: GeometryParams, inner, body, rings):
    """V27 connector returns: only the seat frame that the rounded shell does not already provide.

    The skin follows the bay fillets up to the seat (return_frame), so the shell is a uniform wall around the rounded
    air everywhere. At the seat it must still carry the square collar (its footprint reaches 0.4 mm below the seat) and,
    as the lower return, a lip flush with the plug-pocket floor (housing_clear) along the bay floor. That target outline,
    within the bay quadrant of each card, gets an underside that recedes from every free edge at return_ramp_slope per mm
    of height (the 3-D Minkowski sum of the free space with a cone), so it grows out of the rounded shell without an
    overhang steeper than atan(slope) and without a cavity: everything between the target and the shell is solid, and
    nothing below the receding underside is. Every height follows from L.
    """
    L = g.chamber_length; s = g.return_ramp_slope; w = g.wall_dilation; hh = g.bore[1]/2
    d = g.return_depth; z_top = L-.4   # the collar reaches 0.4 mm below the seat: the frame is full width from there up
    J = mf.JoinType.Round
    def section(cx, rect):
        x, y, rw, rh = rect
        return mf.CrossSection.square([rw, rh]).translate([cx+x, y])
    air = inner.slice(L-1e-3)
    # The lip stays 0.4 mm clear of the air: it overlaps the 1.2 mm shell with every inner face buried in it (a face on
    # the passage wall would be near-coincident with it); the shell's own recession below the seat stays well under 0.8 mm.
    keep_off = air.offset(.4, J, circular_segments=64)
    lips = []; ring_parts = []; support = []; seals = []
    for cx, ring in zip(g.card_x, rings):
        bay = cx+bay_wall_x(g, L)+g.skin_wall
        x0 = ring.bounds()[0]; y0 = g.bay_floor_y-g.passage_radius-w-1             # outer collar face; below the deepest passage fillet
        x1 = bay+min(g.upper_outlet_radius, g.upper_radius)+w+1                    # past the upper fillet under the collar's top wall
        # Square in plan: its one free convex corner, rounded, would undercut to a cone apex (degenerate facets)
        lip = mf.CrossSection.square([bay-x0, g.housing_clear[1]-y0]).translate([x0, y0])-section(cx, g.housing_clear)-section(cx, g.latch_clear)-keep_off
        lips.append(lip)
        # The lip covers the collar's outer wall and its notch end (flush with its outer face x0). Along the top wall, the ring
        # beyond its half-round end is extruded as is, so its faces coincide exactly with the collar's (a 2-D boolean would
        # re-quantize them); under the half round a square block, up to the collar's underside only, carries it: undercut,
        # it gives two return_ramp_slope planes crossing the bay-wall shell, not a cone whose apex grazes it just inside its surface.
        xe = cx+g.power_notch[0]+g.collar_wall; ytop = ring.bounds()[3]
        ring_parts.append(mf.Manifold.extrude(ring, d).translate([0, 0, L-d])^cube([x1-xe, ytop-hh+1, d+.2], [xe, hh-.5, L-d-.1]))
        end = mf.CrossSection.square([g.collar_wall, ytop-hh]).translate([cx+g.power_notch[0], hh])
        ring_parts.append(mf.Manifold.extrude(end, z_top-(L-d)).translate([0, 0, L-d]))
        # Between the upper fillet's rounded shell and the collar's top wall: seat closure, so that wall grows out of the shell
        # instead of hanging over the gap
        yu = hh-min(g.upper_outlet_radius, g.upper_radius)-w-1
        corner = mf.CrossSection.square([x1-(cx+g.power_notch[0]), hh-yu]).translate([cx+g.power_notch[0], yu])-section(cx, g.latch_clear)-keep_off
        lips.append(corner)
        part = lip+corner
        if g.seat_seal:
            # The card face beside the pocket, between the housing clearance and the rounded bay wall: the fin channels run
            # across the card, so an exposed end there leaks the passage's air. It covers the fin stack (port boxes) and stops
            # a collar half-width short of the bore's edge, clear of the block under the collar's half-round end.
            y_fin = max(max(abs(y0_), abs(y1_)) for _, _, (_, _, y0_, y1_) in g.port_boxes); ys = max(y_fin, hh-g.collar_wall/2)
            xh = cx+g.housing_clear[0]+g.housing_clear[2]   # from the housing clearance's edge: above it the bore is beyond the fin stack
            seal = mf.CrossSection.square([bay-xh, ys-g.bay_floor_y]).translate([xh, g.bay_floor_y]) \
                - section(cx, g.housing_clear)-section(cx, g.latch_clear)-keep_off
            # Grown from the bay-wall shell alone: one return_ramp_slope plane rising from it to the housing clearance's edge,
            # vertical faces at the latch and top edges. Undercut from those edges too, it would end in a horizontal
            # knife-edge ridge hanging off the shell.
            zb = L-d-.1
            ramp = solid_rings([np.array([[cx-50, -100, z], [xh+.1+s*(z_top-z), -100, z], [xh+.1+s*(z_top-z), 100, z], [cx-50, 100, z]]) for z in (zb, z_top)])
            seals.append(mf.Manifold.extrude(seal, d).translate([0, 0, L-d])-ramp)
            part = part+seal
        support.append(part+(ring^mf.CrossSection.square([x1-x0, hh+w+1-y0]).translate([x0, y0]))+end)
    support = mf.CrossSection.batch_boolean(support, mf.OpType.Add)
    filled = body.slice(z_top-.05)+inner.slice(z_top-.05)+air        # the shell outline, passages included
    free = support.offset(s*d+1, J, circular_segments=64)-support-filled
    free = free.offset(-.05, J, circular_segments=32).offset(.05, J, circular_segments=32)   # not the hairline gaps between ring and shell
    cone = mf.Manifold.cylinder(d, s*d, 0., 32).translate([0, 0, -d])  # apex up: the region a free point undercuts below it
    eps = .01
    # Below z_top the underside starts 0.1 mm inside the free edges: no face grazes (or lies within the ~0.02 mm kernel
    # hairline of) the dilated outer wall it meets. Above z_top the frame is the target itself, the ring exactly the collar's.
    cut = mf.Manifold.extrude(free.offset(.1, J, circular_segments=64), eps).translate([0, 0, z_top-eps]).minkowski_sum(cone)
    frame = union(mf.Manifold.extrude(mf.CrossSection.batch_boolean(lips, mf.OpType.Add), d).translate([0, 0, L-d]), *ring_parts)-cut
    if seals: frame = union(frame, *seals)
    frame = frame-inner
    assert (frame^inner).volume() < 1e-4
    return frame


def build_duct(g: GeometryParams) -> DuctSolids:
    L = g.chamber_length; R = g.fan_radius; bw, bh = g.bore; hw, hh = bw/2, bh/2
    cl = g.collar_length; cw = g.collar_wall; ft = g.flange_thickness; P = g.fan_plate

    # Outward-only reinforcement: identical collars on both GPU seats.
    # The inner bore and power notch are unchanged.
    # (V24 builds its collars from the shell kernel below.)
    collars = []
    for cx in [] if g.shell_from_air else g.card_x:
        reinforced = plate(bw+2*cw, bh+2*cw, cw, L, cl).translate([cx, 0, 0])
        bore = cube([bw, bh, cl+.2], [cx-hw, -hh, L-.1])
        notch = cube([100, 100, cl+.2], [cx+g.power_notch[0]-100, g.power_notch[1], L-.1])
        collars.append(reinforced-bore-notch)

    inners, outer_tools, section_data, passage_fillet_data, upper_fillet_data = _passages(g)
    # The fan face must open only into the two sealed branches. A watertight
    # material mesh alone does not catch an uncovered portion of the fan aperture.
    for side in [0, 1]:
        expected = _fan_half(g, side).area
        actual = next(row["area_mm2"] for row in section_data if row["side"] == side and row["z_mm"] == 0)
        assert abs(actual-expected) < .1, "Uncovered fan-face region in branch "+str((side, actual, expected))
    inner = union(*inners)
    air = inner
    fairing = hub_fairing(g) if g.hub_fairing else None
    if fairing:
        # The fairing is solid in the passage (body = outer - inner); its cavity opens onto the fan face instead of the air
        inner -= fairing.outer
        hub = Point(0, 0).buffer(g.hub_fairing_d/2-.05, quad_segs=64)
        assert area_inside(inner.slice(1e-3), hub) < 1e-3, 'air in front of the fan hub with the fairing on'

    # Dilate the passage in 3D (not per section) to retain normal wall thickness on steep slopes.
    kernel = mf.Manifold.sphere(1., int(g.kernel_segments)); raw = kernel.to_mesh64()
    kv = np.asarray(raw.vert_properties)[:, :3]; kt = kv[np.asarray(raw.tri_verts)]
    kn = np.cross(kt[:, 1]-kt[:, 0], kt[:, 2]-kt[:, 0]); kn /= np.linalg.norm(kn, axis=1)[:, None]
    inradius = np.min(np.einsum('ij,ij->i', kn, kt[:, 0]))
    kernel = kernel.scale([g.wall_dilation/inradius]*3)
    outer = dilate(union(*outer_tools).simplify(g.shell_simplify), kernel)
    outer = outer.trim_by_plane([0, 0, 1], 0.0).trim_by_plane([0, 0, -1], -L)
    outer = outer^cube([P, P, L+1], [-P/2, -P/2, 0])
    if g.shell_from_air:
        # The same kernel dilates the bore into the collar, so collar and body meet flush; the collar reaches
        # 0.4 mm into the body (an overlap, not a coplanar seam) and its wall ends at the power notch are full rounds.
        assert abs(g.wall_dilation-cw) < 1e-9, 'shell_from_air dilates the collar by wall_dilation'
        collars = []; rings = []
        for cx in g.card_x:
            ring = cube([bw, bh, cl], [cx-hw, -hh, L]).minkowski_sum(kernel).slice(L+cl/2)-mf.CrossSection.square([bw, bh]).translate([cx-hw, -hh]) \
                - mf.CrossSection.square([100, 100]).translate([cx+g.power_notch[0]-100, g.power_notch[1]])
            ring = ring.offset(-cw/2+.01, mf.JoinType.Round, circular_segments=64).offset(cw/2-.01, mf.JoinType.Round, circular_segments=64)
            rings.append(ring)
            collars.append(mf.Manifold.extrude(ring, cl+.4).translate([0, 0, L-.4]))
        if g.shared_wall:
            # One wall between the bores: the two inner walls' rounded outer corners would leave a V-groove down its -y end
            # (the +y end is card B's power notch, where only card A's wall continues). Fill it flush with the outer wall.
            sw = g.shared_wall
            bridge = mf.CrossSection.square([sw, cw+1]).translate([-sw/2, -hh-cw])
            collars.append(mf.Manifold.extrude(bridge, cl+.4).translate([0, 0, L-.4]))
    if g.flange_fillet: outer = union(outer, _flange_fillet(g, outer))
    body = outer-inner
    fan_flange = plate(P, P, g.fan_plate_corner_radius, 0, ft)-cylinder(R, ft+.2, -.1)
    for x in [-g.fan_hole_offset, g.fan_hole_offset]:
        for y in [-g.fan_hole_offset, g.fan_hole_offset]:
            fan_flange -= mf.Manifold.cylinder(ft+.2, g.fan_hole_radius, circular_segments=48).translate([x, y, -.1])
    final = union(fan_flange, body, *collars)
    if fairing and g.shared_wall:   # one wall between the bores: the cavity cuts through it, one clean cone
        final = union(final, fairing.outer)-fairing.cavity
    elif fairing:
        # A parted web: the fairing stops at the branch skins (no tip in the gap between them, outside `outer`) and its
        # cavity at the web, which stands whole through it: a half cone each side, closed by the skins
        below = union(*[mf.Manifold.extrude(mf.CrossSection([np.asarray(orient(_fan_half(g, i), 1).exterior.coords)[:-1]]), 5.0)
                        .translate([0, 0, -5]) for i in (0, 1)])
        final = union(final, fairing.outer^outer)-(fairing.cavity^union(air, below))
    # Identical card fit and a lead-in chamfer, with no bore intrusions.
    for cx in g.card_x:
        final -= cube([bw, bh, cl+.1], [cx-hw, -hh, L])
        lead = []
        for z, w, h in [(L+g.lead_in_z[0], bw, bh), (L+g.lead_in_z[1], *g.lead_in_bore)]:
            lead.append(np.array([[cx-w/2, -h/2, z], [cx+w/2, -h/2, z], [cx+w/2, h/2, z], [cx-w/2, h/2, z]]))
        final -= solid_rings(lead)

    assert g.return_frame or not g.seat_seal, "seat_seal extends the return_frame seat frame"
    if g.return_frame:
        assert g.shell_from_air, "return_frame builds on the shell_from_air collars and skin"
        ramped_returns = _frame_returns(g, inner, final, rings)
    else:
        ramped_returns = _rect_returns(g, inner)
    final = union(final, ramped_returns).as_original()

    # Preserve the full slip clearance around the connector and latch over the
    # straight insertion/unplug sweep, as a contoured pocket rather than a
    # rectangular service trim.
    z0 = L-g.sweep_start; depth = g.sweep_length
    def clearance(cx): return union(_box(cx, g.housing_clear, z0, depth), _box(cx, g.latch_clear, z0, depth))
    for cx in g.card_x:
        guard = clearance(cx)
        assert (guard^inner).volume() < 1e-6, 'Connector guard intersects flow passage'
        final -= guard
    collisions = []; bay_collisions = []
    for cx in g.card_x:
        collisions.append(float((final^union(_box(cx, g.plug, z0, depth), _box(cx, g.latch, z0, depth))).volume()))
        assert collisions[-1] < 1e-4, 'Plug/latch collision'
        assert (final^cube([bw-.002, bh-.002, cl], [cx-hw+.001, -hh+.001, L+.0001])).volume() < 1e-4  # 1 µm inset: coplanar-face noise is not an intrusion
        bay = clearance(cx)
        assert (inner^bay).volume() < 1e-6, 'Rounded pocket enters plug/latch insertion sweep'
        final -= bay
        bay_collisions.append(float((final^bay).volume()))
        assert bay_collisions[-1] < 1e-4, 'Connector service bay collision'
    # Restore the ramped returns after trimming the surrounding service bay (the V27 frame excludes both clearances already).
    if not g.return_frame: final = union(final, ramped_returns)

    splitter = [dict(z_mm=float(z), half_width_mm=float(splitter_half_width(g, z))) for z in np.linspace(0, L, 551)]
    return DuctSolids(g, inner, final, upper_fillet_data, passage_fillet_data, section_data, splitter, collisions, bay_collisions,
                      hub_fairing=fairing.info if fairing else None, hub_fairing_cavity=fairing.cavity if fairing else None)
