"""Push-pull exhaust collector over the rear slot brackets. Pure: no file I/O.

A rounded-rectangle mouth over the five slot positions (both dual-slot brackets and the blank middle slot)
lofts to the round 117 mm bore of a 120 mm fan plate. As in V24, the shell is the 3-D dilation of the rounded
air volume, so the walls are a uniform `wall` (1.2 mm). Print orientation: flange (case face) on the bed; the four fan
plate corners rest on 45 degree chamfers, which the fan-screw pilots pass through.

Experimental: no hardware has been measured; every hardware number is an assumption in CollectorParams.
"""
from dataclasses import dataclass

import manifold3d as mf
import numpy as np
import shapely
import shapely.affinity
import shapely.ops
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.polygon import orient

from ..params import CollectorParams
from .geometry import ramp, smooth01, solid_rings, union


@dataclass(frozen=True)
class CollectorSolids:
    params: CollectorParams
    inner: mf.Manifold                  # air: bracket plane (z = inlet_z) to the fan face, one watertight body
    final: mf.Manifold                  # printable solid, in the duct frame (flange face on z = inlet_z)
    gauge: mf.Manifold                  # 1 mm fit gauge of the flange footprint, case face on z = 0
    sections: list[dict]                # air section half-widths, corner radius and area along the plenum
    features: dict                      # mount, fan-hole and notch positions
    clips: mf.Manifold | None = None    # mount 'snap': the clips in place (collector frame), printed as separate parts

    @property
    def solid(self) -> mf.Manifold:
        return self.final


def rounded_rect(a, b, r, centre=(0., 0.), n=512):
    """Rounded rectangle (half-widths a, b, corner radius r), counter-clockwise, sampled at n outward-normal angles.

    Every loft section uses the same normal-angle parametrisation, so the rings stay in step from the mouth
    (small corners) to the round fan end (r = a = b); straight sides become single long quads.
    """
    t = (np.arange(n)+.5)*2*np.pi/n
    c, s = np.cos(t), np.sin(t)
    return np.c_[centre[0]+np.sign(c)*(a-r)+r*c, centre[1]+np.sign(s)*(b-r)+r*s]


def _u(c: CollectorParams, s):
    """Loft fraction at distance s: zero slope at both ends, flush with flange and plate (smoothstep, or a bounded-slope ramp)."""
    t = s/(c.plenum_depth-c.fan_plate_thickness)
    return ramp(t, c.ease_ramp) if c.ease_ramp else smooth01(t)


def section_at(c: CollectorParams, s):
    """Air section (a, b, r) at distance s from the bracket plane; straight through the fan plate."""
    (x0, x1), (y0, y1) = c.window_x, c.window_y; R = c.fan_radius; u = _u(c, s)
    a0, b0 = (x1-x0)/2, (y1-y0)/2
    if c.fan_dy:   # the window's y edges move to the bore's, which sits off the window centre
        ay = c.fan_axis[1]; b = ((y1+(ay+R-y1)*u)-(y0+(ay-R-y0)*u))/2
    else: b = b0+(R-b0)*u
    return a0+(R-a0)*u, b, c.window_corner_radius+(c.fan_end_corner_radius-c.window_corner_radius)*u


def section_centre(c: CollectorParams, s):
    """Centre of the air section at s: the window centre, moving to the fan axis."""
    if not c.fan_dy: return c.fan_axis
    (y0, y1), ay, R, u = c.window_y, c.fan_axis[1], c.fan_radius, _u(c, s)
    return (c.fan_axis[0], ((y1+(ay+R-y1)*u)+(y0+(ay-R-y0)*u))/2)


def window_centre(c: CollectorParams):
    return (sum(c.window_x)/2, sum(c.window_y)/2)


def air_volume(c: CollectorParams, n=None, extend=0.0) -> mf.Manifold:
    """Loft from the bracket plane to the fan face; `extend` prolongs both straight ends (for the dilation tool)."""
    if c.split: return _split_air(c, n or c.loft_points, extend)
    z0 = c.inlet_z; D = c.plenum_depth; ctr = c.fan_axis; n = n or c.loft_points
    ss = [-extend]*bool(extend)+list(np.linspace(0, D-c.fan_plate_thickness, c.loft_rings))+[D+extend]
    rings = [np.c_[rounded_rect(*section_at(c, max(s, 0)), section_centre(c, max(s, 0)), n), np.full(n, z0+s)] for s in ss]
    return solid_rings(rings, ctr)


# Split collector (c.split): one mouth and gasket loop per card, one plenum to the bore, a splitter fin between the cards

def card_mouths(c: CollectorParams) -> list[tuple[float, float, float, float]]:
    """Each card's mouth (x0, x1, y0, y1): its two chassis openings plus split_margin in x, mouth_y in y."""
    ops = sorted(c.openings); m = c.split_margin; y0, y1 = c.window_y
    if c.mouth_x: return [(a, b, y0, y1) for a, b in c.mouth_x]
    return [(ops[0][0]-m, ops[1][1]+m, y0, y1), (ops[-2][0]-m, ops[-1][1]+m, y0, y1)]


def _rrect(x0, x1, y0, y1, radii, n=24) -> Polygon:
    """Rectangle with per-corner radii (bottom-left, bottom-right, top-right, top-left), counter-clockwise."""
    pts = []
    for (cx, cy, r, a0) in ((x0, y0, radii[0], np.pi), (x1, y0, radii[1], 1.5*np.pi), (x1, y1, radii[2], 0.), (x0, y1, radii[3], .5*np.pi)):
        if r <= 1e-9: pts.append((cx, cy)); continue
        ox, oy = cx-np.sign(np.cos(a0+np.pi/4))*r, cy-np.sign(np.sin(a0+np.pi/4))*r
        pts += [(ox+r*np.cos(a), oy+r*np.sin(a)) for a in np.linspace(a0, a0+np.pi/2, n)]
    return Polygon(pts)


def mouths(c: CollectorParams) -> list[tuple[float, float, float, float]]:
    """The mouths through the flange: one per card (card_mouths), or one per chassis opening (x +- split_margin, y mouth_y),
    sorted in x. The gasket loops, the fin line and the plenum envelope always follow card_mouths."""
    if not c.per_opening_mouths: return card_mouths(c)
    m = c.split_margin; y0, y1 = c.window_y; cards = card_mouths(c)
    return [(o[0]-m, o[1]+m, y0, y1) for o in sorted(c.openings) if any(k[0]-1e-6 <= o[0]-m and o[1]+m <= k[1]+1e-6 for k in cards)]


def mouth_sides(c: CollectorParams) -> list[tuple[str, str]]:
    """Each mouth's (left, right) edge: 'outer' (a plenum side wall), 'web' (the web between the cards) or 'rib' (the strip
    between a card's two per-opening mouths)."""
    if not c.per_opening_mouths: return [('outer', 'web'), ('web', 'outer')]
    return [('outer', 'rib'), ('rib', 'web'), ('web', 'rib'), ('rib', 'outer')]


def mouth_radii(c: CollectorParams) -> list[tuple[float, float, float, float]]:
    """Corner radii (bottom-left, bottom-right, top-right, top-left) per mouth. Card mouths: mouth_corners (outer-bottom,
    inner-bottom, inner-top, outer-top), mirrored for card B; per-opening mouths: rib_corners on the rib side, the bottom
    ones no larger than rib_corners[0]."""
    if not c.mouth_corners: return [(c.window_corner_radius,)*4]*len(mouths(c))
    ob, ib, it, ot = c.mouth_corners; rb, rt = c.rib_corners; out = []
    for left, right in mouth_sides(c):
        def corner(side, top):
            if side == 'rib': return rt if top else rb
            r = (ot if top else ob) if side == 'outer' else (it if top else ib)
            return r if top or not c.per_opening_mouths else min(r, rb)
        out.append((corner(left, False), corner(right, False), corner(right, True), corner(left, True)))
    return out


