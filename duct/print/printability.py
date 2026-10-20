"""Deterministic printability and seal gates for an STL printed as exported (z up, first layer on z = 0).

Every geometric gate slices the serialized mesh (manifold3d `Manifold.slice`, Clipper2 offsets), so it judges what the
slicer receives. Each gate returns a GateResult: pass/fail against `Thresholds`, numbers, and xyz locations (mm) of
every finding. Findings inside an explicitly named `Allowed` region are reported separately with the reason they are
intended; nothing is waved through by a loose threshold.

- unsupported_overhang: per layer, area not supported by the layer below grown by layer_h * tan(45 deg) (50/55/60 deg
  reported), each island's angle from its reach beyond the layer below; a second pass on the slicer's own layer stack
  catches small tips steeper than the slicer's support angle; floating islands.
- solid_regions: material where a ball of diameter solid_k * wall fits (per layer, from the neighbouring sections), i.e.
  regions thicker than the shell that the slicer fills solid. A sloped wall of nominal thickness never fits the ball, so
  only real lumps count, however wide their horizontal section looks.
- seal: (a) per layer, every enclosed void of the section is a designed opening; (b) in 3-D (voxels), with the conduit's
  end openings capped, the passage does not reach the outside, and there are no enclosed voids.
- slicer_support: the real slicer (Bambu Studio CLI) with automatic supports; support extrusions read from the G-code.
- seat_coverage: at each seat plane (z = seat - seat_eps), the card face that must be sealed (a region of the spec, e.g. the
  bore over the fin stack) is covered by material, by the passage's own opening, or by a named allowed opening. An exposed
  patch is the open end of fin channels that the passage pressurizes: a leak (V27's pocket corners). The allowed openings
  are the connector's envelope plus a print clearance, and what they leave open (beyond the footprint that the mounted
  connector housing itself covers) has a per-seat budget, max_seat_open_mm2 (V28's 3 x 8.6 mm latch notch exceeds it).
"""
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import manifold3d as mf
import numpy as np
import shapely
import trimesh
from shapely.geometry import MultiPolygon, Point, Polygon, box

ROUND = mf.JoinType.Round


@dataclass(frozen=True)
class Thresholds:
    layer_h: float = 0.2                  # slice pitch of the geometric gates (the duct prints at 0.2-0.28 mm)
    overhang_deg: float = 45.0            # tier A: layer k may reach layer_h * tan(45 deg) beyond layer k-1 ...
    max_overhang_island_mm2: float = .25  # ... an island beyond that larger than this fails
    cantilever_deg: float = 60.0          # tier B, on the slicer's layer stack: an island whose reach beyond the layer
    cantilever_min_mm2: float = .002      # below is steeper than this, at least this large, fails. Bambu supports from
    slicer_first_layer: float = .2        # support_threshold_angle 30 deg (from horizontal), however small the region
    slicer_layer_h: float = .28           # (V25's return tip); profiles/slicer/process-028.json
    report_deg: tuple[float, ...] = (45.0, 50.0, 55.0, 60.0)
    overhang_eps: float = .02             # mm added to the allowed reach: facet chords and float32 vertices
    noise_mm2: float = .001               # islands below this are numerical slivers
    solid_k: float = 4/3                  # solid: a ball of diameter solid_k * wall fits (1.2 mm wall: 1.6 mm)
    max_solid_island_mm2: float = 1.0     # a solid island (outside the allowlist) larger than this fails
    hole_noise_mm2: float = .005          # enclosed section voids below this are slivers
    voxel: float = .5                     # seal (b) voxel pitch; every wall is >= 1.2 mm, i.e. >= 2 voxels
    cap_grow: float = .6                  # the end-opening caps overlap the rim by this much (< the 1.2 mm wall)
    min_void_mm3: float = 1.0             # seal (b): smaller voxel voids are sampling artifacts of narrow grooves
    support_max_g: float = 0.0            # slicer gate: grams of support material allowed
    seat_eps: float = .001                # seat gate: section this far below the seat plane
    max_seat_uncovered_mm2: float = .5    # seat gate: exposed card face allowed per seat
    max_seat_open_mm2: float = 24.0       # seat gate: card face left open through the allowed openings, per seat (V29: ~21.4)


@dataclass(frozen=True)
class Allowed:
    """A named region in which a finding is intended; `why` justifies it from the geometry.

    xy: the box lo/hi, or `region` (a shapely polygon) when given. Overhang findings are allowed only up to max_deg.
    """
    name: str
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]
    why: str
    max_deg: float = 90.0
    region: object = None

    def active(self, z) -> bool:
        return self.lo[2]-1e-6 <= z <= self.hi[2]+1e-6

    def cross_section(self) -> mf.CrossSection:
        if self.region is None:
            return mf.CrossSection.square([self.hi[0]-self.lo[0], self.hi[1]-self.lo[1]]).translate([self.lo[0], self.lo[1]])
        return _cs(self.region)


@dataclass(frozen=True)
class Opening:
    """A designed enclosed void of a horizontal section: a passage (large), a circular hole at a known centre, or a
    blind recess inside a known region."""
    name: str
    z: tuple[float, float]
    min_area: float = 0.0                 # passage: any void at least this large ...
    max_count: int = 0                    # ... at most this many per layer (0: no limit)
    centres: tuple[tuple[float, float], ...] = ()   # circular hole: centre within `tol` of one of these ...
    radius: float = 0.0                   # ... and no larger than 1.25 pi r^2
    region: object = None                 # recess: the void lies inside this shapely polygon (grown by tol)
    tol: float = .5
    end_opening: bool = False             # an end of the conduit, capped for the 3-D seal check


@dataclass(frozen=True)
class SeatFace:
    """A face that another part seats against and that must be sealed: `region` (shapely, xy) at the plane z, covered by
    material, by an enclosed passage void of the section (an `end_opening`), or by one of `openings`: (name, polygon, why).
    `covers` (name, polygon, why) are covered by the mating part itself (a connector housing on the card face): what the
    openings leave exposed beyond them is the seat's open area, held to max_seat_open_mm2."""
    name: str
    z: float
    region: object
    openings: tuple = ()
    covers: tuple = ()


@dataclass(frozen=True)
class PartSpec:
    """What a part is allowed to have."""
    name: str
    wall: float                           # nominal wall (the 3-D shell dilation)
    overhang_allowed: tuple[Allowed, ...] = ()
    solid_allowed: tuple[Allowed, ...] = ()
    openings: tuple[Opening, ...] = ()
    passage_seeds: tuple[tuple[float, float, float], ...] = ()   # points inside the passage, for seal (b)
    caps: tuple[tuple[float, float], ...] = ()   # seal (b): (section z, cap z): the end-opening voids of the section at
                                                 # `section z`, grown by cap_grow, close the voxel layer at `cap z`
    seats: tuple[SeatFace, ...] = ()      # faces that must be covered (seat_coverage)


@dataclass
class GateResult:
    name: str
    passed: bool
    summary: dict
    failures: list = field(default_factory=list)
    allowed: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


# --------------------------------------------------------------------------------------------------------------------
# Geometry helpers


def load_manifold(stl) -> mf.Manifold:
    m = stl if isinstance(stl, trimesh.Trimesh) else trimesh.load(Path(stl))
    s = mf.Manifold(mf.Mesh(np.asarray(m.vertices, dtype=np.float32), np.asarray(m.faces, dtype=np.uint32)))
    assert s.status() == mf.Error.NoError, s.status()
    return s


def export_stl(solid: mf.Manifold, path):
    raw = solid.to_mesh64()
    trimesh.Trimesh(np.asarray(raw.vert_properties)[:, :3], np.asarray(raw.tri_verts), process=False).export(Path(path))


def layer_z(solid: mf.Manifold, h: float) -> np.ndarray:
    """Mid-layer heights, as a slicer samples them: (k + 1/2) h above the bed."""
    bb = solid.bounding_box()
    assert abs(bb[2]) < 1e-3, f'the part must sit on z = 0 (min z {bb[2]})'
    return (np.arange(int(np.floor(bb[5]/h+1e-9)))+.5)*h


