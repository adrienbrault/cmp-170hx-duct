"""Reference (not printed) PC-case and card hardware at the cards' rear, in the duct frame, for fit checks and previews.

Duct frame: x across the cards (centres at +-pitch/2), y along the card height (+y = the card's top edge = the bracket's
screw-tab end), z along the card axis; the cards' brackets sit at z = chamber_length + card_length.

Stack along z, outward (CEM r3.0 Fig 9-25 note 1: "the add-in card bracket resides behind the chassis wall"):
bracket plate [z_b - sheet, z_b] | rear panel [z_b, z_b + panel] | outside. The bracket's top tab points away from the
card (CEM Fig 9-5 side view: the card-mount 4-40 bosses on one side of the plate, the tab on the other), so it
reaches out over the panel's top edge and rests on the slot ledge, the panel folded outward above the slot openings.
Tabs, ledge and slot screws are therefore OUTSIDE the case, in a band just above the slot openings (+y).

Every dimension cites its source: CEM = PCI Express CEM r3.0 figure; "user photo" = the coordinator's estimate from the
author's photos of the CMP 170HX bracket (+-10 %, unmeasured); "assumption" = not in any spec, case-specific, measure.
"""
from dataclasses import dataclass, replace

import manifold3d as mf
import numpy as np
import shapely
import trimesh
from shapely.geometry import Point, box

from ..params import CollectorParams, GeometryParams, slot_layout
from .geometry import cube, union


@dataclass(frozen=True)
class BracketParams:
    sheet: float = .86                   # CEM Fig 9-5 note 1: 0.86 mm (20 ga) steel
    width_single: float = 18.42          # CEM Fig 9-5
    width_dual: float = 38.74            # CEM Fig 9-13 (18.42 + 20.32)
    height_single: float = 112.75        # tab top to tongue base, CEM Fig 9-5
    height_dual: float = 112.93          # CEM Fig 9-13
    tongue_length: float = 7.14          # 120.07 - 112.93, CEM Fig 9-13 (bottom tabs into the board-side slot)
    tongues: tuple[tuple[float, float], ...] = ((4.11, 14.30), (24.43, 34.62))   # x from the reference edge, CEM Fig 9-13
    tab_depth: float = 11.43             # top tab reach from the plate, CEM Fig 9-5 / 9-13
    slot_depth: float = 7.24             # screw-slot centre from the plate, CEM Fig 9-5 / 9-13
    slot_diameter: float = 4.42          # U-slot, full radius, open toward the tab's free edge, CEM Fig 9-5 / 9-13
    slot_x: tuple[float, ...] = (12.45, 32.77)   # slot centres from the reference edge, CEM Fig 9-13 (single: 12.45, Fig 9-5)
    ref_edge: float = -1.0               # assumption: the CEM x dimensions start from the bracket's -x edge (mirroring unresolved)
    window: tuple[float, float, float] = (81.0, 25.0, 8.0)  # 170HX vent window: length (y), width (x), top below bracket top; user photo
    window_x_offset: float = 0.0         # window centre from the card centre, +x (photo: ~3 / 8 mm from the long edges; side unknown)
    bezel: tuple[float, float] = (4.0, .8)   # window bezel: width around the window, height; user photo, unmeasured. Modelled on the
                                             # card side: on the outer face it would hit the panel rib between the two openings
    torx_head: tuple[float, float] = (4.0, 1.0)   # bezel screws (4, at the bezel corners): head diameter, height above the plate's
                                                  # outer face; user photo, unmeasured (1.0 mm: 0.2 mm past an 0.8 mm panel)