def lip_offset(c: CollectorParams, s: float) -> float:
    """Inlet lip at s from the bracket plane: the sides and bottom roll outward by `lip` (smoothstep, end radius ~lip)."""
    if not c.lip: return 0.0
    return c.lip*float(smooth01((s-c.lip_start)/(2.45*c.lip)))


def web_round_offset(c: CollectorParams, s: float) -> float:
    """Quarter round on the wide web's top edges (inside the flange): vertical at tf - web_round, flat on the web at tf."""
    r = c.web_round; d = s-(c.flange_thickness-r)
    return 0.0 if not r or d <= 0 else r-float(np.sqrt(max(r*r-min(d, r)**2, 0.)))


def _web_is_wide(c: CollectorParams) -> bool:
    a, b = card_mouths(c); return b[0]-a[1] > c.fin_thickness+4*c.vane_root


def _mouth_air(c: CollectorParams, extend: float) -> list[mf.Manifold]:
    """The mouths through the flange: straight prisms (v3), or (lip / web_round) lofted with the lip on the outer sides and
    bottom and the quarter round on a wide web's edges."""
    z0 = c.inlet_z; tf = c.flange_thickness
    if not (c.lip or c.web_round or c.mouth_corners):
        return [_extrude(_rrect(*m, (c.window_corner_radius,)*4), z0-extend, tf+extend+.3) for m in card_mouths(c)]
    wide = _web_is_wide(c); out = []
    ss = np.r_[-extend, np.linspace(0, tf+.3, 32)]
    for (x0, x1, y0, y1), (left, right), radii in zip(mouths(c), mouth_sides(c), mouth_radii(c)):
        def d(side, s):
            if side == 'outer': return lip_offset(c, s)
            return web_round_offset(c, s) if side == 'web' and wide and not c.fill_web else 0.0
        polys = [(_rrect(x0-d(left, v), x1+d(right, v), y0-lip_offset(c, v), y1, radii), z0+v) for v in ss]
        out.append(_ring_loft(polys, 256))
    return out


def _vane_y(c: CollectorParams, s: float, xs) -> tuple[float, float]:
    """The y range a vane may span at s over x in xs: FIN_END_GAP inside the plenum section (or the mouth envelope below the flange top)."""
    sec = split_section(c, max(s, c.flange_thickness)); lo, hi = [], []
    for x in xs:
        seg = sec.intersection(LineString([(x, -300), (x, 300)])); lo.append(seg.bounds[1]); hi.append(seg.bounds[3])
    return max(lo)+FIN_END_GAP, min(hi)-FIN_END_GAP


def _vane(c: CollectorParams, edges, s_top: float, n: int = 90) -> tuple[mf.Manifold, dict]:
    """A vane standing on the flange: edges(s) -> (left, right) x of its section at s, from 0.5 mm under the flange top to
    s_top, where its top is a full round (the edges close on a semicircle over the last half width). The y ends stay
    FIN_END_GAP off the plenum walls."""
    tf = c.flange_thickness; z0 = c.inlet_z; w = c.fin_thickness/2
    ss = np.r_[tf-.5, np.linspace(tf, s_top-w, n), s_top-w+w*np.sin(np.linspace(0, np.pi/2, 13)[1:])]
    rings = []; prof = []
    for v in ss:
        l, r = edges(min(v, s_top-w))
        if v > s_top-w:     # the full-round top
            cx = (l+r)/2; hw = max(w*np.sqrt(max(1-((v-(s_top-w))/w)**2, 0)), .02); l, r = cx-hw, cx+hw
        ylo, yhi = _vane_y(c, v, (l, (l+r)/2, r))
        rings.append(np.array([(l, ylo, z0+v), (r, ylo, z0+v), (r, yhi, z0+v), (l, yhi, z0+v)])); prof.append((float(v), float(l), float(r)))
    return solid_rings(rings), dict(profile=prof)


def _s_root(x_edge, x_face, s, tf, H):
    """S-curve from a mouth edge (vertical at the flange top) to a fin face (vertical at tf + H)."""
    return x_edge+(x_face-x_edge)*float(smooth01((s-tf)/H))


def vanes(c: CollectorParams) -> list[tuple[str, mf.Manifold, dict]]:
    """The free-standing vanes subtracted from the air (vane_style 'v4'): the centre fin (on the web between the cards) and,
    with rib_fins, one fin per card on the strip between its two mouths. Roots: on a narrow strip (rib strips, the 4-slot
    centre web) an S-curve from the mouth edges into the fin faces, end radius >= vane_root; on a wide web (5-slot) a
    concave quarter-round fillet of vane_root, or with fill_web an S-curve leaning <= fill_angle with radius >= merge_fillet.
    Every vane ends in a full-round top, its y ends FIN_END_GAP off the walls."""
    tf = c.flange_thickness; w = c.fin_thickness/2; out = []
    (_, ax1, _, _), (bx0, _, _, _) = card_mouths(c); xc = (ax1+bx0)/2; h = (bx0-ax1)/2-w
    if c.fill_web:
        H = max(1.5*h/np.tan(np.radians(c.fill_angle)), np.sqrt(6*h*c.merge_fillet))
        edges = lambda s: (_s_root(ax1, xc-w, s, tf, H), _s_root(bx0, xc+w, s, tf, H))  # noqa: E731
        kind = dict(root='fill', H=float(H), min_radius=float(H*H/(6*h)), max_lean_deg=float(np.degrees(np.arctan(1.5*h/H))))
    elif _web_is_wide(c):
        r = c.vane_root
        def edges(s):
            d = min(max(s-tf, 0.), r); e = r-np.sqrt(max(r*r-(r-d)**2, 0.)); return (xc-w-e, xc+w+e)
        kind = dict(root='fillet', radius=r)
    else:
        H = np.sqrt(6*h*c.vane_root)
        edges = lambda s: (_s_root(ax1, xc-w, s, tf, H), _s_root(bx0, xc+w, s, tf, H))  # noqa: E731
        kind = dict(root='s-curve', H=float(H), min_radius=float(H*H/(6*h)))
    m, info = _vane(c, edges, split_end(c)); out.append(('centre', m, {**info, **kind, 'x': xc, 'top_s': split_end(c)}))
    if c.rib_fins:
        ms = mouths(c)
        for k, (a, b) in enumerate(((ms[0], ms[1]), (ms[-2], ms[-1]))):
            xe0, xe1 = a[1], b[0]; x_c = (xe0+xe1)/2; hh = (xe1-xe0)/2-w; H = np.sqrt(6*hh*c.vane_root); sgn = -1 if k == 0 else 1
            top = c.rib_fin_end
            def edges(s, xe0=xe0, xe1=xe1, x_c=x_c, H=H, sgn=sgn, top=top):
                cx = x_c+sgn*c.rib_fin_lean*float(smooth01((s-tf)/(top-tf)))
                return _s_root(xe0, cx-w, s, tf, H), _s_root(xe1, cx+w, s, tf, H)
            m, info = _vane(c, edges, top)
            out.append((f'rib {"AB"[k]}', m, {**info, 'root': 's-curve', 'H': float(H), 'min_radius': float(H*H/(6*hh)), 'x': x_c,
                                              'lean': c.rib_fin_lean*sgn, 'top_s': top}))
    return out