def to_shapely(cs: mf.CrossSection):
    """CrossSection -> (Multi)Polygon with holes."""
    out = []
    for part in cs.decompose():
        rings = [np.asarray(r) for r in part.to_polygons() if len(r) >= 3]
        if not rings: continue
        k = int(np.argmax([abs(Polygon(r).area) for r in rings]))
        out.append(Polygon(rings[k], [r for i, r in enumerate(rings) if i != k]))
    return out[0] if len(out) == 1 else MultiPolygon(out)


def _cs(poly) -> mf.CrossSection:
    rings = []
    for p in getattr(poly, 'geoms', [poly]):
        rings += [np.asarray(p.exterior.coords)[:-1]]+[np.asarray(r.coords)[:-1] for r in p.interiors]
    return mf.CrossSection(rings, mf.FillRule.EvenOdd)


def _island(cs: mf.CrossSection, z: float, **extra) -> dict:
    x0, y0, x1, y1 = cs.bounds()
    c = to_shapely(cs).representative_point()
    return dict(z=round(float(z), 3), area_mm2=round(float(cs.area()), 4), at=[round(c.x, 2), round(c.y, 2), round(float(z), 2)],
                bbox_xy=[round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)], **extra)


def _split_allowed(cs: mf.CrossSection, z: float, allowed, deg: float = 0.0):
    """(unexplained part, [(Allowed, part inside it)]) of a section region."""
    rest = cs; inside = []
    for a in allowed:
        if not a.active(z) or deg > a.max_deg+1e-9: continue
        part = rest ^ a.cross_section()
        if part.area() > 0:
            inside.append((a, part)); rest = rest-a.cross_section()
    return rest, inside


def _clusters(rows, h, gap=1.0, series=False):
    """Group per-layer islands into 3-D features: consecutive layers whose xy boxes overlap (grown by `gap`)."""
    feats = []
    for r in sorted(rows, key=lambda r: (r['z'], r['bbox_xy'])):
        b = r['bbox_xy']; key = r.get('allowed_as')
        for f in feats:
            fb = f['last']
            if (f.get('allowed_as') == key and r['z']-f['z1'] <= 1.5*h+1e-9 and b[0] <= fb[2]+gap and fb[0] <= b[2]+gap
                    and b[1] <= fb[3]+gap and fb[1] <= b[3]+gap):
                break
        else:
            f = dict(z0=r['z'], z1=r['z'], bbox=list(b), last=b, n=0, vol=0.0, max_area=0.0, rows=[], **({'allowed_as': key} if key else {}))
            feats.append(f)
        f['z1'] = r['z']; f['last'] = b; f['n'] += 1; f['vol'] += r['area_mm2']*h; f['rows'].append(r)
        f['bbox'] = [min(f['bbox'][0], b[0]), min(f['bbox'][1], b[1]), max(f['bbox'][2], b[2]), max(f['bbox'][3], b[3])]
        if r['area_mm2'] >= f['max_area']: f['max_area'] = r['area_mm2']; f['worst'] = r
    out = []
    for f in feats:
        b = f['bbox']; w = f['worst']
        row = dict(z_range=[round(f['z0'], 2), round(f['z1'], 2)], bbox_xy=[round(v, 2) for v in b],
                   centre=[round((b[0]+b[2])/2, 2), round((b[1]+b[3])/2, 2), round((f['z0']+f['z1'])/2, 2)],
                   layers=f['n'], max_island_mm2=round(f['max_area'], 4), volume_mm3=round(f['vol'], 3), worst_layer=w['at'])
        for k in ('max_angle_deg', 'reach_mm', 'max_width_mm'):
            vals = [r[k] for r in f['rows'] if k in r]
            if vals: row[k] = max(vals)
        if 'allowed_as' in f: row['allowed_as'] = f['allowed_as']
        if series: row['area_by_layer'] = [[r['z'], r['area_mm2']] for r in f['rows']]
        out.append(row)
    return out


# --------------------------------------------------------------------------------------------------------------------
# Gates


def _reach(island: mf.CrossSection, below: mf.CrossSection, lo: float, span: float = 8.0, tol: float = .005) -> float:
    """Distance from the layer below to the island's furthest point: the least d with island inside below grown by d
    (bisection on Clipper offsets of the layer below, clipped to the island's neighbourhood); at most lo + span."""
    x0, y0, x1, y1 = island.bounds()
    near = below ^ mf.CrossSection.square([x1-x0+2*span, y1-y0+2*span]).translate([x0-span, y0-span])
    a, b = lo, lo+span
    if near.is_empty(): return b
    covered = lambda d: (island-near.offset(d, ROUND, circular_segments=64)).area() < 1e-7  # noqa: E731
    if not covered(b): return b
    while b-a > tol:
        m = (a+b)/2
        a, b = (a, m) if covered(m) else (m, b)
    return b


def _overhang_pass(solid, zs, spec, t, angles, gate_deg):
    """One pass over the layer stack zs: per angle, area beyond the layer below grown by dz * tan(angle); islands beyond
    gate_deg with their reach (furthest point from the layer below) and angle; floating islands."""
    prev = None; z_prev = 0.0; rows = []; ok = []; floating = []
    totals = {a: 0.0 for a in angles}; worst = {a: 0.0 for a in angles}
    for z in zs:
        cur = solid.slice(float(z)); dz = float(z-z_prev)
        if prev is not None and not cur.is_empty():
            for a in angles:
                extra = cur-prev.offset(dz*np.tan(np.radians(a))+t.overhang_eps, ROUND, circular_segments=64)
                area = extra.area(); totals[a] += area*dz; worst[a] = max(worst[a], area)
                if a != gate_deg or area < t.noise_mm2: continue
                for p in extra.decompose():
                    if p.area() < t.noise_mm2: continue
                    r = _reach(p, prev, dz*np.tan(np.radians(a))+t.overhang_eps)
                    deg = round(float(np.degrees(np.arctan2(r, dz))), 1)
                    rest, inside = _split_allowed(p, z, spec.overhang_allowed, deg)
                    ok += [_island(q, z, max_angle_deg=deg, reach_mm=round(float(r), 3), allowed_as=al.name) for al, q in inside]
                    rows += [_island(q, z, max_angle_deg=deg, reach_mm=round(float(r), 3)) for q in rest.decompose() if q.area() >= t.noise_mm2]
            grown = prev.offset(.01, ROUND, circular_segments=16)
            for p in cur.decompose():
                if p.area() >= t.noise_mm2 and (p ^ grown).area() < 1e-6:
                    rest, _ = _split_allowed(p, z, spec.overhang_allowed, 90.0)
                    if rest.area() >= t.noise_mm2: floating.append(_island(p, z))
        prev = cur; z_prev = z
    return rows, ok, floating, totals, worst


def slicer_layers(solid, first=.2, h=.28):
    """Mid-layer heights of the slicer's own stack: a first layer, then constant layers."""
    top = solid.bounding_box()[5]
    return np.r_[first/2, first+(np.arange(int(np.floor((top-first)/h+1e-9)))+.5)*h]