@dataclass(frozen=True)
class CaseParams:
    card_length: float = 267.0           # duct seat face to bracket outer face: DomainParams.card_envelope (PB-10577: 267.70 mm
                                         # card without bracket, 268.60 with; the CFD and the collector use 267)
    slot_pitch: float = 20.32            # CEM Fig 1-3, ATX 2.2 Fig 3
    card_pitch: float = 60.96            # GeometryParams.pitch: the slot layout (slots, card_slots) derives from it (slot_layout).
                                         # build_hardware / openings re-derive it from the duct / collector (for_pitch)
    covers: tuple[float, ...] = ()       # slots with a solid single-slot cover; every other non-card slot is OPEN to the case
                                         # air (the author's case: no covers anywhere). CASE_COVERED / covered(): every empty slot
    panel: float = .8                    # rear-panel sheet; assumption (typical SECC 0.6-1.0 mm)
    opening_width: float = 13.25         # per-slot chassis opening, minimum, starting at the PCB plane: CEM Fig 9-22
    opening_height: float = 100.71       # CEM Fig 9-22 (minimum)
    opening_top_drop: float = 4.82       # opening top below the bracket top, maximum: CEM Fig 9-22
    ledge: float = .8                    # slot ledge sheet (the panel folded outward); assumption
    ledge_depth: float = 12.0            # ledge reach from the bracket plane; assumption (>= the 11.43 mm tab)
    lip_up: float = 0.0                  # optional lip at the ledge's outer edge, up (+y) / down (-y); assumption (case-specific)
    lip_down: float = 0.0
    ledge_bend_radius: float = 0.0       # inside radius of the panel-to-ledge fold (outside the case, under the ledge); assumption:
                                         # a press-brake fold is ~1 sheet thickness, 0 models a sharp (welded / hemmed) corner
    panel_margin: tuple[float, float] = (25.0, 30.0)   # panel beyond the outermost openings in x, and below them in y
    screw: str = 'pan'                   # 'pan' or 'thumb'
    pan_head: tuple[float, float] = (6.86, 2.46)       # 6-32 pan head: diameter 0.270 in, height 0.097 in (ASME B18.6.3)
    thumb_head: tuple[float, float] = (12.0, 8.0)      # typical knurled 6-32 thumb screw head (retail listing)
    screw_major: float = 3.51            # 6-32 UNC major diameter
    screw_length: float = 6.35           # 6-32 x 1/4 in
    tap_hole: float = 2.85               # 6-32 tap drill (#36)
    fan: tuple[float, float, float] = (120.0, 25.0, 117.0)   # reference pull fan: square, thickness, bore (Arctic P12 Pro drawing)
    driver_diameter: float = 7.0         # screwdriver access column above a pan head
    finger_diameter: float = 20.0        # finger access column above a thumb-screw head
    # Recessed slot bay (CASE_FRACTAL): all slots in one drawn pocket of the rear panel; None: a flat panel (CEM default).
    # In x it is centred on the slot openings' span; in y its top wall stands recess_top_above_bracket over the bracket top.
    recess: tuple[float, float, float, float] | None = None   # inner width (x), height (y), depth (z, border plane to floor), corner r
    recess_top_above_bracket: float = 2.5
    recess_floor_band: float = 7.0       # flat recess floor between the bottom wall and the visible end of the slot openings
    divider: tuple[float, float] | None = None   # raised rounded bars between the slot openings: base width, crown above the plate
    vented_covers: tuple[float, ...] = ()        # slots with a louvred cover: open to the case air (for the seal) though covered
    bezel_side: str = 'card'             # the 170HX window bezel and its Torx heads: on the card side, or 'outer' (Fractal photos)
    # Neighbours of the recess the collector must keep clear of: (name, x ref, x0, x1, y ref, y0, y1, z0, z1); x from the
    # recess's 'left' / 'right' wall or 'centre', y from its 'top' / 'bottom' wall, z from the border plane (outward +)
    keepouts: tuple[tuple, ...] = ()

    def __post_init__(self):
        assert self.screw in ('pan', 'thumb'), self.screw
        cards = {k for sl in self.card_slots for k in sl}
        assert all(k in self.slots and k not in cards for k in self.covers), f'covers {self.covers} must be empty slots of {self.slots}'

    @property
    def slots(self) -> tuple[float, ...]:
        """Slot positions modelled, in slot pitches from the midpoint between the cards: the cards' slots and one neighbour each
        side. 3-slot card pitch: -3 ... 3 (ints; 0 = the empty slot between the cards); 2-slot pitch: -2.5 ... 2.5."""
        return slot_layout(self.card_pitch, self.slot_pitch)['slots']

    @property
    def card_slots(self) -> tuple[tuple[float, float], ...]:
        return slot_layout(self.card_pitch, self.slot_pitch)['cards']

    def for_pitch(self, card_pitch: float) -> 'CaseParams':
        """This case with the cards `card_pitch` apart (its covers must be slots of that layout)."""
        return self if card_pitch == self.card_pitch else replace(self, card_pitch=card_pitch)

    def covered(self) -> 'CaseParams':
        """This case with a solid cover in every slot without a card."""
        cards = {k for sl in self.card_slots for k in sl}
        return replace(self, covers=tuple(k for k in self.slots if k not in cards))

    @property
    def open_slots(self) -> tuple[int, ...]:
        """Slots with neither a card bracket nor a cover: open holes into the case."""
        cards = {k for sl in self.card_slots for k in sl}
        return tuple(k for k in self.slots if k not in cards and k not in self.covers)

    @property
    def middle_blank(self) -> bool:
        """Read-only: a cover in the slot between the cards (set it with covers=(0,) or CASE_COVERED)."""
        return 0 in self.covers

    @property
    def head(self) -> tuple[float, float]:
        return self.pan_head if self.screw == 'pan' else self.thumb_head


CASE = CaseParams()                          # the author's case: every slot without a card is open
CASE_COVERED = CASE.covered()                # solid covers in every empty slot (v1 / v2's assumption: -3, 0, +3)
# The author's real case (Fractal, Ion Gold PSU; photos 2026-10): 7 slots in one recessed bay ~ the slots' own size, raised
# rounded dividers between the openings (the one at each card centre crosses its vent window), a louvred blank in slot -3,
# slots 0 and +3 open, no external ledge (the bracket tabs are inside). PHOTO ESTIMATES (+-8 %), scaled from the 20.32 mm
# pitch and the VGA jack's 24.99 mm screws: replace with the author's measurements.
CASE_FRACTAL = replace(CASE, recess=(142.0, 125.0, 8.0, 4.0), recess_top_above_bracket=2.5, recess_floor_band=7.0,
                       divider=(7.0, 3.0), vented_covers=(-3,), bezel_side='outer',
                       keepouts=(('hex vent', 'centre', -71.0, 71.0, 'top', 8.5, 45.0, 0.0, 15.0),        # don't cover it near the panel
                                 ('PSU face', 'right', 6.5, 150.0, 'bottom', -20.0, 145.0, 0.0, 2.0),     # may stand proud of the border
                                 ('PSU inlet and cable', 'right', 25.0, 150.0, 'top', -6.0, 16.0, 0.0, 60.0),
                                 ('I/O shield cables', 'left', -150.0, -7.5, 'bottom', -20.0, 50.0, 0.0, 60.0)))
