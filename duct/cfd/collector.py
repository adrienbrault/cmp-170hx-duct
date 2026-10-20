"""Push-pull exhaust collector in the CFD domain: any air-volume Manifold whose inlet face lies on the
bracket plane (z = L + card_envelope, mm, duct frame) and whose fan face is its flat top, normal +z.

The collector is unioned into the fluid with a short hub-annulus approach past its fan face (the exhaust
twin of the intake approach); the annulus end is the `exhaust` patch, every other collector face is a wall.
"""
from dataclasses import dataclass, replace

import manifold3d as mf
import numpy as np

from ..cad.geometry import cube, cylinder, union
from ..params import GeometryParams
from .domain import DOMAIN, TOL, DomainParams, Rule

PATCH = "exhaust"
CASE_AIR = "caseAir"


@dataclass(frozen=True)
class CaseAir:
    """Chassis slots with neither a card nor a cover (duct.cad.hardware CaseParams.covers; the author's case has none)
    open the case interior to whatever lies past the panel. Under a collector's mouth the exhaust fan draws case air
    through them: each such opening (clipped to the mouth) goes through the panel, with a box of still case air
    upstream whose sides and far face are the `caseAir` patch."""
    depth: float = 20.0                 # mm, still case air upstream of a slot
    margin: float = 2.0                 # mm, that box beyond the open slot in x and y (the panel's inner face around it)


CASE_AIR_BOX = CaseAir()


@dataclass(frozen=True)
class FanFace:
    centre: tuple[float, float]   # mm, x y of the fan axis
    z: float                      # mm, fan face plane
    radius: float                 # mm, largest top-face vertex radius about the centre


def fan_face(collector: mf.Manifold) -> FanFace:
    """The collector's flat top face, taken as the exhaust fan face."""
    raw = collector.to_mesh()
    v = np.asarray(raw.vert_properties)[:, :3]
    z = v[:, 2].max(); top = v[np.abs(v[:, 2]-z) < 1e-6]
    c = (top[:, :2].min(0)+top[:, :2].max(0))/2
    return FanFace((float(c[0]), float(c[1])), float(z), float(np.linalg.norm(top[:, :2]-c, axis=1).max()))


def exhaust_approach(face: FanFace, d: DomainParams = DOMAIN, annulus: tuple[float, float] | None = None) -> mf.Manifold:
    """Hub annulus of depth approach_depth past the fan face; outer radius the blade tip, capped by the face. `annulus`:
    the exhaust fan's (hub, tip) radii, mm (None: the domain's, the intake fan's)."""
    hub, tip = annulus or (d.hub_radius, d.approach_radius)
    r = min(tip, face.radius)
    ring = (cylinder(r, d.approach_depth+.01, face.z-.01)
            - cylinder(hub, d.approach_depth+.01, face.z-.01))
    return ring.translate([face.centre[0], face.centre[1], 0])


def parts(g: GeometryParams, collector: mf.Manifold, d: DomainParams = DOMAIN,
          room=None, annulus: tuple[float, float] | None = None) -> tuple[tuple[mf.Manifold, ...], tuple[Rule, ...]]:
    """Extra solids and patch rules for case.CaseOptions: the exhaust annulus end becomes `exhaust` (or, with a
    disk.RoomParams `room`, a still-air room past it whose far field is `exhaust`); all faces at or past the bracket
    plane (collector walls, the plenum floor around the ports, the room's back wall) are walls. `annulus`: as
    exhaust_approach."""
    from . import disk  # noqa: PLC0415
    face = fan_face(collector)
    exit_z = (g.chamber_length+d.card_envelope)*.001
    out_z = (face.z+d.approach_depth)*.001
    solids = (collector, exhaust_approach(face, d, annulus))
    if room is None:
        rules = ((PATCH, lambda t: np.abs(t[:, :, 2]-out_z).max(1) < TOL),)
    else:
        solids += (disk.exhaust_room(face.centre, face.z+d.approach_depth, room),)
        rules = disk.exhaust_rules(out_z)
    return solids, rules+(("walls", lambda t: t[:, :, 2].min(1) >= exit_z-TOL),)


def mouth(placed: mf.Manifold, panel_face_z: float):
    """The collector's air section just past the panel's outer face (shapely, mm)."""
    from ..cad.exhaust import section
    return section(placed, panel_face_z+1e-3)