def unsupported_overhang(solid: mf.Manifold, spec: PartSpec, t: Thresholds = Thresholds()) -> GateResult:
    """Layer k minus layer k-1 grown by dz * tan(angle): area that must bridge or needs support.

    Tier A (design rule, layer_h stack): an island beyond overhang_deg larger than max_overhang_island_mm2.
    Tier B (the slicer's rule, on its own first-layer + layer stack): an island whose reach beyond the layer below is
    steeper than cantilever_deg, however small (a tip or ledge the slicer supports).
    Floating islands: regions of a layer that touch nothing of the layer below.
    Allowed regions excuse findings up to their max_deg.
    """
    h = t.layer_h; angles = sorted(set(t.report_deg) | {t.overhang_deg})
    rows, ok, floating, totals, worst = _overhang_pass(solid, layer_z(solid, h), spec, t, angles, t.overhang_deg)
    rows_b, ok_b, _, _, _ = _overhang_pass(solid, slicer_layers(solid, t.slicer_first_layer, t.slicer_layer_h), spec, t,
                                           [t.overhang_deg], t.overhang_deg)
    tier_a = [r for r in rows if r['area_mm2'] > t.max_overhang_island_mm2]
    tier_b = [r for r in rows_b if r['max_angle_deg'] > t.cantilever_deg and r['area_mm2'] >= t.cantilever_min_mm2]
    steep_ok = [r for r in ok_b if r['max_angle_deg'] > t.cantilever_deg]
    summary = dict(layer_h_mm=h, slicer_stack_mm=[t.slicer_first_layer, t.slicer_layer_h],
                   rule=f'tier A ({h} mm layers): island beyond {t.overhang_deg:g} deg > {t.max_overhang_island_mm2} mm2; tier B '
                        f'({t.slicer_layer_h} mm slicer layers): island steeper than {t.cantilever_deg:g} deg >= {t.cantilever_min_mm2} mm2; '
                        f'floating islands',
                   unsupported_volume_mm3={f'{a:g}deg': round(v, 4) for a, v in totals.items()},
                   worst_layer_area_mm2={f'{a:g}deg': round(v, 4) for a, v in worst.items()},
                   tier_a_failures=_clusters(tier_a, h), tier_b_failures=_clusters(tier_b, t.slicer_layer_h),
                   floating_islands=_clusters(floating, h),
                   below_limits=_clusters([r for r in rows if r not in tier_a], h),
                   steepest_slicer_stack=sorted(_clusters([r for r in rows_b if r not in tier_b], t.slicer_layer_h),
                                                key=lambda f: -f['max_angle_deg'])[:6])
    fails = summary['tier_a_failures']+summary['tier_b_failures']+summary['floating_islands']
    return GateResult('unsupported_overhang', not fails, summary, failures=fails, allowed=_clusters(ok, h)+_clusters(steep_ok, t.slicer_layer_h))


def _thick(sections, h, r):
    """Per layer, the part of each section where a ball of radius r fits (3-D opening of the solid by the ball).

    The ball's slice at height offset dz is a disk of radius sqrt(r^2 - dz^2); a centre must lie in every neighbouring
    section eroded by its disk radius, and the opened region is the union of those centres grown back by the disks.
    """
    m = int(np.floor(r/h+1e-9)); offs = range(-m, m+1); rho = {j: np.sqrt(max(r*r-(j*h)**2, 0.0)) for j in offs}
    n = len(sections); cache = {}
    def eroded(k, j):
        if not 0 <= k < n: return mf.CrossSection()
        key = (k, abs(j))
        if key not in cache:
            cache[key] = sections[k].offset(-rho[j], ROUND, circular_segments=48) if rho[j] > 1e-9 else sections[k]
        return cache[key]
    centres = []
    for k in range(n):
        c = sections[k].offset(-r, ROUND, circular_segments=48) if r > 0 else sections[k]
        for j in offs:
            if c.is_empty(): break
            if j: c = c ^ eroded(k+j, j)
        centres.append(c)
    out = []
    for k in range(n):
        parts = [centres[k+j].offset(rho[j], ROUND, circular_segments=48) for j in offs if 0 <= k+j < n and not centres[k+j].is_empty() and rho[j] > 1e-9]
        out.append(mf.CrossSection.batch_boolean(parts, mf.OpType.Add) ^ sections[k] if parts else mf.CrossSection())
    return out


def solid_regions(solid: mf.Manifold, spec: PartSpec, t: Thresholds = Thresholds()) -> GateResult:
    """Material thicker than solid_k * wall in 3-D (a ball of that diameter fits), per layer, outside the allowlist."""
    h = t.layer_h; zs = layer_z(solid, h); r = spec.wall*t.solid_k/2
    sections = [solid.slice(float(z)) for z in zs]
    rows = []; ok = []
    for z, thick in zip(zs, _thick(sections, h, r)):
        if thick.area() < t.noise_mm2: continue
        rest, inside = _split_allowed(thick, z, spec.solid_allowed)
        ok += [_island(q, z, allowed_as=a.name) for a, q in inside if q.area() >= t.noise_mm2]
        rows += [_island(q, z) for q in rest.decompose() if q.area() >= .01]
    fails = [x for x in rows if x['area_mm2'] > t.max_solid_island_mm2]
    feats = _clusters(fails, h, series=True)
    for f in feats:   # the widest horizontal section of each failing feature, for scale
        z = f['worst_layer'][2]; sec = to_shapely(solid.slice(float(z))).intersection(box(*f['bbox_xy']).buffer(.5))
        f['max_width_mm'] = round(2*float(shapely.length(shapely.maximum_inscribed_circle(sec, tolerance=.01))), 2) if not sec.is_empty else None
    allowed = _clusters(ok, h)
    by_name = {}
    for f in allowed: by_name[f['allowed_as']] = round(by_name.get(f['allowed_as'], 0)+f['volume_mm3'], 2)
    summary = dict(layer_h_mm=h, wall_mm=spec.wall, ball_diameter_mm=round(2*r, 3), island_limit_mm2=t.max_solid_island_mm2,
                   unexplained_solid_volume_mm3=round(sum(x['area_mm2'] for x in rows)*h, 2), allowed_solid_volume_mm3=by_name,
                   features=feats, below_limit=_clusters([x for x in rows if x not in fails], h))
    return GateResult('solid_regions', not fails, summary, failures=feats, allowed=allowed)


def _voids(cs: mf.CrossSection, pad=2.0):
    """Enclosed voids of a section: components of (frame - section) that do not touch the frame edge."""
    if cs.is_empty(): return []
    x0, y0, x1, y1 = cs.bounds()
    frame = mf.CrossSection.square([x1-x0+2*pad, y1-y0+2*pad]).translate([x0-pad, y0-pad])
    out = []
    for p in (frame-cs).decompose():
        a, b, c, d = p.bounds()
        if a > x0-pad+1e-6 and b > y0-pad+1e-6 and c < x1+pad-1e-6 and d < y1+pad-1e-6: out.append(p)
    return out


def _match(p: mf.CrossSection, z: float, openings, counts):
    area = p.area(); x0, y0, x1, y1 = p.bounds(); cx, cy = (x0+x1)/2, (y0+y1)/2
    for o in openings:
        if not o.z[0]-1e-6 <= z <= o.z[1]+1e-6: continue
        if o.centres:
            if min(np.hypot(cx-a, cy-b) for a, b in o.centres) <= o.tol and area <= 1.25*np.pi*o.radius**2: return o
        elif o.region is not None:
            if (p-_cs(o.region.buffer(o.tol))).area() < 1e-4: return o
        elif area >= o.min_area and (not o.max_count or counts.get(o.name, 0) < o.max_count): return o
    return None


def _classified_voids(cs, z, spec, t):
    counts = {}; out = []
    for p in sorted(_voids(cs), key=lambda p: -p.area()):
        if p.area() < t.hole_noise_mm2: continue
        o = _match(p, z, spec.openings, counts)
        if o is not None: counts[o.name] = counts.get(o.name, 0)+1
        out.append((p, o))
    return out


def seal(solid: mf.Manifold, spec: PartSpec, t: Thresholds = Thresholds()) -> GateResult:
    """(a) Per layer, every enclosed void of the section is a designed opening. (b) In 3-D, with the conduit's end
    openings capped, the passage does not reach the outside, and there are no enclosed voids."""
    h = t.layer_h; bad = []; ok = {}
    for z in layer_z(solid, h):
        for p, o in _classified_voids(solid.slice(float(z)), z, spec, t):
            if o is None: bad.append(_island(p, z))
            else: ok[o.name] = ok.get(o.name, 0)+1
    a_fail = _clusters(bad, h)
    caps = []
    for z_sec, z_cap in spec.caps:
        ends = [p for p, o in _classified_voids(solid.slice(float(z_sec)), z_sec, spec, t) if o is not None and o.end_opening]
        caps.append((z_cap, ends))
    vox = _seal_voxels(solid, spec, t, caps)
    for f in a_fail: f['kind'] = 'section void that is no designed opening (cavity in the wall)'
    summary = dict(a_undesigned_voids=a_fail, a_designed_void_layers=ok, b_voxels=vox)
    return GateResult('seal', not a_fail and not vox['leaks'] and not vox['enclosed_voids'], summary,
                      failures=a_fail+vox['leaks']+vox['enclosed_voids'])