BRACKET = BracketParams()


def bracket_z(g: GeometryParams, case: CaseParams = CASE) -> float:
    """Bracket outer face (= rear-panel inner face), duct z."""
    return g.chamber_length+case.card_length


def openings(c: CollectorParams, case: CaseParams = CASE) -> dict[float, tuple[float, float, float, float]]:
    """Chassis opening (x0, x1, y0, y1) per slot: starts at the card's PCB plane (CEM Fig 9-22), as CollectorParams.openings.
    The slot layout follows c.card_pitch (case.for_pitch)."""
    case = case.for_pitch(c.card_pitch); s = c.component_side; sec, comp = c.pcb_side_reach
    pcb = -c.card_pitch/2-s*(comp-sec)/2           # card A's PCB secondary face; card A's first slot is case.card_slots[0][0]
    y1 = c.bracket_top_y-case.opening_top_drop; y0 = y1-case.opening_height; out = {}
    for k in case.slots:
        a = pcb+s*(k-case.card_slots[0][0])*case.slot_pitch; b = a+s*case.opening_width
        out[k] = (min(a, b), max(a, b), y0, y1)
    return out


def _span(rects):
    return min(r[0] for r in rects), max(r[1] for r in rects)


def windows(c: CollectorParams, b: BracketParams = BRACKET) -> list[tuple[float, float, float, float]]:
    """Each card's bracket vent window (x0, x1, y0, y1), centred on the card (the CFD centres it on the port span, +0.1 mm)."""
    L, W, top = b.window; y1 = c.bracket_top_y-top
    return [(cx+b.window_x_offset-W/2, cx+b.window_x_offset+W/2, y1-L, y1) for cx in (-c.card_pitch/2, c.card_pitch/2)]


def _bracket(c, case, b, slots, z_b, window=None):
    """One I/O bracket over `slots`: plate, tongues, outward top tab with U-slots; returns (solid, screw xz list, bezel solid)."""
    ops = openings(c, case); x0, x1 = _span([ops[k] for k in slots]); dual = len(slots) == 2
    w = b.width_dual if dual else b.width_single; h = b.height_dual if dual else b.height_single
    xc = (x0+x1)/2; lo, hi = xc-w/2, xc+w/2; top = c.bracket_top_y; t = b.sheet
    ref = lo if b.ref_edge < 0 else hi; sgn = 1 if b.ref_edge < 0 else -1
    plate = box(lo, top-h, hi, top)
    for a, e in b.tongues[:len(slots)]:
        ta, te = sorted([ref+sgn*a, ref+sgn*e])
        plate = plate.union(box(ta, top-h-b.tongue_length, te, top-h))
    bezel = None
    if window is not None:
        wx0, wx1, wy0, wy1 = window
        plate = plate.difference(box(wx0, wy0, wx1, wy1))
        bw, bh = b.bezel; ring = box(wx0-bw, wy0-bw, wx1+bw, wy1+bw).difference(box(wx0, wy0, wx1, wy1))
        heads = [mf.Manifold.cylinder(b.torx_head[1], b.torx_head[0]/2, circular_segments=32).translate([x, y, z_b])
                 for x in (wx0-bw/2, wx1+bw/2) for y in (wy0-bw/2, wy1+bw/2)]
        bezel = union(_extrude(ring, z_b-t-bh, bh), *heads)
    solid = _extrude(plate, z_b-t, t)
    # Top tab: horizontal (normal y), reaching outward from the plate's inner face by tab_depth
    zt0 = z_b-t; zc = zt0+b.slot_depth; r = b.slot_diameter/2
    xs = [ref+sgn*sx for sx in b.slot_x[:len(slots)]]
    tab = box(lo, zt0, hi, zt0+b.tab_depth)              # in the (x, z) plane
    for x in xs: tab = tab.difference(Point(x, zc).buffer(r, quad_segs=16).union(box(x-r, zc, x+r, zt0+b.tab_depth+1)))
    return union(solid, _xz_prism(tab, top-t, top)), [(x, zc) for x in xs], bezel


def _xz_prism(poly, y0, y1) -> mf.Manifold:
    """Prism of an (x, z) polygon over y in [y0, y1]."""
    m = mf.Manifold.extrude(_cs(poly), y1-y0)            # (x, z_in_poly, e) with e along +z
    return m.transform(np.array([[1, 0, 0, 0], [0, 0, 1, y0], [0, 1, 0, 0]], dtype=float))


def _yz_prism(poly, x0, x1) -> mf.Manifold:
    """Prism of a (y, z) polygon over x in [x0, x1]."""
    m = mf.Manifold.extrude(_cs(poly), x1-x0)
    return m.transform(np.array([[0, 0, 1, x0], [1, 0, 0, 0], [0, 1, 0, 0]], dtype=float))