def open_slots(g: GeometryParams, placed: mf.Manifold, panel, d: DomainParams = DOMAIN,
               m: CaseAir = CASE_AIR_BOX) -> tuple[tuple[mf.Manifold, ...], tuple[Rule, ...], list[dict]]:
    """Solids, patch rules and a summary per slot for the uncovered chassis slots under the collector's mouth.
    `placed`: the collector on the rear panel's outer face; `panel`: duct.cad.hardware.CaseParams (its `covers` are
    closed: CaseParams.open_slots). Each slot's opening ∩ the mouth goes through the panel; upstream, a box of still case air (clear of the
    card ports) whose sides and far face are the `caseAir` patch, at ambient total pressure like the room the intake fan
    draws from. Nothing for a mouth that stays off the empty slots (a collector sealing per card)."""
    from shapely.geometry import box
    from shapely.geometry.polygon import orient

    from ..cad import hardware
    from ..params import CollectorParams
    panel = panel.for_pitch(g.pitch)   # the slot layout follows the duct's card pitch
    ops = hardware.openings(replace(CollectorParams(), card_pitch=g.pitch), panel)
    z = g.chamber_length+d.card_envelope; zp = z+panel.panel
    mouth_ = mouth(placed, zp); ports = [r for _, _, r in g.port_boxes]
    solids, masks, info = (), [], []
    for k in panel.open_slots:
        x0, x1, y0, y1 = ops[k]
        open_ = box(x0, y0, x1, y1).intersection(mouth_)
        if open_.area < 1.0:   # mm²: off the mouth (or a sliver along its edge)
            continue
        assert open_.geom_type == "Polygon", (k, open_.geom_type)
        ring = np.asarray(orient(open_, 1).exterior.coords)[:-1]
        prism = mf.Manifold.extrude(mf.CrossSection([ring], mf.FillRule.EvenOdd), zp-z+.005).translate([0, 0, z-.005])
        bx0, by0, bx1, by1 = open_.buffer(m.margin, join_style="mitre").bounds
        assert all(bx1 < px0 or px1 < bx0 for px0, px1, _, _ in ports), f"case-air box of slot {k} reaches a card port"
        air = cube([bx1-bx0, by1-by0, m.depth], [bx0, by0, z-m.depth])   # ends on the bracket plane; the prism overlaps it
        solids += (air, prism)
        masks.append((np.array([bx0, by0])*.001-TOL, np.array([bx1, by1])*.001+TOL))
        info.append(dict(slot=k, opening_mm=[x0, x1, y0, y1], open_mm=[list(map(float, v)) for v in ring],
                         open_area_m2=open_.area*1e-6, case_air_box_mm=[bx0, bx1, by0, by1, z-m.depth, z]))
    if not info:
        return (), (), []
    zlo, zm = (z-m.depth)*.001-TOL, z*.001-TOL

    def inside(t):
        upstream = (t[:, :, 2].min(1) > zlo) & (t[:, :, 2].min(1) < zm)
        return upstream & np.any([np.all((t[:, :, :2] >= lo) & (t[:, :, :2] <= hi), axis=(1, 2)) for lo, hi in masks], axis=0)
    return solids, ((CASE_AIR, inside),), info


def placeholder(g: GeometryParams, d: DomainParams = DOMAIN, width: float = 106.0, depth: float = 104.0,
                corner: float = 10.0, plenum: float = 10.0, transition: float = 30.0,
                face_radius: float = 58.0) -> mf.Manifold:
    """Development stand-in for duct.cad.exhaust: a rounded-rectangle plenum over both cards' ports
    (x ±width/2, y centred on the port span), `plenum` mm straight, then a `transition` mm loft
    (convex hull) to a round fan face on the card centreline."""
    z0 = g.chamber_length+d.card_envelope
    ys = [y for _, _, (_, _, y0, y1) in g.port_boxes for y in (y0, y1)]
    yc = (min(ys)+max(ys))/2
    corners = [(sx*(width/2-corner), yc+sy*(depth/2-corner)) for sx in (-1, 1) for sy in (-1, 1)]
    post = lambda x, y, h, z: cylinder(corner, h, z).translate([x, y, 0])  # noqa: E731
    box = mf.Manifold.batch_hull([post(x, y, plenum, z0) for x, y in corners])
    loft = mf.Manifold.batch_hull([post(x, y, .01, z0+plenum-.01) for x, y in corners]
                                  + [cylinder(face_radius, .01, z0+plenum+transition-.01).translate([0, yc, 0])])
    return union(box, loft)