def _seal_voxels(solid, spec, t, caps):
    from scipy import ndimage
    v = t.voxel; bb = solid.bounding_box(); pad = 3*v; top = bb[5]
    xs, ys, zc = (np.arange(bb[i]-pad, bb[i+3]+pad+1e-9, v)+v/2 for i in range(3))
    X, Y = np.meshgrid(xs, ys, indexing='ij'); occ = np.zeros((len(xs), len(ys), len(zc)), bool)
    for k, z in enumerate(zc):
        if 0 < z < top:
            poly = to_shapely(solid.slice(float(z)))
            if not poly.is_empty: occ[:, :, k] = shapely.contains_xy(poly, X, Y)
    cap_rows = []
    for z_cap, polys in caps:
        if not polys: cap_rows.append(dict(z=z_cap, area_mm2=0.0)); continue
        g = to_shapely(mf.CrossSection.batch_boolean(polys, mf.OpType.Add).offset(t.cap_grow, ROUND, circular_segments=32))
        k = int(np.argmin(abs(zc-z_cap))); occ[:, :, k] |= shapely.contains_xy(g, X, Y)
        cap_rows.append(dict(z=round(float(zc[k]), 3), area_mm2=round(float(g.area), 1)))
    lab, n = ndimage.label(~occ)   # 6-connectivity: a fluid path must cross a full voxel face
    border = set(np.unique(np.r_[lab[[0, -1]].ravel(), lab[:, [0, -1]].ravel(), lab[:, :, [0, -1]].ravel()]).tolist()) - {0}
    idx = lambda p: tuple(int(np.argmin(abs(a-c))) for a, c in zip((xs, ys, zc), p))  # noqa: E731
    seeds = {int(lab[idx(p)]) for p in spec.passage_seeds} - {0}
    leaks = [dict(kind='the passage reaches the outside other than through its end openings',
                  **_leak_path(lab == s, idx(spec.passage_seeds[0]), xs, ys, zc, solid)) for s in sorted(seeds & border)]
    sizes = ndimage.sum_labels(np.ones(lab.shape), lab, index=np.arange(1, n+1)); boxes = ndimage.find_objects(lab)
    enclosed = []
    for s in range(1, n+1):
        if s in border or s in seeds or sizes[s-1]*v**3 < t.min_void_mm3: continue
        sl = boxes[s-1]; lo = [x.start for x in sl]; hi = [x.stop-1 for x in sl]
        enclosed.append(dict(kind='enclosed void', volume_mm3=round(float(sizes[s-1])*v**3, 3),
                             bbox=[round(float(a[i]), 2) for a, i in zip((xs, ys, zc), lo)]+[round(float(a[i]), 2) for a, i in zip((xs, ys, zc), hi)]))
    return dict(voxel_mm=v, caps=cap_rows, passage_components=len(seeds), leaks=leaks, enclosed_voids=enclosed)


def _leak_path(comp, start, xs, ys, zc, solid):
    """Shortest voxel path from the passage seed to the grid edge, and where it leaves the part's filled outline."""
    from collections import deque
    prev = {start: None}; q = deque([start]); end = None; shape = comp.shape
    while q:
        c = q.popleft()
        if 0 in c or any(c[i] == shape[i]-1 for i in range(3)): end = c; break
        for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            nb = (c[0]+d[0], c[1]+d[1], c[2]+d[2])
            if nb not in prev and comp[nb]: prev[nb] = c; q.append(nb)
    path = []
    while end is not None: path.append(end); end = prev[end]
    exit_at = None
    for i, j, k in path[::-1]:
        z = float(zc[k])
        if not 0 < z < solid.bounding_box()[5]: continue
        sec = to_shapely(solid.slice(z))
        filled = shapely.unary_union([Polygon(p.exterior) for p in getattr(sec, 'geoms', [sec])])
        if not filled.contains(Point(xs[i], ys[j])): exit_at = [round(float(xs[i]), 2), round(float(ys[j]), 2), round(z, 2)]; break
    return dict(path_voxels=len(path), leaves_part_at=exit_at)


def seat_coverage(solid: mf.Manifold, spec: PartSpec, t: Thresholds = Thresholds()) -> GateResult:
    """Each seat's sealed region, just below the seat plane, must be covered by material, the passage opening or a named
    allowed opening; more than max_seat_uncovered_mm2 exposed per seat fails, with the exposed patches' locations. What
    the allowed openings leave exposed beyond the mating part's own covers is the open area: more than max_seat_open_mm2
    per seat fails."""
    rows = []; fails = []
    for seat in spec.seats:
        z = seat.z-t.seat_eps; cs = solid.slice(float(z))
        passage = [p for p, o in _classified_voids(cs, z, spec, t) if o is not None and o.end_opening]
        covered = to_shapely(mf.CrossSection.batch_boolean([cs, *passage], mf.OpType.Add)) if not cs.is_empty() else Polygon()
        exposed = seat.region.difference(covered)
        opened = exposed
        for _, poly, _ in seat.covers: opened = opened.difference(poly)
        for _, poly, _ in seat.openings: exposed = exposed.difference(poly)
        opened = opened.difference(exposed)   # through the allowed openings only
        patches = sorted([q for q in getattr(exposed, 'geoms', [exposed]) if not q.is_empty and q.area > 1e-4], key=lambda q: -q.area)
        row = dict(seat=seat.name, z=round(float(z), 4), region_mm2=round(seat.region.area, 2), uncovered_mm2=round(exposed.area, 4),
                   open_mm2=round(opened.area, 3), allowed_openings=[dict(name=n, why=w) for n, _, w in seat.openings],
                   covers=[dict(name=n, why=w) for n, _, w in seat.covers],
                   patches=[dict(area_mm2=round(q.area, 4), at=[round(q.representative_point().x, 2), round(q.representative_point().y, 2), round(float(z), 3)],
                                 bbox_xy=[round(v, 2) for v in q.bounds]) for q in patches[:12]])
        rows.append(row)
        if exposed.area > t.max_seat_uncovered_mm2:
            fails.append(dict(kind='exposed card face at the seat (open fin-channel ends: a leak)', seat=seat.name, uncovered_mm2=row['uncovered_mm2'],
                              at=row['patches'][0]['at'], bbox_xy=row['patches'][0]['bbox_xy']))
        if opened.area > t.max_seat_open_mm2:
            big = max(getattr(opened, 'geoms', [opened]), key=lambda q: q.area)
            fails.append(dict(kind='card face open through the allowed openings beyond the open-area budget (a leak)', seat=seat.name,
                              open_mm2=row['open_mm2'], at=[round(big.representative_point().x, 2), round(big.representative_point().y, 2), round(float(z), 3)],
                              bbox_xy=[round(v, 2) for v in big.bounds]))
    return GateResult('seat_coverage', not fails, dict(limit_mm2=t.max_seat_uncovered_mm2, open_limit_mm2=t.max_seat_open_mm2, seats=rows), failures=fails)


# --------------------------------------------------------------------------------------------------------------------
# Slicer gate