def _hub_fairing_profile(c: CollectorParams):
    """The fairing's (r, s) profile: the outer flank with its round tip, the cavity wall (rim down), and the numbers."""
    R = c.hub_fairing_d/2; p = c.hub_fairing_power; k = np.tan(np.radians(c.hub_fairing_angle)); w = c.wall
    s_base = c.plenum_depth-c.fan_plate_thickness; L = p*R/k; s_tip = s_base-L; rho = c.hub_fairing_tip
    assert s_tip >= c.flange_thickness+2, ('hub fairing tip too close to the flange', s_tip)
    t = np.linspace(0, 1, 160); r = R*(1-t**p); ss = s_base-t*L
    dr = np.gradient(r, ss); nrm = np.c_[1/np.sqrt(1+dr**2), -dr/np.sqrt(1+dr**2)]   # outward normal (r, s) of the flank
    a = np.arctan(k); keep = r > rho*np.cos(a)+1e-6                                     # the round tip replaces the rest
    s_c = ss[keep][-1]+rho*np.sin(a)                                                  # its centre: on the axis, tangent to the flank
    arc = [(rho*np.cos(th), s_c-rho*np.sin(th)) for th in np.linspace(a, np.pi/2, 12)]
    outer = [*zip(r[keep], ss[keep]), *arc]                                            # rim down the flank to the tip (on the axis)
    inner = np.c_[r, ss]-w*nrm; ok = inner[:, 0] > .3                                  # the cavity wall, from the rim down
    return outer, inner[ok], dict(R=R, p=p, w=w, rho=rho, s_base=s_base, s_c=s_c, L=L, dr=dr)


def hub_fairing(c: CollectorParams, segments: int = 128) -> tuple[mf.Manifold, dict]:
    """The hub fairing: a shell of revolution (wall thick) on the fan axis, its base (hub_fairing_d) at the fan plate's
    underside, open toward the fan; radius R (1 - t^p) from the base (t 0) toward the panel (t 1), the flank reaching
    hub_fairing_angle from vertical at the tip, which is a solid round of hub_fairing_tip. It stands on the centre fin
    (the fin meets its outside; hub_fairing_cavity clears the fin from its inside), so it prints flange-down: it only
    widens going up, at <= hub_fairing_angle."""
    outer, inner, q = _hub_fairing_profile(c); R, p, w, rho, s_base, s_c, L, dr = (q[n] for n in ('R', 'p', 'w', 'rho', 's_base', 's_c', 'L', 'dr'))
    prof = [*outer[::-1], *(tuple(v) for v in inner), (0.0, float(inner[-1][1]))]
    poly = Polygon([(max(x, 0.0), z) for x, z in prof]).buffer(0)
    poly = max(getattr(poly, 'geoms', [poly]), key=lambda q: q.area)
    ring = np.asarray(orient(poly, 1).exterior.coords)[:-1]
    m = mf.Manifold.revolve(mf.CrossSection([ring]), segments).translate([*c.fan_axis, c.inlet_z])
    return m, dict(base_d_mm=2*R, base_s_mm=float(s_base), tip_s_mm=float(s_c-rho), length_mm=float(L), power=p, wall_mm=w,
                   steepest_flank_deg=float(np.degrees(np.arctan(np.max(np.abs(dr))))), tip_radius_mm=rho,
                   cavity_volume_mm3=float(np.pi*np.trapezoid(np.clip(inner[:, 0], 0, None)**2, -inner[:, 1])))


def hub_fairing_cavity(c: CollectorParams, segments: int = 128, up: float = .5) -> mf.Manifold:
    """The fairing's cavity as a solid, `up` into the fan bore: dead air behind the fan hub, cleared of the centre fin."""
    _, inner, q = _hub_fairing_profile(c); top = q['s_base']+up
    ring = [(0.0, top), (0.0, float(inner[-1][1])), *((float(r), float(s)) for r, s in inner[::-1]), (float(inner[0][0]), top)]
    poly = orient(Polygon(ring).buffer(0), 1)
    return mf.Manifold.revolve(mf.CrossSection([np.asarray(poly.exterior.coords)[:-1]]), segments).translate([*c.fan_axis, c.inlet_z])


def air_wall_angles(c: CollectorParams) -> dict:
    """Plenum wall angles from vertical, from the triangle normals of the air (air_volume: no vanes, no fairing) between the
    flange top and the fan plate. 'ceiling' faces look down into the air (an overhang of the inner skin as printed, flange
    down); 'floor' faces look up (the air widens: the inner skin is self-supporting, only an outer skin parallel to it would
    overhang; the overhang gate checks the real outer skin)."""
    import trimesh
    m = air_volume(c).to_mesh(); t = trimesh.Trimesh(np.asarray(m.vert_properties)[:, :3], np.asarray(m.tri_verts), process=False)
    n = t.face_normals; ctr = t.triangles_center; s = ctr[:, 2]-c.inlet_z; tf = c.flange_thickness; se = c.plenum_depth-c.fan_plate_thickness
    deg = np.degrees(np.arcsin(np.clip(np.abs(n[:, 2]), 0, 1))); wall = (np.abs(n[:, 2]) < .999) & (s >= tf) & (s < se)
    out = {}
    for name, sel in (('ceiling', wall & (n[:, 2] > 0)), ('floor', wall & (n[:, 2] < 0))):
        d = deg[sel]; i = int(np.argmax(d)); over = d > c.max_wall_angle
        out[name] = dict(peak_deg=round(float(d[i]), 2), at_xys_mm=[round(float(ctr[sel][i, 0]), 2), round(float(ctr[sel][i, 1]), 2), round(float(s[sel][i]), 2)],
                         area_over_limit_mm2=round(float(t.area_faces[sel][over].sum()), 2),
                         over_limit_s_max_mm=round(float(s[sel][over].max()), 2) if over.any() else None,
                         over_limit_y_max_mm=round(float(ctr[sel][over, 1].max()), 2) if over.any() else None)
    return out


def card_windows(c: CollectorParams) -> list[tuple[float, float, float, float]]:
    """Each card's bracket vent window (x0, x1, y0, y1), from vent_window (hardware.windows)."""
    L, W, top = c.vent_window; y1 = c.bracket_top_y-top
    return [(cx-W/2, cx+W/2, y1-L, y1) for cx in (-c.card_pitch/2, c.card_pitch/2)]


def snap_sites(c: CollectorParams) -> list[dict]:
    """Where the snap arms go: on each card window's outer x edge (out: the outward x sign), at snap_arm_y from its centre."""
    out = []
    for k, (x0, x1, y0, y1) in enumerate(card_windows(c)):
        sgn = -1 if k == 0 else 1
        out += [dict(card='AB'[k], edge_x=x0 if k == 0 else x1, out=sgn, y=(y0+y1)/2+dy) for dy in c.snap_arm_y]
    return out


def snap_dims(c: CollectorParams) -> dict:
    """The clip in its local frame: u outward from the window edge, v along it, s from the flange face (+ toward the fan)."""
    cd = c.snap_catch_depth+c.snap_catch_gap; ua = -c.snap_clearance; t = c.snap_arm_thickness; d = c.snap_barb
    s_root = -cd+c.snap_arm_length; s_top = s_root+c.snap_base_length
    rel = np.radians(c.snap_release_deg); lead = np.radians(c.snap_lead_deg)
    s_rel = -cd+ua/np.tan(rel)*-1.0      # the catch face passes through (u 0, s -cd)
    ub = ua+d; s_b = -cd-(ub/np.tan(rel)); s_flat = s_b-.3; s_tip = s_flat-d/np.tan(lead)
    prof = [(ua-t, s_tip+.4), (ua-t+.4, s_tip), (ua, s_tip), (ub, s_flat), (ub, s_b), (ua, s_rel), (ua, s_top), (ua-t, s_top)]
    n, dep = c.snap_tenon; w = n+dep/np.tan(np.radians(c.snap_tenon_flank_deg))   # the arm: as wide as the tenon's far end
    return dict(profile=prof, catch_s=-cd, root_s=s_root, top_s=s_top, tip_s=s_tip, u_arm=(ua-t, ua), barb_u=ub, width=w, neck=n, depth=dep)