def _cs(poly) -> mf.CrossSection:
    from shapely.geometry.polygon import orient
    polys = [poly] if poly.geom_type == 'Polygon' else list(poly.geoms)
    loops = []
    for p in polys:
        p = orient(p, 1)
        loops += [np.asarray(p.exterior.coords)[:-1]]+[np.asarray(q.coords)[:-1] for q in p.interiors]
    return mf.CrossSection(loops, mf.FillRule.EvenOdd)


def _extrude(poly, z, depth) -> mf.Manifold:
    return mf.Manifold.extrude(_cs(poly), depth).translate([0, 0, z])


def _y_cylinder(x, z, y0, y1, d, n=48) -> mf.Manifold:
    """Cylinder with its axis along y (screws stand on the tab, axis along y)."""
    return mf.Manifold.cylinder(y1-y0, d/2, circular_segments=n).transform(
        np.array([[1, 0, 0, x], [0, 0, 1, y0], [0, 1, 0, z]], dtype=float))


@dataclass(frozen=True)
class Hardware:
    z_b: float                           # bracket outer face / panel inner face
    panel_face: float                    # panel outer face (where the collector flange sits)
    parts: dict                          # name -> mf.Manifold
    screws: list                         # dicts: x, z, head (y0, y1), card or cover slot
    openings: dict                       # slot -> (x0, x1, y0, y1)
    windows: list                        # bracket vent windows (x0, x1, y0, y1)
    ledge_bottom: float                  # y of the ledge's underside
    panel_2d: object                     # shapely: the panel sheet (minus openings) as seen from outside
    plates_2d: object                    # shapely: steel behind the openings (brackets and covers, minus the vent windows)
    case: CaseParams = CASE              # the case as built: its slot layout follows the duct's card pitch


def build_hardware(g: GeometryParams, c: CollectorParams, case: CaseParams = CASE, b: BracketParams = BRACKET) -> Hardware:
    """The case hardware behind duct `g`'s cards: the slot layout, openings and brackets follow g.pitch (the collector `c`
    only lends the shared frame: bracket top, PCB side reach), the bracket plane g.chamber_length + card_length."""
    if c.card_pitch != g.pitch: c = replace(c, card_pitch=g.pitch)
    case = case.for_pitch(g.pitch)
    z_b = bracket_z(g, case); top = c.bracket_top_y; ops = openings(c, case); win = windows(c, b)
    ledge_top = top-b.sheet; ledge_bottom = ledge_top-case.ledge
    assert max(o[3] for o in ops.values()) < ledge_bottom, 'slot openings reach the ledge'
    xs = [x for o in ops.values() for x in o[:2]]
    px0, px1 = min(xs)-case.panel_margin[0], max(xs)+case.panel_margin[0]
    py0 = min(o[2] for o in ops.values())-case.panel_margin[1]
    panel2d = box(px0, py0, px1, ledge_bottom)
    for o in ops.values(): panel2d = panel2d.difference(box(o[0], o[2], o[1], o[3]))
    parts = dict(rear_panel=_extrude(panel2d, z_b, case.panel))
    # Slot ledge: the panel's top edge folded outward; tapped holes under every slot screw
    ledge = _xz_prism(box(px0, z_b, px1, z_b+case.ledge_depth), ledge_bottom, ledge_top)
    lips = []
    if case.ledge_bend_radius:   # fillet in the outside corner between the panel face and the ledge underside
        r = case.ledge_bend_radius; pf = z_b+case.panel
        corner = box(ledge_bottom-r, pf, ledge_bottom, pf+r).difference(Point(ledge_bottom-r, pf+r).buffer(r, quad_segs=32))
        lips.append(_yz_prism(corner, px0, px1))
    if case.lip_up: lips.append(cube([px1-px0, case.lip_up, case.ledge], [px0, ledge_top, z_b+case.ledge_depth-case.ledge]))
    if case.lip_down: lips.append(cube([px1-px0, case.lip_down, case.ledge], [px0, ledge_bottom-case.lip_down, z_b+case.ledge_depth-case.ledge]))
    brackets = {}; screws = []; bezels = []
    for i, slots in enumerate(case.card_slots):
        solid, sxz, bezel = _bracket(c, case, b, slots, z_b, win[i])
        brackets[f'bracket_{"AB"[i]}'] = solid; screws += [dict(x=x, z=z, slot=f'card {"AB"[i]}') for x, z in sxz]
        if bezel is not None: bezels.append(bezel)
    covers = {}
    for k in case.covers:
        solid, sxz, _ = _bracket(c, case, b, (k,), z_b)
        covers[k] = solid; screws += [dict(x=x, z=z, slot=f'cover {k:+g}' if k else 'cover middle') for x, z in sxz]
    hd, hh = case.head; heads = []; shanks = []
    for s in screws:
        heads.append(_y_cylinder(s['x'], s['z'], top, top+hh, hd))
        shanks.append(_y_cylinder(s['x'], s['z'], top-case.screw_length, top, case.screw_major, 24))
        s.update(head_y=(top, top+hh), head_d=hd, outside_by=s['z']-hd/2-(z_b+case.panel), tip_y=top-case.screw_length)
        ledge -= _y_cylinder(s['x'], s['z'], ledge_bottom-1, ledge_top+1, case.tap_hole, 24)
    parts.update(slot_ledge=union(ledge, *lips), **brackets)
    if 0 in covers: parts['blank_middle'] = covers[0]
    if set(covers)-{0}: parts['slot_covers'] = union(*[m for k, m in covers.items() if k])
    parts.update(screw_heads=union(*heads), screw_shanks=union(*shanks))
    if bezels: parts['window_bezels'] = union(*bezels)
    steel = shapely.unary_union([shapely.geometry.Polygon(q) for m in [*brackets.values(), *covers.values()]
                                 for q in m.slice(z_b-b.sheet/2).to_polygons() if shapely.geometry.Polygon(q).area > 0])
    steel = steel.difference(shapely.unary_union([box(w[0], w[2], w[1], w[3]) for w in win]))
    return Hardware(z_b, z_b+case.panel, parts, screws, ops, win, ledge_bottom, panel2d, steel, case)