def support_from_gcode(gcode, stl_bounds, cell=1.0, keep_points=False) -> dict:
    """Support extrusions in a Bambu/Orca G-code: filament length and mass, and 3-D support islands in model coordinates.

    The plate offset is recovered from the first layer's outer wall against `stl_bounds`: the xy bounds of the STL's first
    layer (its bed footprint), which the part's overall bounds equal only when nothing overhangs the footprint.
    """
    import re
    from scipy import ndimage
    z = 0.0; feat = ''; x = y = None; segs = []; first = []; density = 1.27; dia = 1.75
    num = re.compile(r'([XYE])(-?\d*\.?\d+)')
    with open(gcode) as f:
        for line in f:
            if line.startswith(';'):
                if line.startswith('; Z_HEIGHT:'): z = float(line.split(':')[1]); feat = ''
                elif line.startswith('; FEATURE:'): feat = line.split(':', 1)[1].strip()
                elif line.startswith('; filament_density:'): density = float(line.split(':')[1].split(',')[0])
                elif line.startswith('; filament_diameter:'): dia = float(line.split(':')[1].split(',')[0])
                continue
            if not line.startswith(('G1 ', 'G0 ', 'G2 ', 'G3 ')): continue
            m = dict((k, float(v)) for k, v in num.findall(line.split(';')[0]))
            nx = m.get('X', x); ny = m.get('Y', y)
            if m.get('E', 0) > 0 and x is not None and (nx != x or ny != y):
                if feat.startswith('Support'): segs.append((z, x, y, nx, ny, m['E'], feat == 'Support interface'))
                elif feat == 'Outer wall' and z < .21: first += [(x, y), (nx, ny)]
            x, y = nx, ny
    lo, hi = np.asarray(stl_bounds[0]), np.asarray(stl_bounds[1])
    off = (np.min(first, 0)+np.max(first, 0))/2-(lo[:2]+hi[:2])/2 if first else np.zeros(2)
    if not segs:
        return dict(support_filament_mm=0.0, support_g=0.0, interface_g=0.0, islands=[], plate_offset_xy=np.round(off, 3).tolist())
    a = np.array(segs, dtype=float); grams = a[:, 5]*np.pi*(dia/2)**2*density/1000
    zi = np.searchsorted(np.unique(a[:, 0]), a[:, 0])
    pts = []; owner = []
    for n_, (_, x0, y0, x1, y1, _, _) in enumerate(a):
        k = max(2, int(np.hypot(x1-x0, y1-y0)/(cell/2))+1); s = np.linspace(0, 1, k)
        pts.append(np.c_[np.full(k, zi[n_]), x0+s*(x1-x0)-off[0], y0+s*(y1-y0)-off[1]]); owner.append(np.full(k, n_))
    P = np.vstack(pts); owner = np.concatenate(owner)
    gx = np.floor((P[:, 1]-P[:, 1].min())/cell).astype(int); gy = np.floor((P[:, 2]-P[:, 2].min())/cell).astype(int); gz = P[:, 0].astype(int)
    grid = np.zeros((gz.max()+1, gx.max()+1, gy.max()+1), bool); grid[gz, gx, gy] = True
    lab, n = ndimage.label(grid, structure=np.ones((3, 3, 3)))
    seg_lab = np.zeros(len(a), int); seg_lab[owner] = lab[gz, gx, gy]
    islands = []
    for i in range(1, n+1):
        sel = seg_lab == i
        if not sel.any(): continue
        s = a[sel]; top = s[:, 0].max(); tt = s[s[:, 0] == top]
        xy = np.r_[tt[:, [1, 2]], tt[:, [3, 4]]]-off; allxy = np.r_[s[:, [1, 2]], s[:, [3, 4]]]-off
        islands.append(dict(_top_xy=xy, grams=round(float(grams[sel].sum()), 4), z_range=[round(float(s[:, 0].min()), 2), round(float(top), 2)],
                            top_contact_bbox_xy=np.r_[xy.min(0), xy.max(0)].round(1).tolist(),
                            bbox_xy=np.r_[allxy.min(0), allxy.max(0)].round(1).tolist(),
                            interface_g=round(float(grams[sel & (a[:, 6] > 0)].sum()), 4)))
    islands.sort(key=lambda r: (-r['grams'], r['z_range'], r['bbox_xy']))
    if not keep_points:
        for r in islands: del r['_top_xy']
    return dict(support_filament_mm=round(float(a[:, 5].sum()), 2), support_g=round(float(grams.sum()), 3),
                interface_g=round(float(grams[a[:, 6] > 0].sum()), 3), islands=islands, plate_offset_xy=np.round(off, 3).tolist())


def slicer_support(stl, out_dir=None, t: Thresholds = Thresholds(), spec: PartSpec | None = None, gcode=None) -> GateResult:
    """Slice with automatic supports (the repo's P1S profile, profiles/slicer/process-028.json) and measure the support
    material in the G-code. `gcode`: reuse an existing automatic-supports slice instead of slicing again.

    Support whose top contact lies under a designed bridge of `spec` (an overhang Allowed with max_deg >= 90) is
    reported as allowed; any other support fails.
    """
    from .slice import slice_stl
    info = None
    if gcode is None:
        info = slice_stl(stl, Path(out_dir), True)
        gcode = next(Path(out_dir).glob('*.gcode'))
    mesh = trimesh.load(Path(stl)); z0 = mesh.bounds[0][2]
    foot = mesh.section(plane_origin=[0, 0, z0+.1], plane_normal=[0, 0, 1])   # the plate offset is matched on the first layer's
    rep = support_from_gcode(gcode, foot.bounds if foot is not None else mesh.bounds, keep_points=True)   # outline, not the part's bounds
    bridges = [a for a in (spec.overhang_allowed if spec else ()) if a.max_deg >= 90]
    bad, ok = [], []
    for isl in rep['islands']:
        pts = shapely.points(isl.pop('_top_xy')); zc = isl['z_range'][1]+t.slicer_layer_h   # + support_top_z_distance
        hit = next((a for a in bridges if a.lo[2]-.6 <= zc <= a.hi[2]+.6 and shapely.contains(
                    (a.region if a.region is not None else box(a.lo[0], a.lo[1], a.hi[0], a.hi[1])).buffer(1.0), pts).all()), None)
        (ok if hit else bad).append({**isl, **({'allowed_as': hit.name} if hit else {})})
    grams = round(sum(i['grams'] for i in bad), 4)
    # the G-code is reported as runs/<slice dir>/<file>: checks.json ships in releases/, so no machine-local path
    summary = dict(profile='profiles/slicer/process-028.json', gcode=f'runs/{Path(gcode).parent.name}/{Path(gcode).name}', slice=info, gate_g=t.support_max_g,
                   unexplained_support_g=grams, allowed_support_g=round(sum(i['grams'] for i in ok), 4),
                   **{k: v for k, v in rep.items() if k != 'islands'}, islands=bad)
    return GateResult('slicer_support', grams <= t.support_max_g, summary, failures=bad, allowed=ok)


# --------------------------------------------------------------------------------------------------------------------
# Part specifications


SEAT_CLEARANCE = .3   # per side around the connector envelopes at the seat: a 0.4 mm nozzle holds about +-0.15 mm on such edges