def _snap_local(c: CollectorParams, grow: float = 0.0, s_lo=None, s_hi=None) -> tuple[mf.Manifold, mf.Manifold]:
    """(arm + barb, tenon) of one clip in the local frame; grow: the tenon grown by this (the slot)."""
    k = snap_dims(c); w = k['width']; n, dep = k['neck'], k['depth']; ua = k['u_arm'][1]
    prof = Polygon(k['profile']); prof = orient(prof, 1)
    arm = mf.Manifold.extrude(_cs(prof), w).translate([0, 0, -w/2])                   # (u, s, v)
    arm = arm.transform(np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0]], dtype=float))   # -> (u, v, s)
    g = grow   # half dovetail: flat along -v (the print bed), one flank widening toward +v (it faces up in print)
    tra = Polygon([(ua-.05-g, -w/2-g), (ua+dep+g, -w/2-g), (ua+dep+g, w/2+g), (ua-.05-g, -w/2+n+g)])
    lo = k['root_s'] if s_lo is None else s_lo; hi = k['top_s'] if s_hi is None else s_hi
    return arm, _extrude(tra, lo, hi-lo)


def _place(c: CollectorParams, m: mf.Manifold, site: dict) -> mf.Manifold:
    if site['out'] < 0: m = m.mirror([1, 0, 0])
    return m.translate([site['edge_x'], site['y'], c.inlet_z])


def snap_clip(c: CollectorParams) -> mf.Manifold:
    """One clip in print orientation: lying on its side (v up), so the layers run along the arm."""
    arm, tenon = _snap_local(c); m = union(arm, tenon)
    m = m.transform(np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0]], dtype=float))   # (u, s, v): v up
    b = m.bounding_box(); return m.translate([-b[0], -b[1], -b[2]])


def snap_clips(c: CollectorParams) -> mf.Manifold:
    """Every clip in place (collector frame)."""
    arm, tenon = _snap_local(c); one = union(arm, tenon)
    return union(*[_place(c, one, st) for st in snap_sites(c)])


def snap_posts(c: CollectorParams) -> tuple[list[mf.Manifold], list[mf.Manifold]]:
    """(post regions, slots), collector frame: each post fills the mouth corner beside its arm, outboard of the window edge
    (over the bracket plate: no flow there), from the flange face to the clip's top, out to the plenum wall (intersect with
    the air); its dovetail slot holds the clip's tenon from the slot floor (the clamp; open at the top: the clip goes in
    from the plenum side and is glued)."""
    k = snap_dims(c); w = k['width']; wall = 1.6; g = c.snap_slot_clearance
    post = _extrude(box(0.0, -(w/2+g+wall), 30.0, w/2+g+wall), -1.0, k['top_s']+1.0)   # below the flange face: clipped by the air
    _, slot = _snap_local(c, grow=g, s_lo=k['root_s'], s_hi=k['top_s']+1)
    return [_place(c, post, st) for st in snap_sites(c)], [_place(c, slot, st) for st in snap_sites(c)]


def snap_arm_air(c: CollectorParams) -> list[mf.Manifold]:
    """What each arm takes out of the air in the collector: the arm and its clearance gap to the post (one slab with the
    post, so the air keeps genus 0; the 0.2 mm gap carries no flow)."""
    k = snap_dims(c); w = k['width']
    slab = _extrude(box(k['u_arm'][0], -w/2, .5, w/2), -1.0, k['top_s']+1.0)
    return [_place(c, slab, st) for st in snap_sites(c)]


def snap_arm_footprints(c: CollectorParams) -> list[Polygon]:
    """Each arm's footprint on the panel (xy), with its 0.2 mm gap: the window area it blocks by design."""
    k = snap_dims(c); w = k['width']; out = []
    for st in snap_sites(c):
        u0, u1 = k['u_arm'][0], 0.0
        x0, x1 = sorted((st['edge_x']+st['out']*u0, st['edge_x']+st['out']*u1))
        out.append(box(x0, st['y']-w/2, x1, st['y']+w/2))
    return out


def snap_numbers(c: CollectorParams, E: dict = None, mu: float = .3, allow: dict = None) -> dict:
    """Cantilever estimates per arm (rectangular section, tip deflection = barb depth): root strain, deflection force,
    insertion and pull-off force (Bayer's wedge relation), and the window area the arms block."""
    E = E or {'PETG': 2000.0, 'ASA': 1900.0}; allow = allow or {'PETG': .025, 'ASA': .02}
    t, w, L, d = c.snap_arm_thickness, snap_dims(c)['width'], c.snap_arm_length, c.snap_barb
    eps = 1.5*t*d/L**2; I = w*t**3/12
    wedge = lambda a: (mu+np.tan(np.radians(a)))/(1-mu*np.tan(np.radians(a)))  # noqa: E731
    n = len(snap_sites(c)); out = dict(arms=n, root_strain=round(eps, 4), allowable_strain=allow, mu=mu)
    for mat, e in E.items():
        P = 3*e*I*d/L**3
        out[mat] = dict(E_MPa=e, deflection_force_N=round(P, 2), insertion_N_per_arm=round(P*wedge(c.snap_lead_deg), 1),
                        pull_off_N_per_arm=round(P*wedge(c.snap_release_deg), 1), insertion_N_total=round(n*P*wedge(c.snap_lead_deg), 1),
                        pull_off_N_total=round(n*P*wedge(c.snap_release_deg), 1), strain_ok=bool(eps <= allow[mat]))
    wins = c.vent_rects or card_windows(c)   # the live strips (window x chassis opening)
    live = shapely.unary_union([box(v[0], v[2], v[1], v[3]) for v in wins])
    arms = shapely.unary_union(snap_arm_footprints(c))   # arm + its clearance gap
    out.update(window_live_area_mm2=round(live.area, 1), blocked_mm2=round(arms.intersection(live).area, 1),
               blocked_fraction=round(arms.intersection(live).area/live.area, 4), note='blocked: arm and its 0.2 mm gap to the window edge')
    return out


def split_end(c: CollectorParams) -> float:
    """Distance from the bracket plane where the splitter fin stops (fin_end below the fan plate)."""
    return c.plenum_depth-c.fan_plate_thickness-c.fin_end


def web_x(c: CollectorParams) -> float:
    """The splitter fin's centre line: midway between the two mouths (over the middle slot)."""
    a, b = card_mouths(c); return (a[1]+b[0])/2


def _disc_start(c: CollectorParams) -> float:
    """Radius about the fan axis that clears both mouths (the rounding disc starts there)."""
    ax, ay = c.fan_axis; r = c.window_corner_radius; (x0, _, y0, y1), (_, x1, _, _) = card_mouths(c)
    return np.hypot(max(abs(x0+r-ax), abs(x1-r-ax)), max(abs(y0+r-ay), abs(y1-r-ay)))+r+.5+c.lip