def fan_box(c: CollectorParams, z_face: float, case: CaseParams = CASE) -> mf.Manifold:
    """Reference pull fan on the collector's fan face (square frame minus the bore)."""
    s, t, bore = case.fan; ax, ay = c.fan_axis
    return cube([s, s, t], [ax-s/2, ay-s/2, z_face])-mf.Manifold.cylinder(t+.2, bore/2, circular_segments=96).translate([ax, ay, z_face-.1])


def hardware_meshes(g: GeometryParams, c: CollectorParams, case: CaseParams = CASE, b: BracketParams = BRACKET) -> dict[str, trimesh.Trimesh]:
    """Named reference meshes in the duct frame (mm) for the preview page: rear_panel (sheet with the slot openings),
    slot_ledge, bracket_A, bracket_B, blank_middle (cover in slot 0, only if CaseParams.covers has 0), slot_covers (covers in
    the other empty slots, only those listed in covers; none in the author's case), screw_heads, screw_shanks, window_bezels (card side bezel + Torx heads). Not printed;
    see CaseParams / BracketParams for the sources. Place a collector on it with `placed`."""
    return manifold_meshes(build_hardware(g, c, case, b).parts)


def manifold_meshes(parts: dict) -> dict[str, trimesh.Trimesh]:
    """{name: Manifold} as {name: trimesh.Trimesh} for the preview page, vertices unmerged (merging breaks touching edges)."""
    out = {}
    for name, m in parts.items():
        raw = m.to_mesh64()
        out[name] = trimesh.Trimesh(np.asarray(raw.vert_properties)[:, :3], np.asarray(raw.tri_verts), process=False)
    return out


# Fit of a collector (duct.cad.exhaust.CollectorSolids) against the hardware

HARD = ('rear_panel', 'slot_ledge', 'bracket_A', 'bracket_B', 'blank_middle', 'slot_covers', 'screw_heads', 'screw_shanks')
# window_bezels (Torx heads) are from a photo, unmeasured: reported, not part of the hard total

def placed(solids, hw: Hardware) -> mf.Manifold:
    """The collector with its flange face on the panel's outer face (its inlet_z is the bracket plane: CFD convention)."""
    return solids.final.translate([0, 0, hw.panel_face-solids.params.inlet_z])


def _samples(m: mf.Manifold, density: float, seed: int, bounds=None) -> np.ndarray:
    raw = m.to_mesh64(); t = trimesh.Trimesh(np.asarray(raw.vert_properties)[:, :3], np.asarray(raw.tri_verts), process=False)
    p, _ = trimesh.sample.sample_surface(t, max(1000, int(t.area*density)), seed=seed)
    if bounds is not None:
        lo, hi = bounds; p = p[np.all((p >= lo) & (p <= hi), axis=1)]
    return p


def _classify(pt, hw: Hardware) -> str:
    q = Point(pt)
    if pt[1] > hw.ledge_bottom: return 'ledge'            # the slot ledge, tabs and screws stand off the panel face here
    if hw.panel_2d.contains(q): return 'flush'            # panel sheet at the panel face
    if not hw.panel_2d.envelope.contains(q): return 'off_panel'
    if hw.plates_2d.contains(q): return 'recessed'        # a bracket or cover plate, one panel thickness behind the face
    return 'open'