def duct_spec(g) -> PartSpec:
    """The duct (duct.cad.geometry), printed fan face down."""
    from ..cad.geometry import splitter_half_width
    L = g.chamber_length; top = L+g.collar_length; ft = g.flange_thickness; o = g.fan_hole_offset; P = g.fan_plate/2+1
    d = g.return_depth; rx, ry, rw, rh = g.return_rect; hx, hy, hw, _ = g.housing_clear; e = .1
    zz = np.linspace(0, L, 7001); hs = np.array([splitter_half_width(g, z) for z in zz])
    z_web = float(zz[np.argmax(hs >= g.wall_dilation+g.splitter_groove_radius)])
    solids = [Allowed('fan plate', (-P, -P, -1), (P, P, ft+g.wall_dilation), f'{ft} mm plate under the 105 mm screw pattern: solid by '
                      f'design; the ball also fits in the L-junction of each wall with the plate, up to about one wall above it')]
    if g.flange_fillet:
        solids.append(Allowed('flange fillet', (-P, -P, ft), (P, P, ft+g.flange_fillet),
                              f'{g.flange_fillet} mm concave fillet between plate and body: a solid quarter-round'))
    solids.append(Allowed('splitter web', (-3, -P, -1), (3, P, max(z_web+2*g.wall_dilation, 1.0)),
                          f'the web between the branches is solid until the skins part by 2 x splitter_groove_radius '
                          f'(splitter half width >= wall + groove at z = {z_web:.2f} mm), then the shell rounds it'))
    if g.shared_wall:
        sw = g.shared_wall
        solids.append(Allowed('shared collar wall between adjacent cards', (-sw/2-g.wall_dilation, -P, -1), (sw/2+g.wall_dilation, P, top+1),
                              f'at the {g.pitch} mm (2-slot) pitch the bores are pitch - bore = {sw:.2f} mm apart: the splitter web never parts '
                              f'into two skins and the two inner collar walls are one {sw:.2f} mm wall between the cards (about five 0.4 mm lines), '
                              f'solid from the fan face to the collar top, with its T-junctions into the outer walls'))
    overhang = []
    w = g.wall_dilation   # each return fuses with the adjoining shell wall: its box extends one wall into it
    bhw = g.bore[0]/2; r_seat = g.passage_radius-g.passage_radius_drop
    for cx in [] if g.return_frame else g.card_x:
        solids += [Allowed('connector return, floor strip', (cx+rx-e, g.bay_floor_y-e, L-d), (cx+rx+rw+w, hy+e, L+w),
                           f'the {hy-g.bay_floor_y:.1f} mm strip between the bay floor (passage, y {g.bay_floor_y}) and the plug pocket '
                           f'floor (y {hy}), {d} mm deep under the seat: the integral connector return'),
                   Allowed('connector return, latch-side wall', (cx+hx+hw-e, g.bay_floor_y-e, L-d), (cx+rx+rw+w, ry+rh+w, L+w),
                           f'the return wall between the housing/latch clearance (x {hx+hw:+.2f} from the card centre) and the bay '
                           f'wall, {d} mm deep under the seat: the integral connector return')]
        overhang.append(Allowed('connector return, latch-side ramp', (cx+hx+hw-e, g.bay_floor_y-e, L-d), (cx+rx+rw+e, ry+rh+e, L),
                                f'the return underside ramps at return_ramp_slope ({g.return_ramp_slope} mm/mm, 40 deg) relative to the bay '
                                f'wall, which narrows outward over the same height: measured up to ~53 deg, which the slicer (supports from '
                                f'60 deg) prints unsupported in V23-V25', max_deg=55.0))
    for cx in g.card_x if g.return_frame else []:
        solids.append(Allowed('seat corner fill', (cx-bhw-w-e, g.bay_floor_y-r_seat-w-e, L-3.5), (cx-bhw+r_seat+e, hy+e, L),
                              f'the seat closes between the rounded passage corner (r {r_seat} mm at the seat) and the square bore/collar, '
                              f'and up to the plug-pocket floor (y {hy}), undercut at return_ramp_slope: ~30 mm3 per card, up to 2.7 mm wide, within 3.5 mm of the seat'))
    for cx in g.card_x if g.seat_seal else []:
        x_bay = g.bay_wall_x-g.bay_wall_narrowing+g.skin_wall   # the air's bay wall at the seat, from the card centre
        span = x_bay-w-(hx+hw); depth = span/g.return_ramp_slope+.4
        solids.append(Allowed('seat seal beside the latch wall', (cx+hx+hw-e, g.bay_floor_y-e, L-depth-1), (cx+g.bay_wall_x+g.skin_wall+e, g.bore[1]/2+e, L),
                              f'the card face between the housing clearance (x {hx+hw:+.2f}) and the rounded bay wall is over the fin '
                              f'stack, so the seat covers it (seat_coverage); it is a {span:.1f} mm cantilever from the bay-wall shell, '
                              f'grown from it at return_ramp_slope ({depth:.1f} mm deep at the shell): a thinner sloped skin would enclose a '
                              f'cavity under the seat for about the same material'))
    holes =tuple((sx*o, sy*o) for sx in (-1, 1) for sy in (-1, 1))
    openings = (Opening('branch passage', (0, top), min_area=100.0, max_count=2, end_opening=True),
                Opening('fan screw hole', (0, ft), centres=holes, radius=g.fan_hole_radius))
    if g.hub_fairing:
        from ..cad.geometry import hub_fairing
        shell = hub_fairing(g); f = shell.info; w = g.wall_dilation
        # First: at the fan face the cavity is as large as a branch passage. It opens onto the fan (a border component in 3-D,
        # not an end opening to cap), and in each section it is the disc inside the fairing shell.
        openings = (Opening('hub fairing cavity', (0, f['cavity_length_mm']), region=Point(0, 0).buffer(f['cavity_radius_mm'], quad_segs=64), tol=.1),)+openings
        if not g.shared_wall:   # (at the 2-slot pitch the junction lies inside the shared-wall allowance)
            # Where the parted web's skins (outer faces at x = +-splitter half width) cross the narrowing fairing shell at a
            # shallow angle, the two 1.2 mm walls merge into a short solid wedge: z_j, where the fairing's radius meets them.
            radius = lambda z: max((float(np.hypot(*np.asarray(p).T).max()) for p in shell.outer.slice(float(z)).to_polygons()), default=0.0)  # noqa: E731
            lo, hi = z_web, f['tip_z_mm']
            for _ in range(40):
                mid = (lo+hi)/2; lo, hi = (mid, hi) if radius(mid) > splitter_half_width(g, mid) else (lo, mid)
            zj = lo; xj = splitter_half_width(g, zj); yj = radius(zj-2*w)
            solids.append(Allowed('hub fairing root on the splitter web', (-xj-.5, -yj-.5, zj-2*w), (xj+.5, yj+.5, zj+2*w),
                                  f'the parted web\'s skins (outer faces at x = +-{xj:.2f} mm) cross the {w} mm fairing shell where its '
                                  f'radius meets them (z = {zj:.1f} mm), at a shallow angle: the two walls merge into a short solid wedge '
                                  f'within one wall pair ({2*w:.1f} mm) of that height'))
    seeds = tuple((sx*g.fan_radius/2, 0.0, .5) for sx in (-1, 1))
    caps = ((.1, -.25), (L-.1, L+.25))   # the fan aperture and the GPU seat; the collars above the seat are open sleeves
    # The card's end face at the seat: the bore over the fin stack (rows of horizontal fin plates whose channels span the
    # card width; the port boxes reach |y| = y_fin, the bore's last ~1.9 mm at each end is the shroud frame, no channel ends)
    bw, bh = g.bore; y_fin = max(max(abs(y0), abs(y1)) for _, _, (_, _, y0, y1) in g.port_boxes)
    # Allowed openings: the connector envelope (housing, latch lever with its release swing) plus SEAT_CLEARANCE per side,
    # whatever the clearance boxes the CAD cuts; the housing's own footprint covers the card face.
    def rect(cx, r, grow=0.): return box(cx+r[0]-grow, r[1]-grow, cx+r[0]+r[2]+grow, r[1]+r[3]+grow)
    seats = tuple(SeatFace(f'card {"AB"[i]} seat', L, box(cx-bw/2, -y_fin, cx+bw/2, y_fin), (
        ('plug housing clearance', rect(cx, g.plug, SEAT_CLEARANCE), f'the power plug enters here along its insertion sweep: housing + {SEAT_CLEARANCE} mm'),
        ('latch clearance', rect(cx, g.latch, SEAT_CLEARANCE), f"the plug's latch lever and its release swing, along the same sweep, + {SEAT_CLEARANCE} mm")),
        (('connector housing', rect(cx, g.plug), "the card's power-connector housing covers the card face under it"),))
        for i, cx in enumerate(g.card_x))
    return PartSpec('duct', wall=g.wall_dilation, overhang_allowed=tuple(overhang), solid_allowed=tuple(solids),
                    openings=openings, passage_seeds=seeds, caps=caps, seats=seats)