@dataclass(frozen=True)
class PlugAir:
    """The plug collector in the recessed bay (duct.cad.plug, CASE_FRACTAL): between the bracket plates and the plug face
    (plug_placement above the bracket plane: the bars' crowns + foam) an air layer per card (plug_layer); the collector's
    mouths open from its top. Slots -3 / 0 / +3 lie under the plug's solid face: no case air. The released seal ends the
    layer at the top dam (duct.cad.plug.top_dam, foam on the bracket plates' top band). For sensitivity only (`slit`: the
    superseded lateral top seal, no dam), the openings above each card's bracket tops then reach the mouths and draw case
    air: `slit_mm2` in all, split per card over its two slot openings, with a still case-air box upstream."""
    slit: bool = False
    slit_mm2: float = 130.0             # both cards (photo estimate: 2 slots x ~13 mm x ~2.5 mm per card)
    depth: float = 20.0                 # mm, still case air upstream of each slit
    margin: float = 2.0


PLUG_AIR = PlugAir()
# kind -> options (base: the duct.params collector, default COLLECTOR_PLUG_BASE); any kind takes CollectorParams overrides
# after a colon: "plug:plenum_depth=55,corner_end=30". plug140: the plug with the 140 mm pull fan (P14 Pro Reverse).
PLUG_KINDS = {"plug": dict(hub=True), "plug-nohub": dict(hub=False), "plug-slit": dict(hub=True, slit=True),
              "plug140": dict(hub=True, base="COLLECTOR_PLUG_140")}


def split_kind(kind: str) -> tuple[str, dict]:
    """("plug", {"plenum_depth": 55.0}) from "plug:plenum_depth=55": the base kind and CollectorParams overrides (numbers)."""
    base, _, rest = kind.partition(":")
    over = {}
    for kv in filter(None, (t.strip() for t in rest.split(","))):
        k, _, v = kv.partition("=")
        over[k.strip()] = float(v)
    return base, over


def plug_collector(g: GeometryParams, d: DomainParams = DOMAIN, hub: bool = True, base: str = "COLLECTOR_PLUG_BASE", **over):
    """(plug CollectorParams, the case) for duct `g`: duct.params `base` (COLLECTOR_PLUG_BASE; hub fairing off with
    hub=False), with CollectorParams overrides `over` applied by plug_params (absolute: plenum_depth=55 is the plug's plenum
    depth)."""
    from .. import params
    from ..cad import plug
    from ..cad.hardware import CASE_FRACTAL
    base = getattr(params, base) if hub else replace(getattr(params, base), hub_fairing=False)
    case = CASE_FRACTAL.for_pitch(g.pitch)
    return plug.plug_params(base.for_duct(g, d.card_envelope), case, **over), case


def plug_layer(g: GeometryParams, c, case, d: DomainParams = DOMAIN, dam: bool = True) -> mf.Manifold:
    """The air between the bracket plates (the bracket plane) and the plug face, per card, less the divider bars (mm).
    In x between the bounding bars' crown foam: side walls 0.5 mm past their feet. In y from the collector's mouths' lower
    end to the top dam's inner edge (`dam`; without it, the plug's top). Left out: the dead pocket under the plug's solid
    face below the mouths (down to the floor band's foam; the screen mesh diverged in it, on the 1 mm gaps over the bar
    crowns), the panel floor (between the bounding bars it is all slot openings but for 0.035 mm strips beside the bar feet:
    7.0 mm bars over 7.07 mm ribs), and the bezels and Torx heads on the plates. Above the mouths the 1 mm gap over a mid
    bar's crown is closed."""
    from ..cad import exhaust as ex, hardware, plug
    z = g.chamber_length+d.card_envelope; fz = plug.plug_placement(c, case)
    assert abs(hardware.bracket_z(g, case)-z) < 1e-6, "the recess model's bracket plane is not the domain's"
    mouths = ex.card_mouths(c); y0, my1 = min(m[2] for m in mouths), max(m[3] for m in mouths)
    y1 = plug.top_dam(c, case)[0] if dam else c.plug_outline[3]
    bw = case.divider[0]
    e = bw/2+.5   # the side walls 0.5 mm past the bounding bars' feet (their crown foam), over the outer slot openings
    boxes = [cube([b-a-2*e, y1-y0, fz], [a+e, y0, z]) for a, b in plug.bounding_bars(c)]
    mid = [x for x in plug.divider_x(c) if any(a+bw/2 < x < b-bw/2 for a, b in plug.bounding_bars(c))]
    bars = [plug.build_recess_hardware(g, c, case)["parts"]["divider_bars"]]
    bars += [cube([bw, y1+1-my1, fz+.02], [x-bw/2, my1, z-.01]) for x in mid]
    return mf.Manifold.batch_boolean(boxes, mf.OpType.Add)-mf.Manifold.batch_boolean(bars, mf.OpType.Add)