def fit_check(solids, g: GeometryParams, case: CaseParams = CASE, b: BracketParams = BRACKET, density: float = 6.0) -> dict:
    """Deterministic fit numbers of a collector mounted flange-to-panel: intersection volume and minimum clearance per
    hardware part, slot-screw position and access (driver or finger column above each head, against collector + fan),
    gasket-path surface classes, magnet footing and vent-window coverage."""
    from scipy.spatial import cKDTree

    from .exhaust import gasket_loops, magnet_pocket, mount_points, section
    c = solids.params; hw = build_hardware(g, c, case, b); case = hw.case; col = placed(solids, hw); dz = hw.panel_face-c.inlet_z
    if getattr(solids, 'clips', None) is not None: col = col+solids.clips.translate([0, 0, dz])   # snap clips: through the panel
    fan = fan_box(c, c.inlet_z+c.plenum_depth+dz, case)
    lo, hi = np.asarray(col.bounding_box()[:3])-20, np.asarray(col.bounding_box()[3:])+20
    cp = _samples(col, density, 1, (lo, hi)); tree = cKDTree(cp)
    parts = {}
    for name, m in hw.parts.items():
        vol = float((col ^ m).volume())
        pp = _samples(m, density, 2, (lo, hi))
        d = float(tree.query(pp)[0].min()) if len(pp) else float('inf')
        parts[name] = dict(intersection_mm3=round(vol, 3), min_clearance_mm=round(0.0 if vol > 1e-3 else d, 2))
    hd, hh = case.head; acc = case.driver_diameter if case.screw == 'pan' else case.finger_diameter
    screws = []
    for s in hw.screws:
        column = _y_cylinder(s['x'], s['z'], s['head_y'][1]+.05, s['head_y'][1]+80, acc)
        screws.append(dict(slot=s['slot'], x=round(s['x'], 2), axis_z_from_panel_face=round(s['z']-hw.panel_face, 2),
                           head_y=[round(v, 2) for v in s['head_y']], outside_case=bool(s['z'] > hw.panel_face),
                           access_column_blocked_mm3=round(float((column ^ union(col, fan)).volume()), 3)))
    cls = []; steps = 0
    for loop in gasket_loops(c):
        centre = loop.buffer(c.gasket_width/2, quad_segs=32).exterior
        lc = [_classify(centre.interpolate(t).coords[0], hw) for t in np.arange(0, centre.length, .5)]
        cls += lc; steps += sum(a != b for a, b in zip(lc, lc[1:]+lc[:1]))   # flush <-> recessed crossings (0.8 mm steps under the foam)
    path = {k: round(.5*cls.count(k), 1) for k in ('flush', 'recessed', 'open', 'ledge', 'off_panel')}
    path['steps'] = steps; path['band'] = gasket_band(c, hw, case)
    mags = []
    if c.mount == 'magnets':
        for p in mount_points(c):
            disc = magnet_pocket(c, p); a = disc.area
            ledge = disc.intersection(box(-1e3, hw.ledge_bottom, 1e3, 1e3)).area; rest = disc.difference(box(-1e3, hw.ledge_bottom, 1e3, 1e3))
            flush = rest.intersection(hw.panel_2d).area; rec = rest.difference(hw.panel_2d).intersection(hw.plates_2d).area
            mags.append(dict(at=[round(v, 2) for v in p], flush=round(flush/a, 3), recessed=round(rec/a, 3), open=round(max(0., 1-(flush+rec+ledge)/a), 3), ledge=round(ledge/a, 3)))
    mouth = section(solids.inner, c.inlet_z+1e-3)
    vents = [dict(window=[round(v, 2) for v in wnd], outside_mouth_mm2=round(box(wnd[0], wnd[2], wnd[1], wnd[3]).difference(mouth).area, 3),
                  behind_panel_ribs_mm2=round(box(wnd[0], wnd[2], wnd[1], wnd[3]).intersection(hw.panel_2d).area, 1),
                  open_outside_mouth_mm2=round(box(wnd[0], wnd[2], wnd[1], wnd[3]).difference(hw.panel_2d).difference(mouth).area, 3))   # the live part
             for wnd in hw.windows]
    return dict(case=dict(screw=case.screw, ledge_depth=case.ledge_depth, lip_down=case.lip_down, lip_up=case.lip_up, panel=case.panel,
                          ledge_bend_radius=case.ledge_bend_radius),
                placement=dict(bracket_plane_z=hw.z_b, panel_face_z=hw.panel_face, collector_shift_mm=round(dz, 3), ledge_bottom_y=hw.ledge_bottom,
                               bracket_top_y=c.bracket_top_y),
                parts=parts, total_intersection_mm3=round(sum(p['intersection_mm3'] for n, p in parts.items() if n in HARD), 3),
                screw_tip_below_ledge_mm=round(hw.ledge_bottom-hw.screws[0]['tip_y'], 2),
                torx_heads_past_panel_face_mm=round(b.torx_head[1]-case.panel, 2),
                screws=screws, gasket_path_mm=path, magnets=mags, vents=vents)


def open_slot_vent_area(solids, g: GeometryParams, case: CaseParams = CASE, b: BracketParams = BRACKET) -> list[dict]:
    """Each open slot (case.open_slots): its chassis opening, the part the collector's flange leaves open at the panel face
    (vent to the room), and whether it lies inside a gasket loop (it would vent into the plenum instead)."""
    from .exhaust import gasket_loops, section
    c = solids.params; hw = build_hardware(g, c, case, b); z0 = c.inlet_z
    foot = shapely.unary_union([section(solids.final, z0+dz) for dz in (.05, c.flange_thickness/2, c.flange_thickness-.05)])
    loops = shapely.unary_union(gasket_loops(c)); out = []
    for k in hw.case.open_slots:
        x0, x1, y0, y1 = hw.openings[k]; q = box(x0, y0, x1, y1); left = q.difference(foot).area
        out.append(dict(slot=k, opening_mm=[x0, x1, y0, y1], area_mm2=round(q.area, 1), open_mm2=round(left, 1), fraction=round(left/q.area, 4),
                        inside_gasket_loop_mm2=round(q.intersection(loops).area, 1)))
    return out