def _fillet_band(c):
    """Where the body-to-flange fillet (and, inside, the lips and web rounds on the plenum floor) can be: the plenum's
    footprint at the flange top grown by the wall and the fillet (split v4 collectors); None (anywhere) for the older ones."""
    from ..cad import exhaust as ex
    if not (c.split and c.vane_style == 'v4'): return None
    env = shapely.unary_union([ex.split_section(c, c.flange_thickness+d) for d in (0.0, c.flange_fillet)])
    return env.buffer(c.wall+c.flange_fillet+.8)


def collector_spec(c) -> PartSpec:
    """The exhaust collector (duct.cad.exhaust), printed case face (flange) down."""
    from ..cad import exhaust as ex
    D = c.plenum_depth; tf = c.flange_thickness; tp = c.fan_plate_thickness; h = Thresholds.layer_h; F = 200.0
    ring = ex.gasket_ring(c); pockets = shapely.unary_union([ex.magnet_pocket(c, p) for p in ex.mount_points(c)]) if c.mount == 'magnets' else None
    pilots = shapely.unary_union([Point(p).buffer(c.fan_hole_radius+.8) for p in ex.fan_holes(c)])
    roof = c.magnet_thickness+.2
    overhang = [Allowed('gasket groove roof', (-F, -F, c.gasket_depth-h), (F, F, c.gasket_depth+2*h),
                        f'{c.gasket_width} mm bridge over the foam groove on the case face', region=ring.buffer(.3))]
    if not c.pilot_depth:   # through pilots (blind ones stay inside the chamfer)
        overhang.append(Allowed('fan-screw pilot exit', (-F, -F, 0), (F, F, D),
                                f'the {2*c.fan_hole_radius} mm pilot leaves the 45 deg ear chamfer: a crescent bridging the hole', region=pilots))
    solids = [Allowed('flange', (-F, -F, -1), (F, F, tf), f'{tf} mm flange on the rear panel'),
              Allowed('flange fillet', (-F, -F, tf), (F, F, tf+c.flange_fillet), f'{c.flange_fillet} mm concave fillet between flange and body',
                      region=_fillet_band(c)),
              Allowed('fan plate', (-F, -F, D-tp), (F, F, D+1), f'{tp} mm fan plate under the 105 mm screw pattern'),
              Allowed('fan-plate ear chamfer blocks', (-F, -F, D-tp-c.fan_size/2*.4-1), (F, F, D-tp),
                      f'the plate corners outside the round bore rest on {c.ear_support_angle:g} deg chamfered blocks that the fan '
                      f'screws thread into (3.4 mm pilots); at >= 16 mm wide the slicer fills them with sparse infill, not solid',
                      region=ex.plate_outline(c).difference(Point(c.fan_axis).buffer(c.fan_radius-.5).intersection(
                          ex.section(ex.air_volume(c), c.inlet_z+D-tp-c.fan_size/2*.4))))]   # outside the bore, or outside the air
                                                                                              # where the blocks start (a 140 fan)
    mouths = ex.mouths(c) if c.split else []
    if c.plug_channels:   # flat roofs over the divider bars, bridged
        ch = shapely.unary_union([box(x0, y0, x1, y1) for x0, x1, y0, y1 in c.plug_channels])
        overhang.append(Allowed('divider-bar channel roof', (-F, -F, c.plug_channel_depth-h), (F, F, c.plug_channel_depth+2*h),
                                f'{max(x1-x0 for x0, x1, _, _ in c.plug_channels):.1f} mm bridge over each divider-bar channel in the plug face',
                                region=ch.buffer(.3)))
    openings = [Opening('gasket groove', (0, c.gasket_depth+h), region=ring, tol=.05)] if not ring.is_empty else []   # first: a shared groove can outsize a mouth
    openings += [
                Opening('plenum', (0, D), min_area=500.0, max_count=len(mouths) if c.split else 1, end_opening=True),   # split: one per mouth
                Opening('fan-screw pilot', (0, D), centres=tuple(map(tuple, ex.fan_holes(c))), radius=c.fan_hole_radius)]
    pk = ex.plug_pockets(c)
    if not pk.is_empty:   # the hollow plug's pockets, open at its top: enclosed in each section below it
        openings.insert(0, Opening('plug pocket', (c.plug_pocket_skin, tf+h), region=pk, tol=.1))
    windows = ex.slot_windows(c)
    if windows:   # windowed flange: a through cutout over each outer open slot (it stays a vent); its top edge is rounded
        openings.insert(0, Opening('open-slot window', (0, tf+h), region=shapely.unary_union(windows), tol=c.flange_top_round+.1))   # before the plenum: both are large
    for name, vm, v in ex.vanes(c) if c.split and c.vane_style == 'v4' else ():
        top = tf+v.get('H', c.vane_root)+.5; xs = [q for s_, l, r in v['profile'] if s_ <= top for q in (l, r)]
        vb = vm.bounding_box()   # the root's own y span (the vane ends FIN_END_GAP off the walls), not the whole part
        what = ('the step fill: each inner wall leans <= {:g} deg into the centre fin (merge radius >= {:g} mm)'.format(c.fill_angle, c.merge_fillet)
                if v['root'] == 'fill' else f"its root widens into the flange strip under it (radius >= {v.get('min_radius', c.vane_root):.1f} mm)")
        solids.append(Allowed(f'{name} fin root' if v['root'] != 'fill' else 'channel merge ridge', (-F, -F, tf), (F, F, top),
                              f'the 1.2 mm {name} fin: ' + what, region=box(min(xs)-.5, vb[1]-.5, max(xs)+.5, vb[4]+.5)))
    if c.split and c.hub_fairing:   # the fairing's cavity: open toward the fan (not enclosed in 3-D), a void in each section
        f = ex.hub_fairing(c)[1]; R = c.hub_fairing_d/2
        openings.insert(0, Opening('hub fairing cavity', (f['tip_s_mm'], D), region=Point(c.fan_axis).buffer(R), tol=.1))
        solids += hub_fairing_junctions(c, f)
    if c.mount == 'snap':   # the clip posts fill the mouth corners over the bracket plate (designed solid)
        k = ex.snap_dims(c)
        for i, post in enumerate(ex.snap_posts(c)[0]):
            bb = post.bounding_box()
            solids.append(Allowed(f'snap clip post {i+1}', (bb[0]-.5, bb[1]-.5, -1), (bb[3]+.5, bb[4]+.5, k['top_s']+.5),
                                  'solid post holding a snap clip in its dovetail slot, over the bracket plate (no flow there)'))
    if pockets is not None:
        overhang.append(Allowed('magnet pocket ceiling', (-F, -F, roof-h), (F, F, roof+2*h),
                                f'{c.magnet_diameter+2*c.magnet_clearance:.1f} mm bridge over each magnet pocket', region=pockets.buffer(.3)))
        openings.append(Opening('magnet pocket', (0, roof+h), region=pockets, tol=.05))
    caps = ((.1, -.25), (D-.1, D+.25))   # the case-face mouth and the fan bore
    return PartSpec('collector', wall=c.wall, overhang_allowed=tuple(overhang), solid_allowed=tuple(solids), openings=tuple(openings),
                    passage_seeds=tuple(((m[0]+m[1])/2, (m[2]+m[3])/2, .5) for m in mouths) if c.split else ((*c.fan_axis, .5),),
                    caps=caps)   # split: one seed per mouth (the fan axis lies under the flange web between them)