def split_top(c: CollectorParams, s: float) -> float:
    """Top edge of the split plenum at s: from the mouth top it dips by top_dip[0] within top_dip[1] above the flange
    (the slot-screw tips stand 3.8-7.3 mm out from the panel), holds until top_dip[2], then rises to the bore."""
    y1 = c.window_y[1]; dip, s_dip, s_hold = c.top_dip; tf = c.flange_thickness; se = c.plenum_depth-c.fan_plate_thickness
    if s <= s_hold: return y1-dip*ramp(min(max(s-tf, 0.)/s_dip, 1.), .3)
    return y1-dip+(c.fan_axis[1]+c.fan_radius-(y1-dip))*ramp((s-s_hold)/(se-s_hold), c.top_rise_ease)


def split_section(c: CollectorParams, s: float) -> Polygon:
    """Plenum section at s >= flange_thickness: a rounded rectangle spanning both card mouths, lofting to the bore and
    intersected with a disc about the fan axis that shrinks onto it; every boundary moves at about 45 deg or less."""
    (x0, _, y0, _), (_, x1, _, _) = card_mouths(c); R = c.fan_radius; ax, ay = c.fan_axis
    tf = c.flange_thickness; se = c.plenum_depth-c.fan_plate_thickness
    t = min(max(s-tf, 0.)/(se-tf), 1.); u = ramp(t, c.ease_ramp)
    if c.lip or c.mouth_corners:   # v4: the inlet lip on the sides and bottom; per-corner radii growing to corner_end
        o = lip_offset(c, s); x0, x1, y0 = x0-o, x1+o, y0-o
        xa, xb, ya, yb = x0+(ax-R-x0)*u, x1+(ax+R-x1)*u, y0+(ay-R-y0)*u, split_top(c, s)
        g = ramp(min(t/c.corner_reach, 1.), c.ease_ramp); ms = mouth_radii(c)
        r0 = (ms[0][0], ms[-1][1], ms[-1][2], ms[0][3])           # the envelope's outer corners: bl, br, tr, tl
        rect = _rrect(xa, xb, ya, yb, tuple(r+(max(c.corner_end, r)-r)*g for r in r0))
    else:
        xa, xb, ya, yb = x0+(ax-R-x0)*u, x1+(ax+R-x1)*u, y0+(ay-R-y0)*u, split_top(c, s)
        r0 = c.window_corner_radius; ro = r0+(8.-r0)*u
        rect = _rrect(xa, xb, ya, yb, (ro,)*4)
    if t <= 0: return rect
    Rc0 = _disc_start(c); return rect.intersection(Point(ax, ay).buffer(Rc0-(Rc0-R)*u, quad_segs=256))


def _ring_loft(polys_z, n):
    th = (np.arange(n)+.5)*2*np.pi/n; rings = []
    for p, z in polys_z:
        ctr = np.asarray(p.centroid.coords[0]); r = _reach(p.exterior, ctr, th)
        rings.append(np.c_[ctr+r[:, None]*np.c_[np.cos(th), np.sin(th)], np.full(n, z)])
    return solid_rings(rings)


FIN_END_GAP = 2.0   # the splitter fin's ends stay this far off the plenum's top and bottom walls (no T-junction)


def _split_air(c: CollectorParams, n, extend) -> mf.Manifold:
    """Per-card mouths through the flange, then one plenum lofting to the bore and straight through the fan plate."""
    z0 = c.inlet_z; tf = c.flange_thickness; D = c.plenum_depth; se = D-c.fan_plate_thickness
    ss = np.r_[np.linspace(tf, se, max(12, int((se-tf)/.4))+1), D+extend]
    body = _ring_loft([(split_section(c, min(v, se)), z0+v) for v in ss], n)
    return union(*_mouth_air(c, extend), body)


def splitter_fin(c: CollectorParams) -> mf.Manifold:
    """The 1.2 mm (fin_thickness) fin between the two cards' halves of the plenum: standing on the flange web over the middle
    slot, up to split_end, its ends FIN_END_GAP off the plenum walls (sloping with them)."""
    from shapely.geometry import LineString
    z0 = c.inlet_z; tf = c.flange_thickness; wx = web_x(c); ss = np.linspace(tf, split_end(c), 60); lo, hi = [], []
    for v in ss:
        seg = split_section(c, v).intersection(LineString([(wx, -300), (wx, 300)]))
        lo.append(seg.bounds[1]+FIN_END_GAP); hi.append(seg.bounds[3]-FIN_END_GAP)
    zz = z0+ss; zz[0] -= .5                                                 # rooted 0.5 mm into the flange web
    outline = Polygon([*zip(lo, zz), *zip(hi[::-1], zz[::-1])])            # (y, z)
    m = mf.Manifold.extrude(_cs(outline), c.fin_thickness)
    return m.transform(np.array([[0, 0, 1, wx-c.fin_thickness/2], [1, 0, 0, 0], [0, 1, 0, 0]], dtype=float))


def bare_fan_air(c: CollectorParams, centre_y=None, gap=2.0) -> tuple[mf.Manifold, dict]:
    """CFD baseline, not a part: the pull fan's frame gasketed straight onto the rear panel, no plenum. The air between the
    bracket plane (z = inlet_z) and the fan intake `gap` mm out (0.8 mm panel + ~1.2 mm gasket) inside the frame's
    116 mm gasket square; the intake face is the 117 mm bore. The frame must clear the slot-screw tips and the ledge
    (frame top <= y 45.5), so by default the fan sits at y = 45.5 - 60."""
    ay = 45.5-c.fan_size/2 if centre_y is None else centre_y; ax = c.fan_axis[0]
    foot = Polygon(rounded_rect(58., 58., 8., (ax, ay), 256))
    air = _extrude(foot, c.inlet_z, gap)
    return air, dict(fan_axis=(ax, ay), fan_face_z=c.inlet_z+gap, footprint_mm=list(foot.bounds), bore_radius=c.fan_radius,
                     frame_bottom_y=ay-c.fan_size/2)


def kernel(radius, segments):
    """Sphere scaled so its inradius (not circumradius) is `radius`: the dilation never thins the wall."""
    k = mf.Manifold.sphere(1., int(segments)); raw = k.to_mesh64()
    kv = np.asarray(raw.vert_properties)[:, :3]; kt = kv[np.asarray(raw.tri_verts)]
    kn = np.cross(kt[:, 1]-kt[:, 0], kt[:, 2]-kt[:, 0]); kn /= np.linalg.norm(kn, axis=1)[:, None]
    return k.scale([radius/np.min(np.einsum('ij,ij->i', kn, kt[:, 0]))]*3)


# 2-D layout (shapely, duct x/y)

def window_polygon(c: CollectorParams) -> Polygon:
    if c.split:
        return shapely.unary_union([_rrect(*m, rr) for m, rr in zip(mouths(c), mouth_radii(c))])
    (x0, x1), (y0, y1) = c.window_x, c.window_y
    return Polygon(rounded_rect((x1-x0)/2, (y1-y0)/2, c.window_corner_radius, window_centre(c), 256))


def outer_slots(c: CollectorParams) -> list[tuple[float, float, float, float]]:
    """The chassis openings of the slots just outside the collector's span (one each side): open in the author's case."""
    ops = sorted(c.openings); p = c.slot_pitch
    return [(ops[0][0]-p, ops[0][1]-p, *ops[0][2:]), (ops[-1][0]+p, ops[-1][1]+p, *ops[-1][2:])]


def slot_windows(c: CollectorParams) -> list[Polygon]:
    """flange_mode 'windowed': a cutout over each outer open slot (the layout's outermost slots), opening + slot_window_margin."""
    if c.flange_mode != 'windowed': return []
    m = c.slot_window_margin
    return [_rrect(o[0]-m, o[1]+m, o[2]-m, o[3]+m, (c.slot_window_radius,)*4) for o in outer_slots(c)]