def gasket_band(c: CollectorParams, hw: Hardware, case: CaseParams | None = None) -> dict:
    """Where the full 3 mm groove footprint lands: over open holes (must be 0), over recessed steel (bracket or cover
    plates behind an opening), and its margins: to the nearest open hole, and, along the side bands, to the nearest
    chassis-opening edge (the rib margin). Open slots (case.open_slots): which lie inside a loop (an orifice into the
    plenum), the groove area over them, and the foam's land on steel between a loop and the nearest open slot outside it
    (>= gasket_width: the whole band on steel)."""
    from .exhaust import gasket_loops, gasket_ring
    case = hw.case if case is None else case.for_pitch(hw.case.card_pitch)
    ring = gasket_ring(c); ops = shapely.unary_union([box(o[0], o[2], o[1], o[3]) for o in hw.openings.values()])
    open_ = ops.difference(hw.plates_2d); loops = shapely.unary_union(gasket_loops(c))
    slot_box = {k: box(o[0], o[2], o[1], o[3]) for k, o in hw.openings.items() if k in case.open_slots}
    inside = sorted(k for k, q in slot_box.items() if loops.intersection(q).area > 1e-6)
    outside = shapely.unary_union([q for k, q in slot_box.items() if k not in inside]) if len(inside) < len(slot_box) else None
    y0 = min(o[2] for o in hw.openings.values())+10; y1 = max(o[3] for o in hw.openings.values())-10
    sides = ring.intersection(box(-1e3, y0, 1e3, y1))      # the straight vertical bands, clear of the corners and the top/bottom bands
    bottom = ring.intersection(box(-1e3, -1e3, 1e3, y0-10))
    return dict(over_open_mm2=round(ring.intersection(open_).area, 3), over_recessed_steel_mm2=round(ring.intersection(ops).area, 1),
                margin_to_open_mm=round(ring.distance(open_), 3), side_band_margin_to_openings_mm=round(sides.distance(ops), 3),
                side_bands_over_openings_mm2=round(sides.intersection(ops).area, 3), bottom_band_margin_to_openings_mm=round(bottom.distance(ops), 3),
                open_slots=list(case.open_slots), open_slots_inside_loops=inside,
                groove_over_open_slots_mm2=round(ring.intersection(shapely.unary_union(list(slot_box.values()))).area, 2) if slot_box else 0.0,
                foam_land_to_open_slots_mm=round(loops.distance(outside), 3) if outside is not None else None)


def fit_sweep(solids, g: GeometryParams, cases=None) -> list[dict]:
    """fit_check over case variants: ledge depth, a downward lip at the ledge edge, pan vs thumb screws."""
    cases = cases or [CaseParams(ledge_depth=d, lip_down=l, screw=s, screw_length=n) for d in (10.0, 12.0, 15.0) for l in (0.0, 4.0)
                      for s in ('pan', 'thumb') for n in (6.35, 4.76)]
    rows = []
    for case in cases:
        r = fit_check(solids, g, case, density=3.0)
        rows.append(dict(**r['case'], screw_length=case.screw_length, total_intersection_mm3=r['total_intersection_mm3'],
                         min_clearance_mm=min(p['min_clearance_mm'] for n, p in r['parts'].items() if n in HARD and n != 'rear_panel'),   # the flange sits on the panel
                         access_blocked_mm3=round(sum(s['access_column_blocked_mm3'] for s in r['screws']), 3)))
    return rows


# Bypass: room / case air reaching the collector without crossing the fins

MU, RHO = 1.81e-5, 1.2                  # air at 20 C: Pa s, kg/m3


def slit_flow(width, gap, length, dp, k=1.5):
    """Flow (m3/s) through a thin slit (mm): laminar plane-Poiseuille friction in series with entry + exit losses (k)."""
    W, g, L = width*1e-3, gap*1e-3, length*1e-3
    a, b = 12*MU*L/(W*g**3), k*RHO/2/(W*g)**2          # dp = a Q + b Q^2
    return (-a+np.sqrt(a*a+4*b*dp))/(2*b)


def orifice_flow(area, dp, cd=.6):
    return cd*area*1e-6*np.sqrt(2*dp/RHO)


def effective_area(q, dp):
    """Ideal (Cd = 1) orifice area (mm2) passing q at dp: the yardstick for comparing leak paths with the vent windows."""
    return q/np.sqrt(2*dp/RHO)*1e6