def hub_fairing_junctions(c, f, bands: int = 12, margin: float = 1.5) -> list[Allowed]:
    """Where the hub fairing's shell crosses the centre fin: per height band, two small boxes on the fin around the shell's
    radius range in that band (wall + margin each side), and a disc at the round tip. Nothing inside the cavity or beyond."""
    from ..cad import exhaust as ex
    R = c.hub_fairing_d/2; p = c.hub_fairing_power; L = f['length_mm']; sb = f['base_s_mm']; xw = ex.web_x(c); ax, ay = c.fan_axis
    hw = c.fin_thickness/2+c.wall+margin; rad = lambda s: R*(1-min(max((sb-s)/L, 0.), 1.)**p)  # noqa: E731
    out = []; edges = np.linspace(f['tip_s_mm']-.5, sb+.5, bands+1)
    for k, (s0, s1) in enumerate(zip(edges, edges[1:])):
        r0, r1 = rad(s0)-c.wall-margin, rad(s1)+margin
        reg = shapely.unary_union([box(xw-hw, ay+sg*max(r0, 0.), xw+hw, ay+sg*r1) for sg in (-1, 1)]) if r0 > 0 else box(xw-hw, ay-r1, xw+hw, ay+r1)
        out.append(Allowed(f'hub fairing on the centre fin, band {k+1}', (-200, -200, s0), (200, 200, s1),
                           f'the 1.2 mm fairing shell (radius {rad(s0):.1f}-{rad(s1):.1f} mm here) crosses the 1.2 mm centre fin, its strut',
                           region=reg))
    out.append(Allowed('hub fairing tip on the centre fin', (-200, -200, f['tip_s_mm']-.5), (200, 200, f['tip_s_mm']+c.hub_fairing_tip+c.wall+margin),
                       f'the {c.hub_fairing_tip} mm round tip closes on the fin', region=Point(ax, ay).buffer(c.hub_fairing_tip+c.wall+margin)))
    return out


def snap_clip_spec(c) -> PartSpec:
    """A snap clip (duct.cad.exhaust.snap_clip), printed lying on its side: a solid part by design (a 1.6 mm cantilever and
    its dovetail tenon), no passages."""
    F = 200.0
    return PartSpec('snap clip', wall=c.wall, solid_allowed=(Allowed('snap clip', (-F, -F, -1), (F, F, F),
                    f'{c.snap_arm_thickness} mm spring arm and its {c.snap_tenon[1]} mm dovetail tenon: solid for stiffness'),))


GEOMETRIC_GATES = {'unsupported_overhang': unsupported_overhang, 'solid_regions': solid_regions, 'seal': seal,
                   'seat_coverage': seat_coverage}   # run_gates' order


def gate_workers() -> int:
    """Processes for run_gates' geometric gates: DUCT_GATE_WORKERS, else up to 4 (one per gate); 1 runs them in-process."""
    n = os.environ.get('DUCT_GATE_WORKERS')
    return max(1, int(n)) if n else min(len(GEOMETRIC_GATES), os.cpu_count() or 1)


def _gate_in_worker(name: str, source, spec: PartSpec, t: Thresholds) -> GateResult:
    """One geometric gate on the mesh loaded here: an STL path, or (vertices, faces) of a trimesh."""
    stl = trimesh.Trimesh(*source, process=False) if isinstance(source, tuple) else source
    return GEOMETRIC_GATES[name](load_manifold(stl), spec, t)


def _gate_stdio():
    """A gate worker process: a pickled (name, source, spec, thresholds) on stdin, the pickled GateResult on stdout
    (anything else written to stdout goes to stderr)."""
    import pickle
    import sys
    out = os.fdopen(os.dup(1), 'wb'); os.dup2(2, 1); sys.stdout = sys.stderr
    result = _gate_in_worker(*pickle.load(sys.stdin.buffer))
    pickle.dump(result, out, protocol=pickle.HIGHEST_PROTOCOL); out.close()


def _gate_process(name: str, source, spec: PartSpec, t: Thresholds) -> GateResult:
    """_gate_in_worker in a fresh Python process (a plain subprocess: no multiprocessing, so scripts without a
    __main__ guard and sandboxes without POSIX semaphores work), importing duct from this process's sys.path."""
    import pickle
    import subprocess
    import sys
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join(p or os.getcwd() for p in sys.path)}
    r = subprocess.run([sys.executable, '-c', 'from duct.print.printability import _gate_stdio; _gate_stdio()'],
                       input=pickle.dumps((name, source, spec, t), protocol=pickle.HIGHEST_PROTOCOL), capture_output=True, env=env)
    if r.returncode: raise RuntimeError(f'{name} gate worker failed ({r.returncode}):\n{r.stderr.decode(errors="replace")[-4000:]}')
    return pickle.loads(r.stdout)


def run_gates(stl, spec: PartSpec, t: Thresholds = Thresholds(), slicer: dict | None = None, workers: int | None = None,
              slicer_after=None) -> dict:
    """The geometric gates, plus the slicer gate when `slicer` gives slicer_support kwargs (out_dir, gcode, ...).

    {'passed': bool, 'failed': [gate names], 'gates': {name: result dict}}.

    The geometric gates run in `workers` processes (default gate_workers()), each loading the mesh itself, and the slicer
    gate meanwhile in this one, after `slicer_after()` (e.g. waiting for the slice whose G-code it reads); the result is
    the same as with workers=1 (in-process, one after the other), order included.
    """
    workers = gate_workers() if workers is None else workers
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        source = (np.asarray(stl.vertices), np.asarray(stl.faces)) if isinstance(stl, trimesh.Trimesh) else str(Path(stl).resolve())
        order = sorted(GEOMETRIC_GATES, key=lambda n: n != 'unsupported_overhang')   # the longest first
        with ThreadPoolExecutor(min(workers, len(order))) as pool:
            jobs = {n: pool.submit(_gate_process, n, source, spec, t) for n in order}
            if slicer_after is not None: slicer_after()
            sliced = [slicer_support(stl, t=t, spec=spec, **slicer)] if slicer is not None else []
            gates = [jobs[n].result() for n in GEOMETRIC_GATES]+sliced
    else:
        solid = load_manifold(stl)
        gates = [gate(solid, spec, t) for gate in GEOMETRIC_GATES.values()]
        if slicer is not None:
            if slicer_after is not None: slicer_after()
            gates.append(slicer_support(stl, t=t, spec=spec, **slicer))
    return dict(part=spec.name, thresholds=asdict(t), passed=all(x.passed for x in gates),
                failed=[x.name for x in gates if not x.passed], gates={x.name: x.to_dict() for x in gates},
                allowlist=[dict(gate=gate, name=a.name, lo=a.lo, hi=a.hi, max_deg=a.max_deg, why=a.why)
                           for gate, al in (('unsupported_overhang', spec.overhang_allowed), ('solid_regions', spec.solid_allowed)) for a in al])


def failure_lines(result: dict) -> list[str]:
    """One line per failing finding of a run_gates() result: gate, kind, where (xyz mm) and size."""
    out = []
    for name, g in result['gates'].items():
        if g['passed']: continue
        for f in g['failures']:
            where = f.get('worst_layer') or f.get('at') or f.get('leaves_part_at') or f.get('bbox')
            if 'uncovered_mm2' in f: size = f"{f['seat']}: {f['uncovered_mm2']} mm2 uncovered, largest patch xy {f['bbox_xy']}"
            elif 'open_mm2' in f: size = f"{f['seat']}: {f['open_mm2']} mm2 open through the connector clearances, largest patch xy {f['bbox_xy']}"
            elif 'grams' in f: size = f"{f['grams']} g support, z {f['z_range'][0]}-{f['z_range'][1]}, contact xy {f['top_contact_bbox_xy']}"
            elif 'max_angle_deg' in f: size = f"{f['max_island_mm2']} mm2 at {f['max_angle_deg']} deg, z {f['z_range'][0]}-{f['z_range'][1]}, xy {f['bbox_xy']}"
            elif 'volume_mm3' in f and 'z_range' in f: size = f"{f['volume_mm3']} mm3, worst layer {f['max_island_mm2']} mm2, z {f['z_range'][0]}-{f['z_range'][1]}, xy {f['bbox_xy']}"
            else: size = f.get('kind', '')
            out.append(f'{name}: at {where}: {size}')
    return out


def summary_line(result: dict) -> str:
    return ', '.join(f"{n} {'pass' if g['passed'] else 'FAIL'}" for n, g in result['gates'].items())