def flange_outline(c: CollectorParams) -> Polygon:
    """The flange on the rear panel: window +- flange_overlap ('overlap'), or ('windowed') flange_reach_x past the outer
    open slots in x, with a window over each (holes)."""
    if c.flange_mode == 'plug':   # the plug fills the recessed bay: its outline is the recess less a clearance
        xa, xb, ya, yb, r = c.plug_outline
        return box(xa+r, ya+r, xb-r, yb-r).buffer(r, quad_segs=64)
    (x0, x1), (y0, y1) = c.window_x, c.window_y; ox, oym, oyp = c.flange_overlap
    xa, xb, ya, yb = x0-ox, x1+ox, y0-oym, y1+oyp
    if c.flange_mode == 'windowed':
        ops = outer_slots(c); xa, xb = ops[0][0]-c.flange_reach_x, ops[-1][1]+c.flange_reach_x
    f = Polygon(rounded_rect((xb-xa)/2, (yb-ya)/2, c.flange_corner_radius, ((xa+xb)/2, (ya+yb)/2), 256))
    for w in slot_windows(c): f = f.difference(w)
    return f


def plug_pockets(c: CollectorParams) -> Polygon:
    """flange_mode 'plug' with plug_pocket_skin: where the plug is hollowed, open at its top (the border plane): inside its
    outline less a wall, clear of the body's footprint on the plug top (plenum + wall + fillet + a wall), corners rounded."""
    if not (c.flange_mode == 'plug' and c.plug_pocket_skin): return Polygon()
    w = c.wall; f = max(c.flange_fillet, c.flange_fillet_top); tf = c.flange_thickness
    foot = shapely.unary_union([split_section(c, tf+d) for d in (0.0, f)]).buffer(w+f+w, quad_segs=16)
    r = 2.0; return flange_outline(c).buffer(-w-r).difference(foot.buffer(r)).buffer(r, quad_segs=8)


def plate_outline(c: CollectorParams) -> Polygon:
    return Polygon(rounded_rect(c.fan_size/2, c.fan_size/2, c.fan_plate_corner_radius, c.fan_axis, 256))


def gasket_loops(c: CollectorParams) -> list[Polygon]:
    """The region inside each gasket groove's inner edge (one loop; split: one per card)."""
    if not c.split: return [window_polygon(c).buffer(c.gasket_lip, quad_segs=32)]
    lp = c.gasket_lip; lt = lp if c.gasket_lip_top < 0 else c.gasket_lip_top; r = c.window_corner_radius+lp
    return [_rrect(x0-lp, x1+lp, y0-lp, y1+lt, (r,)*4) for x0, x1, y0, y1 in card_mouths(c)]


def gasket_ring(c: CollectorParams) -> Polygon:
    if c.flange_mode == 'plug': return Polygon()   # the plug's foam is glued flat on its face, channel roofs and top side
    if c.split: return shapely.unary_union([p.buffer(c.gasket_width, quad_segs=32).difference(p) for p in gasket_loops(c)])
    w = window_polygon(c)
    return w.buffer(c.gasket_lip+c.gasket_width, quad_segs=32).difference(w.buffer(c.gasket_lip, quad_segs=32))


def fan_holes(c: CollectorParams) -> list[tuple[float, float]]:
    cx, cy = c.fan_axis; h = c.fan_hole_offset
    return [(cx+sx*h, cy+sy*h) for sx in (-1, 1) for sy in (-1, 1)]


def mount_points(c: CollectorParams, mount=None) -> list[tuple[float, float]]:
    """On both x bands: magnet pockets just outside the gasket groove; screw slots far enough out for a thumb-screw head."""
    if (mount or c.mount) == 'snap': return []
    if c.magnet_columns_y and (mount or c.mount) == 'magnets':   # windowed: on flush steel beyond each outer open slot, and below
        ops = outer_slots(c); xs = (ops[0][0]-c.magnet_column_dx, ops[-1][1]+c.magnet_column_dx)
        return [(x, y) for x in xs for y in c.magnet_columns_y]+[(x, c.magnet_row_y) for x in c.magnet_row_x]
    (x0, x1), cy = c.window_x, window_centre(c)[1]
    d = c.gasket_lip+c.gasket_width+.8+c.magnet_diameter/2+c.magnet_clearance if (mount or c.mount) == 'magnets' else c.screw_offset
    return [(x, cy+y) for x in (x0-d, x1+d) for y in c.mount_y]


def screw_slot(c: CollectorParams, p) -> Polygon:
    h = (c.screw_slot_length-c.screw_slot_width)/2
    return LineString([(p[0], p[1]-h), (p[0], p[1]+h)]).buffer(c.screw_slot_width/2, quad_segs=16)


def magnet_pocket(c: CollectorParams, p) -> Polygon:
    return Point(p).buffer(c.magnet_diameter/2+c.magnet_clearance, quad_segs=32)


def cable_notch(c: CollectorParams) -> Polygon:
    """U-notch through an x-side flange band, from the flange edge to 1.2 mm outside the gasket groove (none: empty)."""
    if not c.cable_notch: return Polygon()
    side, y, w = c.cable_notch; f = flange_outline(c).bounds; y += window_centre(c)[1]; r = w/2
    x_in = (c.window_x[1] if side > 0 else -c.window_x[0])+c.gasket_lip+c.gasket_width+1.2
    x_out = (f[2] if side > 0 else -f[0])+5
    u = box(x_in+r, y-r, x_out, y+r).union(Point(x_in+r, y).buffer(r, quad_segs=16))
    return u if side > 0 else shapely.affinity.scale(u, -1, 1, origin=(0, 0))


def _cs(poly) -> mf.CrossSection:
    polys = [poly] if poly.geom_type == 'Polygon' else list(poly.geoms)
    loops = []
    for p in polys:
        p = orient(p, 1)
        loops += [np.asarray(p.exterior.coords)[:-1]]+[np.asarray(r.coords)[:-1] for r in p.interiors]
    return mf.CrossSection(loops, mf.FillRule.EvenOdd)


def _extrude(poly, z, depth) -> mf.Manifold:
    return mf.Manifold.extrude(_cs(poly), depth).translate([0, 0, z])


def _reach(boundary, ctr, th):
    """Furthest intersection of a 2-D boundary with each ray from ctr."""
    rays = shapely.linestrings(np.stack([np.tile(ctr, (len(th), 1)), np.asarray(ctr)+400*np.c_[np.cos(th), np.sin(th)]], axis=1))
    pts, idx = shapely.get_coordinates(shapely.intersection(boundary, rays), return_index=True)
    out = np.zeros(len(th)); np.maximum.at(out, idx, np.linalg.norm(pts-np.asarray(ctr), axis=1))
    return out


def _solid_reach(solid, z, ctr, th):
    rim = Polygon(max(solid.slice(float(z)).to_polygons(), key=lambda q: abs(Polygon(q).area))).boundary
    return _reach(rim, ctr, th)


def _near_reach(boundary, ctr, th, rmin):
    """Nearest intersection of a 2-D boundary with each ray from ctr beyond rmin (per ray); inf where there is none."""
    rays = shapely.linestrings(np.stack([np.tile(ctr, (len(th), 1)), np.asarray(ctr)+400*np.c_[np.cos(th), np.sin(th)]], axis=1))
    pts, idx = shapely.get_coordinates(shapely.intersection(boundary, rays), return_index=True)
    d = np.linalg.norm(pts-np.asarray(ctr), axis=1); out = np.full(len(th), np.inf); ok = d > rmin[idx]
    np.minimum.at(out, idx[ok], d[ok])
    return out