def plug_slits(g: GeometryParams, c, case, d: DomainParams = DOMAIN, m: PlugAir = PLUG_AIR):
    """The slits above each card's bracket tops (no top dam: inside a lateral top seal) with a still case-air box upstream:
    (solids, rules, info). Each card gets slit_mm2 / 2 over its two slot openings, up to just under the plug's top (the
    real slits run from the bracket top, 52.35, to the recess wall; the model keeps their area and moves them ~1 mm down)."""
    from ..cad import plug
    z = g.chamber_length+d.card_envelope; ports = [r for _, _, r in g.port_boxes]
    ops = plug.slot_openings_x(c); solids, masks, info = (), [], []
    e = case.divider[0]/2+.75   # inside plug_layer's side walls (0.5 mm past the bar feet)
    for a, b in plug.bounding_bars(c):
        mine = [(max(x0, a+e), min(x1, b-e)) for x0, x1 in ops if a < x0 and x1 < b]
        h = m.slit_mm2/2/sum(x1-x0 for x0, x1 in mine)
        for x0, x1 in mine:   # ending 0.25 mm short of the plug's top, so wholly under the layer (the area kept)
            y1 = c.plug_outline[3]-.25; y0 = y1-h
            prism = cube([x1-x0, h, 1.0+.01], [x0, y0, z-1.0])
            bx0, by0, bx1, by1 = x0-m.margin, y0-m.margin, x1+m.margin, y1+m.margin
            assert all(by0 > py1 or bx1 < px0 or px1 < bx0 for px0, px1, _, py1 in ports), "slit case-air box reaches a card port"
            solids += (cube([bx1-bx0, by1-by0, m.depth], [bx0, by0, z-1.0-m.depth]), prism)
            masks.append((np.array([bx0, by0])*.001-TOL, np.array([bx1, by1])*.001+TOL))
            info.append(dict(slit_mm=[x0, x1, y0, y1], area_mm2=(x1-x0)*h))
    zlo, zm = (z-1.0-m.depth)*.001-TOL, (z-1.0)*.001+TOL

    def inside(t):
        up = (t[:, :, 2].min(1) > zlo) & (t[:, :, 2].max(1) < zm)
        return up & np.any([np.all((t[:, :, :2] >= lo) & (t[:, :, :2] <= hi), axis=(1, 2)) for lo, hi in masks], axis=0)
    return solids, ((CASE_AIR, inside),), info


def plug_panel(g: GeometryParams):
    """The rear panel for a plug case (cfd.bracket.BracketWindow.panel): CASE_FRACTAL with every empty slot covered. The plug's
    solid face covers slot 0; -3 / +3 are open, but to the room outside the plug's crown-foam seal, off the duct's flow path,
    so a cover stands in for them too. Its open strips join the windows to the plug's air layer."""
    from ..cad.hardware import CASE_FRACTAL
    return CASE_FRACTAL.for_pitch(g.pitch).covered()


def is_plug(kind: str) -> bool:
    return split_kind(kind)[0] in PLUG_KINDS


def plug_fan(g: GeometryParams, kind: str = "plug", d: DomainParams = DOMAIN):
    """The plug kind's exhaust fan (duct.cfd.fan.for_collector of its CollectorParams)."""
    from . import fan
    base, over = split_kind(kind); o = PLUG_KINDS[base]
    return fan.for_collector(plug_collector(g, d, o["hub"], o.get("base", "COLLECTOR_PLUG_BASE"), **over)[0])