def bypass_leaks(solids, g: GeometryParams, case: CaseParams = CASE, b: BracketParams = BRACKET, gaps=(.1, .3, .5), dp=24.6,
                 q_cards=14.46e-3, vented_open=400.0, gasket_gap=.05) -> dict:
    """Leak paths into the collector that bypass the fins, at plenum suction `dp` (Pa; v27 push-pull CFD: bracketDown
    static -24.6 Pa against the case air, 14.46 L/s through the fins):
    - plate slits: bracket / cover plates rest against the panel's inner face but are not sealed to it; each opening edge
      inside the gasket loop leaks through the plate-to-panel gap (`gaps`, mm; no spec) across the plate's overlap to
      where the plate ends (the 1.9 mm gap between neighbouring brackets, the plate bottom, the ledge corner). Edges
      between two openings of one bracket lead to another opening inside the loop and do not count; edges under the
      gasket band are pressed shut by the foam.
    - open slot inside a gasket loop (no cover fitted): its area inside the loop as an orifice, Cd 0.6.
    - vented middle blank, if one is fitted (0 in case.covers) and inside a loop: `vented_open` mm2 of perforation (typical 35-50 % of an 11 x 90 mm field), Cd 0.6.
    - gasket: `gasket_gap` mm average over the loop (closed-cell foam compressed on flush steel: ~0), and the 0.8 mm
      steps where the gasket crosses an opening edge (a 0.8 x 0.4 mm tunnel across the foam each).
    Returns effective areas (mm2) next to the two 81 x 25 vent windows and the bypass fraction at fixed suction."""
    from shapely.geometry import LineString

    from .exhaust import gasket_loops
    c = solids.params; hw = build_hardware(g, c, case, b); top = c.bracket_top_y; case = hw.case
    inner = shapely.unary_union(gasket_loops(c))                       # inside the grooves' inner edges: foam starts there
    centres = [p.buffer(c.gasket_width/2, quad_segs=32).exterior for p in gasket_loops(c)]
    plates = {k: s for s in [*[(sl, 2) for sl in case.card_slots], *[((k,), 1) for k in case.covers]] for k in s[0]}
    edges = []; open_inside = 0.0; open_in = []
    for k, (x0, x1, y0, y1) in hw.openings.items():
        if inner.intersection(box(x0, y0, x1, y1)).area < 1e-6: continue
        if k not in plates:                                                  # an open slot inside a loop: case air
            open_inside += inner.intersection(box(x0, y0, x1, y1)).area; open_in.append(k); continue
        slots, n = plates[k]
        sx0, sx1 = _span([hw.openings[j] for j in slots]); w = b.width_dual if n == 2 else b.width_single
        h = b.height_dual if n == 2 else b.height_single; lo, hi = (sx0+sx1)/2-w/2, (sx0+sx1)/2+w/2
        for name, line, L in (('left', LineString([(x0, y0), (x0, y1)]), x0-lo if x0 == sx0 else None),
                              ('right', LineString([(x1, y0), (x1, y1)]), hi-x1 if x1 == sx1 else None),
                              ('top', LineString([(x0, y1), (x1, y1)]), top-b.sheet-y1),
                              ('bottom', LineString([(x0, y0), (x1, y0)]), y0-(top-h))):
            W = line.intersection(inner).length
            if L is not None and W > 1e-6: edges.append(dict(slot=k, edge=name, width_mm=round(W, 2), length_mm=round(L, 2)))
    rows = []
    for gap in gaps:
        q = sum(slit_flow(e['width_mm'], gap, e['length_mm'], dp) for e in edges)
        rows.append(dict(path=f'plate slits, {gap} mm gap', q_lps=q*1e3, area_mm2=effective_area(q, dp)))
    qo = orifice_flow(open_inside, dp)
    rows.append(dict(path=f'open slots inside the gasket loops {open_in} ({open_inside:.0f} mm2, Cd 0.6)', q_lps=qo*1e3, area_mm2=effective_area(qo, dp)))
    mid = box(hw.openings[0][0], hw.openings[0][2], hw.openings[0][1], hw.openings[0][3]) if 0 in case.covers else None   # 3-slot pitch only
    qv = orifice_flow(vented_open, dp) if mid is not None and inner.intersection(mid).area > 1 else 0.0
    rows.append(dict(path=f'vented middle blank, if fitted ({vented_open:g} mm2 open)', q_lps=qv*1e3, area_mm2=effective_area(qv, dp)))
    qg = sum(slit_flow(ct.length, gasket_gap, c.gasket_width, dp) for ct in centres)
    rows.append(dict(path=f'gasket, {gasket_gap} mm average gap', q_lps=qg*1e3, area_mm2=effective_area(qg, dp)))
    steps = 0
    for ct in centres:
        cls = [_classify(ct.interpolate(t).coords[0], hw) for t in np.arange(0, ct.length, .5)]; steps += sum(a != b for a, b in zip(cls, cls[1:]+cls[:1]))
    qs = steps*slit_flow(.8, .4, c.gasket_width, dp)
    rows.append(dict(path=f'gasket over {steps} panel steps', q_lps=qs*1e3, area_mm2=effective_area(qs, dp)))
    windows_area = sum((w[1]-w[0])*(w[3]-w[2]) for w in hw.windows)
    for r in rows:
        r.update(q_lps=round(r['q_lps'], 3), area_mm2=round(r['area_mm2'], 1), area_vs_windows=round(r['area_mm2']/windows_area, 4),
                 bypass_fraction=round(r['q_lps']/(r['q_lps']+q_cards*1e3), 4))
    return dict(dp_pa=dp, q_cards_lps=q_cards*1e3, windows_mm2=windows_area, open_slots=list(case.open_slots), open_slots_inside_loops=open_in,
                slit_edges=edges,
                slit_edge_total_mm=round(sum(e['width_mm'] for e in edges), 1), paths=rows)