def _opening(v, k):
    """Periodic lower envelope: a running minimum then a running mean, both over 2k+1 samples (<= v, continuous)."""
    n = len(v); idx = (np.arange(n)[:, None]+np.arange(-k, k+1)[None, :]) % n
    m = v[idx].min(1); return m[idx].mean(1)


def _flange(c: CollectorParams, z0) -> mf.Manifold:
    """The flange slab (with its slot windows); flange_top_round rounds its outer top edge (stacked offsets, 0.1 mm steps).
    The window edges stay square: the strip above each window is only ~1.4 mm wide."""
    f = flange_outline(c); tf = c.flange_thickness; r = c.flange_top_round
    if not r: return _extrude(f, z0, tf)
    ext = Polygon(f.exterior); holes = [Polygon(h) for h in f.interiors]
    n = max(3, int(np.ceil(r/.1))); parts = [_extrude(ext, z0, tf-r)]
    for k in range(n):
        h = (k+1)*r/n; inset = r-np.sqrt(max(r*r-h*h, 0.))
        parts.append(_extrude(ext.buffer(-inset, quad_segs=16), z0+tf-r+k*r/n, r/n+(1e-3 if k < n-1 else 0)))
    slab = union(*parts)
    return slab-_extrude(shapely.unary_union(holes), z0-.1, tf+.2) if holes else slab


def section(solid, z):
    """Shapely section of a manifold at height z (holes as holes)."""
    p = shapely.geometry.GeometryCollection()
    for ring in solid.slice(float(z)).to_polygons(): p = p.symmetric_difference(Polygon(ring))
    return p


def _base_fillet(c: CollectorParams, outer, z_base) -> mf.Manifold:
    """Concave quarter-round between the body and the flange top (V24's flange fillet, rising from the flange)."""
    R = c.flange_fillet; ctr = np.asarray(c.fan_axis)
    th = np.linspace(0, 2*np.pi, 1440, endpoint=False); cs = np.c_[np.cos(th), np.sin(th)]
    f = flange_outline(c); edge = _reach(f.exterior, ctr, th)
    zs = z_base+np.linspace(0, R, 9)
    body = np.array([_solid_reach(outer, z, ctr, th) for z in zs])
    if c.flange_mode == 'windowed' or c.flange_fillet_top >= 0:   # v4: stop short of the windows and the top round; smaller on +y
        for hole in f.interiors: edge = np.minimum(edge, _near_reach(hole, ctr, th, body[0]))
        edge = _opening(edge-c.flange_top_round, 16)
        Rt = R if c.flange_fillet_top < 0 else c.flange_fillet_top; yb = ctr[1]+body[0]*cs[:, 1]
        Rth = Rt+(R-Rt)*(1-smooth01((yb-(c.window_y[1]-12.))/8.))
        Rk = np.maximum(Rth*smooth01((edge-body[0])/(1.5*Rth)), .3)
    else:
        Rk = np.maximum(R*smooth01((edge-body[0])/(1.5*R)), .3)
    rings = []
    for u in np.linspace(0, 1, 17):
        z = z_base+u*Rk
        rb = np.array([np.interp(zk, zs, body[:, k]) for k, zk in enumerate(z)])
        rad = np.minimum(rb+Rk*(1-np.sqrt(1-(1-u)**2))-.05*u, edge)
        rings.append(np.c_[ctr+rad[:, None]*cs, z])
    return solid_rings([rings[0]*[1, 1, 0]+[0, 0, z_base-.2]]+rings, ctr)


def _ear_supports(c: CollectorParams, z_top) -> mf.Manifold:
    """The fan-plate outline shrunk inward with depth below the plate: a chamfer under each corner ear."""
    ctr = np.asarray(c.fan_axis); th = (np.arange(720)+.5)*2*np.pi/720; cs = np.c_[np.cos(th), np.sin(th)]
    k = np.tan(np.radians(c.ear_support_angle)); depth = c.fan_size/2*.4
    rings = []
    for d in np.linspace(depth, 0, 25):
        r = _reach(plate_outline(c).buffer(-d*k, quad_segs=32).exterior, ctr, th)
        rings.append(np.c_[ctr+r[:, None]*cs, np.full(len(th), z_top-d)])
    return solid_rings(rings, ctr)


def magnet_boss(c: CollectorParams, p, z) -> mf.Manifold:
    """Round puck on the flange back with a rounded top edge, deep enough for the magnet pocket."""
    R = c.magnet_diameter/2+c.magnet_clearance+c.boss_wall; h = c.boss_height; rr = min(1.2, h-c.flange_thickness)
    arc = [(R-rr+rr*np.cos(t), h-rr+rr*np.sin(t)) for t in np.linspace(0, np.pi/2, 9)]
    return mf.Manifold.revolve(mf.CrossSection([np.array([(0, 0), (R, 0), *arc, (0, h)])]), 96).translate([p[0], p[1], z])


def build_fit_gauge(c: CollectorParams) -> mf.Manifold:
    """Flat 1 mm outline of the flange footprint as it meets the case: flange edge, window edge, the derived
    chassis-opening edges (ticks), fan-plate outline and screw holes, hub circle, both mount patterns, cable notch, +y arrow."""
    w = c.gauge_line; ctr = np.asarray(c.fan_axis)
    win = window_polygon(c); flange = flange_outline(c); plate = plate_outline(c)
    ring = lambda p, t: p.difference(p.buffer(-t, quad_segs=16))  # noqa: E731
    parts = [ring(flange, w), win.buffer(w, quad_segs=16).difference(win.buffer(-.01))]
    mouths = card_mouths(c) if c.split else []
    for x0, x1, y0, y1 in sorted(c.openings):   # ticks at the derived chassis-opening edges: the real openings should fall between them
        if c.split and not any(m[0] <= x0 and x1 <= m[1] for m in mouths): continue   # an opening under the flange web, between the mouths
        if c.mouth_y: y0, y1 = c.window_y[0]+.5, c.window_y[1]-.5   # the mouth is not the opening: hang the ticks off the window edge
        for x in (x0, x1):
            parts += [box(x-.5, y0-.5, x+.5, y0+6), box(x-.5, y1-6, x+.5, y1+.5)]
    for x0, x1, y0, y1 in c.vent_rects: parts.append(ring(box(x0, y0, x1, y1), .8))   # the bracket vent windows (crossed by the spokes)
    parts.append(ring(plate, 1.2))
    for p in fan_holes(c): parts.append(ring(Point(p).buffer(c.fan_hole_radius+1.4), 1.2))
    parts.append(ring(Point(ctr).buffer(c.fan_hub_diameter/2), 1.0))
    if c.magnet_columns_y:   # magnets only: each ring tied to the flange edge band
        for p in mount_points(c, 'magnets'):
            parts.append(ring(magnet_pocket(c, p).buffer(1.2), 1.2))
            q = shapely.ops.nearest_points(Point(p), flange.boundary)[1]
            parts.append(LineString([p, q]).buffer(.8).difference(magnet_pocket(c, p).buffer(.01)))
    for p, q in [] if c.magnet_columns_y else zip(mount_points(c, 'magnets'), mount_points(c, 'screws')):
        parts.append(ring(magnet_pocket(c, p).buffer(1.2), 1.2))
        parts.append(ring(screw_slot(c, q).buffer(.8), .8))
        parts.append(LineString([p, q]).buffer(.5).difference(screw_slot(c, q)))
    reach = flange.union(plate.buffer(-.6)) if c.fan_y_at_board or c.flange_mode == 'plug' else flange   # a high fan or a plug: pilots past the flange
    for ang in np.arange(4)*np.pi/2+np.pi/4:       # diagonal spokes join everything into one piece
        d = np.array([np.cos(ang), np.sin(ang)])
        parts.append(LineString([ctr+d*(c.fan_hub_diameter/2-.5), ctr+d*300]).buffer(.8).intersection(reach))
    ym = flange.bounds[3]
    if c.gauge_arrow_inside:   # the gauge must slide under the slot ledge: arrow hangs from the window's top edge, inside
        yw = c.window_y[1]
        for xm in ([(m[0]+m[1])/2 for m in card_mouths(c)] if c.split else [ctr[0]]):
            parts.append(Polygon([(xm-5, yw-7), (xm+5, yw-7), (xm, yw+.5)]))
    else: parts.append(Polygon([(ctr[0]-5, ym-w), (ctr[0]+5, ym-w), (ctr[0], ym+6)]))   # +y: card top edge / bracket tab side
    g = shapely.unary_union(parts).difference(cable_notch(c)).buffer(0)
    if c.fan_y_at_board:   # the fan circle and its top pilots reach past the flange's +y edge, into the slot ledge: stop at the edge
        g = g.intersection(box(-400, -400, 400, ym)).buffer(0)
    if c.fan_y_at_board or c.flange_mode == 'plug':   # pieces cut off above the edge (top pilot rings), or a snap plug's unused
        g = max(getattr(g, 'geoms', [g]), key=lambda q: q.area)   # mount rings past its narrow face, drop out
    assert g.geom_type == 'Polygon', (g.geom_type, [[round(v, 1) for v in q.bounds] for q in getattr(g, 'geoms', [])])
    return _extrude(g, 0, c.gauge_thickness)