def plug_air(g: GeometryParams, d: DomainParams = DOMAIN, kind: str = "plug") -> tuple[mf.Manifold, str, tuple, tuple, list]:
    """kind 'plug' (released: top dam, no slits) / 'plug-nohub' / 'plug-slit' (no dam, the slits draw case air) / 'plug140'
    (COLLECTOR_PLUG_140: the 140 mm pull fan), each with
    optional CollectorParams overrides ("plug:plenum_depth=55"): (collector air with its layer, given relative to the panel
    face as CaseOptions expects, source, extra solids, extra rules, slit info)."""
    from ..cad.exhaust import build_collector
    from ..cad import plug
    kind_, over = split_kind(kind); o = PLUG_KINDS[kind_]; name = o.get("base", "COLLECTOR_PLUG_BASE")
    c, case = plug_collector(g, d, o["hub"], name, **over)
    slit = o.get("slit", PLUG_AIR.slit)
    inner = build_collector(c).inner.translate([0, 0, plug.plug_placement(c, case)])
    air = (inner+plug_layer(g, c, case, d, dam=not slit)).translate([0, 0, -case.panel])   # CaseOptions puts it on the panel face
    # (with the bracket's panel = plug_panel(g): CASE_FRACTAL, every empty slot covered)
    solids, rules, info = plug_slits(g, c, case, d) if slit else ((), (), [])
    src = (f"duct.cad.plug {name}{'' if o['hub'] else ' without the hub fairing'}"
           f"{''.join(f', {k} {v:g}' for k, v in over.items())} in CASE_FRACTAL (photo estimates)")
    seal = f", no top dam: case-air slits {sum(i['area_mm2'] for i in info):.0f} mm2" if info else ", top dam"
    return air, src+seal, solids, rules, info


KINDS = ("auto", "v2", "v3", "v3l", "v4a", "v4b", "v1", "bare", "placeholder", *PLUG_KINDS)
PRESET = {"auto": "COLLECTOR_V2", "v2": "COLLECTOR_V2", "v3": "COLLECTOR_V3", "v3l": "COLLECTOR_V3L", "v4a": "COLLECTOR_V4A",
          "v4b": "COLLECTOR_V4B", "v1": "COLLECTOR_V1"}


def default(g: GeometryParams, d: DomainParams = DOMAIN, kind: str = "auto") -> tuple[mf.Manifold, str]:
    """The collector air volume, inlet on the bracket plane (CaseOptions places it on the rear panel), and its source:
    duct.cad.exhaust's COLLECTOR_V2 (kind "auto" or "v2"), COLLECTOR_V3 / COLLECTOR_V3L / COLLECTOR_V4A / COLLECTOR_V4B,
    the superseded COLLECTOR_V1 (it collides with the slot ledge, bracket tabs and screws, duct.cad.hardware), the bare
    pull fan gasketed onto the panel (duct.cad.exhaust.bare_fan_air: its 1.2 mm gasket gap past the panel face; frame
    centred in x like v2), or the development placeholder ("auto" falls back to it without duct.cad.exhaust). Every
    preset is laid out for duct `g` (CollectorParams.for_duct: its card pitch, so 5-slot or 4-slot, and bracket plane)."""
    assert kind in KINDS or is_plug(kind), kind
    if is_plug(kind):
        air, src, *_ = plug_air(g, d, kind)
        return air, src
    if kind != "placeholder":
        try:
            from ..cad import exhaust
            from .. import params
        except ImportError:
            assert kind == "auto", f"collector {kind}: duct.cad.exhaust not importable"
        else:
            if kind == "bare":
                from ..cad.hardware import CASE
                c = params.COLLECTOR_V2.for_duct(g, d.card_envelope)
                air, _ = exhaust.bare_fan_air(c, gap=2.0-CASE.panel)
                return air, "duct.cad.exhaust bare_fan_air (COLLECTOR_V2 fan axis x)"
            name = PRESET[kind]
            if not hasattr(params, name):
                raise ValueError(f"collector {kind}: duct.params has no {name} yet")
            c = getattr(params, name).for_duct(g, d.card_envelope)
            return exhaust.build_collector(c).inner, f"duct.cad.exhaust {name}"
    return placeholder(g, d), "placeholder"