def build_collector(c: CollectorParams) -> CollectorSolids:
    z0 = c.inlet_z; D = c.plenum_depth; tf = c.flange_thickness; tp = c.fan_plate_thickness
    inner = air_volume(c)
    clips = None
    if c.mount == 'snap':   # posts fill the mouth corners over the bracket plate; the clips' arms stand in the air too
        posts, slots = snap_posts(c); clips = snap_clips(c)
        inner -= union(*posts, *snap_arm_air(c))
    if c.split and c.vane_style == 'v4':
        for _, m, _ in vanes(c): inner -= m
        if c.hub_fairing:   # its cavity, open toward the fan, stays air (dead, behind the hub), the fin cleared from it
            inner -= hub_fairing(c)[0]; inner += hub_fairing_cavity(c)
    elif c.split: inner -= splitter_fin(c)   # the fin stands in the air (CFD sees it); body - inner keeps it in the part
    assert inner.status() == mf.Error.NoError and inner.genus() == 0

    # Uniform shell: dilate the rounded air volume; the plate outline bounds it (as the duct's fan plate does)
    tool = air_volume(c, n=c.loft_points//2, extend=2*c.wall).simplify(c.shell_simplify)
    outer = tool.minkowski_sum(kernel(c.wall, c.kernel_segments))
    clip = plate_outline(c).union(Polygon(flange_outline(c).exterior)) if c.fan_dy else plate_outline(c)   # a low fan: the mouth top is above the plate
    outer = outer^_extrude(clip, z0, D)

    flange = _flange(c, z0)
    plate = _extrude(plate_outline(c), z0+D-tp, tp)
    bosses = [magnet_boss(c, p, z0) for p in mount_points(c)] if c.mount == 'magnets' else []
    body = union(outer, flange, _base_fillet(c, outer, z0+tf), plate, _ear_supports(c, z0+D-tp), *bosses)
    body = body.trim_by_plane([0, 0, 1], z0).trim_by_plane([0, 0, -1], -(z0+D))
    final = body-inner

    if not gasket_ring(c).is_empty: final -= _extrude(gasket_ring(c), z0-.1, c.gasket_depth+.1)
    if c.plug_channels:   # the plug face straddles the divider bars: a channel over each, its roof on the bar's crown (foam)
        final -= _extrude(shapely.unary_union([box(x0, y0, x1, y1) for x0, x1, y0, y1 in c.plug_channels]), z0-.1, c.plug_channel_depth+.1)
    if not plug_pockets(c).is_empty:   # hollow plug: pockets open toward the fan side, over a face skin
        final -= _extrude(plug_pockets(c), z0+c.plug_pocket_skin, tf-c.plug_pocket_skin+.1)
    for hx, hy in fan_holes(c):   # pilots through the plate and the ear chamfer below it
        if c.pilot_depth:   # blind, inside the ear chamfer: it never breaks out of the chamfer's underside
            pilot = mf.Manifold.cylinder(c.pilot_depth+1, c.fan_hole_radius, circular_segments=48).translate([hx, hy, z0+D-c.pilot_depth])
        else: pilot = mf.Manifold.cylinder(D, c.fan_hole_radius, circular_segments=48).translate([hx, hy, z0+tf+.4])
        final -= pilot-outer if c.fan_dy else pilot   # a low fan puts the top pilots beside the mouth: keep its wall
    mounts = mount_points(c); flange_poly = flange_outline(c)
    for p in mounts:   # every pocket or slot stays inside the flange, clear of the gasket groove and the cable notch
        hole = (magnet_pocket(c, p) if c.mount == 'magnets' else screw_slot(c, p)).buffer(.8)
        outline = magnet_pocket(c, p).buffer(c.boss_wall) if c.mount == 'magnets' else hole
        assert flange_poly.contains(outline) and not hole.intersects(gasket_ring(c)) and not outline.intersects(cable_notch(c)), p
    for p in mounts:
        if c.mount == 'magnets':
            final -= _extrude(magnet_pocket(c, p), z0-.1, c.magnet_thickness+.2+.1)
        else:
            final -= _extrude(screw_slot(c, p), z0-.1, tf+.2)
    if c.cable_notch: final -= _extrude(cable_notch(c), z0-.1, tf+.2)
    if c.mount == 'snap': final -= union(*slots, *snap_arm_air(c))   # room for the clips (they block that air in the CFD)
    final = final.as_original()

    if c.mount == 'screws':   # each thumb-screw head sits on the bare flange, clear of body and fillet
        for p in mounts:
            head = Point(p).buffer(c.thumb_head_diameter/2)
            for z in np.linspace(z0+tf+.05, z0+tf+c.thumb_head_height, 6):
                sec = section(final, z)
                assert sec.intersection(head).area < 1e-3, ('thumb-screw head hits the body', p, z)

    sections = []
    for s in np.linspace(0, D, 51) if c.split else ():
        a = (window_polygon(c).area if s < tf else split_section(c, min(s, D-tp)).area)
        sections.append(dict(s_mm=float(s), z_mm=float(z0+s), area_mm2=float(a)))
    for s in () if c.split else np.linspace(0, D, 51):
        a, b, r = section_at(c, min(s, D-tp))
        sections.append(dict(s_mm=float(s), z_mm=float(z0+s), half_width_x_mm=float(a), half_width_y_mm=float(b), corner_radius_mm=float(r),
                             area_mm2=float(4*a*b-(4-np.pi)*r*r)))
    features = dict(mount=c.mount, mount_points=mounts, fan_holes=fan_holes(c), cable_notch_bounds=list(cable_notch(c).bounds) if c.cable_notch else None,
                    slot_windows=[list(w.bounds) for w in slot_windows(c)])
    if clips is not None: features['snap'] = dict(sites=snap_sites(c), dims={k: v for k, v in snap_dims(c).items() if k != 'profile'})
    return CollectorSolids(c, inner, final, build_fit_gauge(c), sections, features, clips)
