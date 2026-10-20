"""Write an OpenFOAM porousSimpleFoam case for a duct: fluid surface, mesh dictionaries, porous zones, BCs.

templates/case/ holds the dictionaries; `$name` placeholders are filled with string.Template.
Generated here: triSurface/flow.stl, topoSetDict, porosityProperties, thermalProperties, case.json.

Push-pull: a collector air volume over the bracket plane carries the exhaust fan (`pull_rpm`) on its
fan face, and each card's bracket grille is a thin Darcy-Forchheimer slab in its ports. Those cases put
the background z grid on known planes (`Planes`) so the slab thickness is exact and per-card
faceZones can cut the ports; the default single-fan case is generated exactly as before.
"""
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from string import Template

import manifold3d as mf
import numpy as np

from ..cad.geometry import build_duct
from ..params import GeometryParams
from . import bracket as bracket_
from . import collector as collector_
from . import disk, domain, fan, foamdict, porous
from .domain import DOMAIN, DomainParams, Rule
from .porous import FINS, FinModel

TEMPLATE = Path(__file__).resolve().parents[2]/"templates/case"
HALF_WIDTH = 70.0                       # mm, background block spans x, y in ±HALF_WIDTH
BLOCK_Z = (7.0, 10.0)                   # mm, block margin below the approach start and past the card exits
LOCATION_IN_MESH = (-.03, -.01, .02)    # m, inside card 0's branch
# Level-2 refinement over the bay shoulders: x ranges from each card centre (at the 3-slot pitch: x -38..-6 and 22..54 mm),
# y range, z from 2 mm to the seat face.
SHOULDER_DX = ((-7.52, 24.48), (-8.48, 23.52))
SHOULDER_Y = (20.0, 60.0)
EXIT_SLAB = .2                          # mm, half-thickness of the cardExit selection box; snapped exit faces lie within .06 mm of the plane
SEAT_UP = 1.0                           # mm, the seatUp station (Planes.duct_stations) at most this far before the seat face
GRILLE_SLAB = 12.0                      # mm, target grille slab thickness: a 1-2 cell slab loses ~20 % of its jump at the
                                        # zone interfaces (collocated SIMPLE), 12 mm keeps that small
THERMAL = dict(ny=24, nz=60, baseThickness=.002, copperK=porous.COPPER_K, power=250, inletT=298.15, rhoCp=1206)
# Case air at the open middle slot: ambient total pressure, like the intake far field (inflow at the intake's T).
CASE_AIR_BC = dict(p="{type totalPressure; p0 uniform 0; value uniform 0;}",
                   U="{type pressureInletOutletVelocity; value uniform (0 0 0);}",
                   k="{type inletOutlet; inletValue uniform .01; value uniform .01;}",
                   omega="{type inletOutlet; inletValue uniform 10; value uniform 10;}",
                   nut="{type calculated; value uniform 0;}",
                   T=f"{{type inletOutlet; inletValue uniform {THERMAL['inletT']:.9g}; value uniform {THERMAL['inletT']:.9g};}}")


@dataclass(frozen=True)
class CaseOptions:
    base_cell: float = 4.0              # mm, background mesh; surfaces refine to level 1
    rpm: float = 2500.0                 # intake fan; 0: no intake fan, the inlet is open to ambient (needs pull_rpm)
    fans: int = 1                       # intake fans stacked in series
    stack_efficiency: float = fan.STACK_EFFICIENCY
    direction: str = "push"             # push: fan at the inlet blows in; pull: it draws out
    shoulder_refine: bool = False       # level-2 boxes over the bay shoulders (rounding-study meshes)
    wall_layers: int = 3                # snappy layers on the walls; 0: none (screening meshes, duct.cfd.profiles)
    cells_between_levels: int = 3       # snappy nCellsBetweenLevels
    domain: DomainParams = DOMAIN
    fins: FinModel = FINS
    # Generic seam: solids unioned into the fluid, and patch rules run before the default ones.
    extra_solids: tuple[mf.Manifold, ...] = field(default=(), compare=False)
    extra_rules: tuple[Rule, ...] = ()
    # Push-pull: collector air volume (duct frame, mm; see duct.cfd.collector), exhaust fan on its face.
    collector: mf.Manifold | None = field(default=None, compare=False)
    collector_source: str = ""          # what the collector is (duct.cfd.collector.default's source), for case.json
    pull_rpm: float | None = None       # exhaust fan; None with a collector: its face is a plain static-0 outlet
    # The exhaust fan's model and annulus (duct.cfd.fan.for_collector); None: the P12 Pro on the domain's annulus (the
    # intake fan's: every 120 mm collector).
    exhaust_fan: fan.FanModel | None = None
    # The cards' rear bracket: a solid plate with one window per card (duct.cfd.bracket), in every setup. None: the
    # ports open straight onto the outlet patches (the reference/legacy cases).
    bracket: bracket_.BracketWindow | None = bracket_.BRACKET
    # Optional perforated-plate slab in the ports (open-area ratio); 1: none. Superseded by the bracket window.
    grille_open_area: float = 1.0
    # Fan model: "boundary" (fan curves on the inlet/exhaust patches) or "disk" (actuator-disk baffles inside the
    # flow, with still-air rooms upstream of the intake and downstream of the exhaust; duct.cfd.disk).
    fan_model: str = "boundary"
    swirl: float = 0.0                  # disk model: multiple of the Euler-equation swirl, sign = rotor sense; 0: none
    room: disk.RoomParams = disk.ROOM

    def __post_init__(self):
        assert self.direction in ("push", "pull"), self.direction
        assert self.pull_rpm is None or self.collector is not None, "pull_rpm needs a collector"
        assert self.collector is None or self.direction == "push", "a collector takes the push direction"
        assert self.rpm > 0 or self.pull_rpm, "no fan: set rpm or pull_rpm"
        assert self.fan_model in ("boundary", "disk"), self.fan_model
        assert self.fan_model == "disk" or not self.swirl, "swirl needs the disk fan model"
        assert self.fan_model == "boundary" or self.direction == "push", "the disk model takes the push direction"

    @property
    def grille(self) -> float | None:
        """Effective grille open area, None when there is no grille."""
        return None if self.grille_open_area >= 1 else self.grille_open_area

    @property
    def aligned(self) -> bool:
        """Bracket, grille, collector and disk cases need the background z grid on known planes."""
        return self.collector is not None or self.grille is not None or self.disk or self.bracket is not None

    @property
    def disk(self) -> bool:
        return self.fan_model == "disk"

    @property
    def panel_thickness(self) -> float:
        """mm from the bracket plane to the rear panel's outer face; 0 without a bracket or panel."""
        return self.bracket.panel_thickness if self.bracket is not None else 0.0

    @property
    def pull_model(self) -> fan.FanModel:
        return self.exhaust_fan or fan.P12_PRO

    @property
    def exhaust_annulus(self) -> tuple[float, float] | None:
        """(hub, tip) mm of the exhaust fan; None: the domain's (DomainParams hub_radius, approach_radius)."""
        f = self.exhaust_fan
        return None if f is None else (f.hub_radius*1e3, f.tip_radius*1e3)

    @property
    def placed_collector(self) -> mf.Manifold | None:
        """`collector` (given with its inlet on the bracket plane) with its flange on the rear panel's outer face, where
        duct.cad.hardware.placed mounts it; the panel's open strips join it to the bracket windows."""
        if self.collector is None or not self.panel_thickness:
            return self.collector
        return self.collector.translate([0, 0, self.panel_thickness])


@dataclass(frozen=True)
class Planes:
    """Background z grid (mm) for aligned cases: cell faces at exit_z - delta - k·base_cell, delta chosen so the
    bracket plate faces (on the refined lattice around the windows) and the card porous-zone ends (level 1) stay
    clear of every face and cell centre (>= a quarter lattice): castellation and boxToCell zones must not hinge
    on a centre lying on a surface or a zone edge."""
    delta: float
    base: float
    exit_z: float
    entry_k: int                        # second grid plane upstream of the card porous zones
    slab_cells: int                     # grille slab thickness in base cells (0: no slab)
    bracket: bool = False

    def at(self, k: int) -> float:
        return self.exit_z-self.delta-k*self.base

    @property
    def grille(self) -> tuple[float, float]:
        """Grille slab: slab_cells base cells, ending two base cells upstream of the bracket plane."""
        return self.at(2+self.slab_cells), self.at(2)

    @property
    def zones(self) -> dict[str, float]:
        """Per-card measurement faceZones: card entry, upstream of the grille slab / bracket (cardBracket) and the
        per-card flux cut (cardExit). Each sits a base cell clear of porous zones: a face value interpolates the
        two cells beside it."""
        return {"cardEntry": self.at(self.entry_k), "cardBracket": self.at(3+self.slab_cells if self.slab_cells else 2),
                "cardExit": self.at(1)}

    @property
    def stations(self) -> dict[str, float]:
        """Whole-section faceZones: bracketDown, a base cell past the bracket plane (collector or still air)."""
        return {"bracketDown": self.at(-1)} if self.bracket else {}

    def duct_stations(self, chamber_length: float) -> dict[str, float]:
        """Whole-section faceZones inside the duct: seatUp, the grid plane at or just upstream of 1 mm before the seat
        face (only the two branch passages cross it), which splits the inlet-to-cardEntry total-pressure drop into the
        duct's own loss and the card face's contraction into the ports."""
        return {"seatUp": self.at(math.ceil((self.exit_z-self.delta-(chamber_length-SEAT_UP))/self.base))}


def planes(g: GeometryParams, o: CaseOptions) -> Planes:
    b, L = o.base_cell, g.chamber_length
    exit_z = L+o.domain.card_envelope
    fin0, fin1 = L+o.fins.start*1e3, L+(o.fins.start+o.fins.length)*1e3
    # (plane, lattice of faces and centres at its refinement level): level 1 everywhere, the bracket box finer
    fine = b/2**(o.bracket.refine+1) if o.bracket else b/4
    items = [(exit_z, fine), (fin0, b/4), (fin1, b/4)]
    if o.bracket:
        items.append((exit_z-o.bracket.thickness, fine))
    if o.panel_thickness:
        items.append((exit_z+o.panel_thickness, fine))

    def clearance(delta: float) -> float:
        return min(abs((exit_z-delta-z+lat/2) % lat-lat/2)/lat for z, lat in items)
    delta = max((b*i/32 for i in range(32)), key=lambda dl: (round(clearance(dl), 9), -dl))
    if clearance(delta) < .25-1e-9:
        raise ValueError(f"no grid offset clears the bracket plane and fin zone ends at base cell {b}")
    entry_k = math.ceil((exit_z-delta-fin0)/b)+1
    # bracketDown needs a grid plane past the bracket and short of the collector's fan face (a bare fan on the panel
    # leaves none: its face is 2 mm out, the plane would land on the exhaust disk)
    station = o.bracket is not None and (o.collector is None or exit_z-delta+b < collector_.fan_face(o.placed_collector).z)
    p = Planes(delta, b, exit_z, entry_k, max(1, round(GRILLE_SLAB/b)) if o.grille else 0, station)
    if not (L+b/8 < p.at(entry_k) < fin0-b/2 and fin1+b/2 < p.zones["cardBracket"]):
        raise ValueError(f"base cell {b} too coarse to fit the measurement planes and grille between the fins and the bracket")
    return p


def header(obj: str, cls: str = "dictionary") -> str:
    return f"FoamFile {{version 2.0; format ascii; class {cls}; object {obj};}}\n"


def vec(v) -> str:
    return "("+" ".join(f"{x:.9g}" for x in v)+")"


def _block(g: GeometryParams, o: CaseOptions, bounds) -> tuple[float, float, float]:
    """Background block (half-width, z0, z1) in mm. Aligned cases put z faces on `planes` and grow the
    half-width in base-cell steps (keeping the x/y faces where they were) to clear the collector."""
    L = g.chamber_length; d = o.domain
    if not o.aligned:
        return HALF_WIDTH, -(d.approach_depth+BLOCK_Z[0]), L+d.card_envelope+BLOCK_Z[1]
    p = planes(g, o)
    lo, hi = np.asarray(bounds[:3]), np.asarray(bounds[3:])  # Manifold.bounding_box(): min xyz, max xyz
    w = HALF_WIDTH
    while w < max(np.abs(lo[:2]).max(), np.abs(hi[:2]).max())+BLOCK_Z[0]:
        w += o.base_cell
    k0 = math.ceil((p.exit_z-p.delta-min(lo[2], -d.approach_depth)+BLOCK_Z[0])/o.base_cell)
    k1 = math.ceil((hi[2]+BLOCK_Z[1]-p.exit_z+p.delta)/o.base_cell)
    return w, p.at(k0), p.at(-k1)


def _template_values(g: GeometryParams, o: CaseOptions, patches: list[str], bounds=None,
                     exhaust_area: float | None = None, refine_xy=()) -> dict[str, str]:
    """`refine_xy`: (x0, y0, x1, y1) mm rectangles the bracket refinement box also spans (the collector's mouth and
    the open slots' case air, so the 0.8 mm panel around them is resolved)."""
    L = g.chamber_length
    half, z0, z1 = _block(g, o, bounds)
    n = lambda length: round(length/o.base_cell)  # noqa: E731
    boxes = regions = ""
    if o.shoulder_refine:
        shoulders = [(cx+d0, cx+d1) for cx, (d0, d1) in zip(g.card_x, SHOULDER_DX)]
        boxes = "\n".join(f"shoulder{i} {{type searchableBox; min {vec([x0*.001, SHOULDER_Y[0]*.001, .002])}; "
                          f"max {vec([x1*.001, SHOULDER_Y[1]*.001, L*.001])};}}" for i, (x0, x1) in enumerate(shoulders))
        regions = " ".join(f"shoulder{i} {{mode inside; levels ((1e15 2));}}" for i in range(len(shoulders)))
    if o.bracket is not None:
        lo, hi = bracket_.refinement(g, o.bracket, o.domain)
        for x0, y0, x1, y1 in refine_xy:
            lo[:2] = [min(lo[0], (x0-3)*.001), min(lo[1], (y0-3)*.001)]
            hi[:2] = [max(hi[0], (x1+3)*.001), max(hi[1], (y1+3)*.001)]
        boxes += f"\nbracket {{type searchableBox; min {vec(lo)}; max {vec(hi)};}}"
        regions += f" bracket {{mode inside; levels ((1e15 {o.bracket.refine}));}}"
    w = f"{half*.001:.9g}"
    fan_dir = "in" if o.direction == "push" else "out"
    ambient = "{type totalPressure; p0 uniform 0; value uniform 0;}"
    far = ({"inlet"} if o.disk else set()) | ({"exhaust"} if o.disk or (o.bracket and o.collector is None) else set())
    d = o.domain
    if o.rpm == 0 or o.disk:
        inlet = ambient
    else:
        area = math.pi*(d.approach_radius**2-d.hub_radius**2)*1e-6
        inlet = fan.fan_pressure_bc(o.rpm, o.fans, o.stack_efficiency, direction=fan_dir, area=area)
    if o.pull_rpm and o.disk:
        outlet = ambient
    elif o.pull_rpm:
        outlet = fan.fan_pressure_bc(o.pull_rpm, direction="out", area=exhaust_area, model=o.pull_model)
    elif "exhaust" in patches:  # still air behind the bracket, or a fan-less collector: far field at ambient
        outlet = ambient
    elif o.direction == "push":
        outlet = "{type fixedValue; value uniform 0;}"
    else:
        outlet = "{type totalPressure; p0 uniform 0; value uniform 0;}"
    return dict(
        x0="-"+w, x1=w, y0="-"+w, y1=w, z0=f"{z0*.001:.9g}", z1=f"{z1*.001:.9g}",
        nx=str(n(2*half)), ny=str(n(2*half)), nz=str(n(z1-z0)),
        refinementBoxes=boxes, refinementRegions=regions,
        surfaceRegions=" ".join(f"{p} {{name {p};}}" for p in patches),
        patchRegions=" ".join(f"{p} {{level {'(0 0)' if p in far else '(1 1)'}; "
                              "patchInfo {type patch;}}" for p in patches if p != "walls"),
        locationInMesh=vec(LOCATION_IN_MESH),
        inletPlaneZ=f"{-.003:.9g}", portPlaneZ=f"{(L+260)*.001:.9g}",
        inletPressure=inlet, outletPressure=outlet,
        outletPatch=collector_.PATCH if "exhaust" in patches else '"outlet(Left|Right)"',
        U0="(0 0 1)" if o.direction == "push" else "(0 0 -1)",
        inletT=f"{THERMAL['inletT']:.9g}",
        inletK="{type inletOutlet; inletValue uniform .01; value uniform .01;}" if o.disk else "{type fixedValue; value uniform .01;}",
        inletOmega="{type inletOutlet; inletValue uniform 10; value uniform 10;}" if o.disk else "{type fixedValue; value uniform 10;}",
    )


def _card_rect(g: GeometryParams, card: int) -> tuple[list[float], list[float]]:
    """x y bounding rectangle (mm) of a card's ports, 1 mm margin."""
    rects = [r for c, _, r in g.port_boxes if c == card]
    return ([min(r[0] for r in rects)-1, min(r[2] for r in rects)-1],
            [max(r[1] for r in rects)+1, max(r[3] for r in rects)+1])


def grille_zones(g: GeometryParams, o: CaseOptions) -> list[dict]:
    """Per-card grille slab: name, box (m), thickness (m), K and the axial Forchheimer coefficient K/t."""
    if o.grille is None:
        return []
    z0, z1 = planes(g, o).grille
    K = porous.perforated_plate_k(o.grille)
    out = []
    for card in range(len(g.card_x)):
        lo, hi = _card_rect(g, card)
        out.append(dict(zone=f"grille{card}", side=card, open_area=o.grille, K=K, thickness=(z1-z0)*.001,
                        F=K/((z1-z0)*.001), box=[[lo[0]*.001, lo[1]*.001, z0*.001], [hi[0]*.001, hi[1]*.001, z1*.001]]))
    return out


def topo_set(g: GeometryParams, zones: list[dict], d: DomainParams, o: CaseOptions | None = None) -> str:
    """Porous cellZones (fins, then grilles), plus per-card faceZones: cardExit0/1 on each card's exit plane
    (z = L + envelope) by default; in aligned cases oriented +z cuts through the ports at the `Planes` zones."""
    acts = []
    for z in zones+(grille_zones(g, o) if o else []):
        acts.append(f"{{name {z['zone']}; type cellSet; action new; source boxToCell; box {vec(z['box'][0])} {vec(z['box'][1])};}}")
        acts.append(f"{{name {z['zone']}; type cellZoneSet; action new; source setToCellZone; set {z['zone']};}}")
    if o is None or not o.aligned:
        zexit = g.chamber_length+d.card_envelope
        for card in range(len(g.card_x)):
            (x0, y0), (x1, y1) = _card_rect(g, card)
            lo, hi = [x0, y0, zexit-EXIT_SLAB], [x1, y1, zexit+EXIT_SLAB]
            name = f"cardExit{card}"
            acts.append(f"{{name {name}; type faceSet; action new; source boxToFace; box {vec([v*.001 for v in lo])} {vec([v*.001 for v in hi])};}}")
            acts.append(f"{{name {name}; type faceZoneSet; action new; source setToFaceZone; faceSet {name};}}")
        return header("topoSetDict")+"actions\n(\n"+"\n".join(acts)+"\n);\n"
    # Each cut is the interface of the cells centred upstream of the plane, so every face has exactly one cell
    # on each side (snapping and layer shrinking bend grid planes near the walls); one card's box, no walls.
    for name, centre, z in disk_planes(g, o):
        tip = o.exhaust_annulus[1] if name == disk.EXHAUST and o.exhaust_annulus else None
        acts += disk.topo_actions(name, centre, z, d, o.base_cell, tip)
        station, side = disk.STATIONS[name]
        acts += disk.station_actions(station, z+side*o.base_cell, o.base_cell)
    for name, z in (planes(g, o).stations | planes(g, o).duct_stations(g.chamber_length)).items():
        acts += disk.station_actions(name, z, o.base_cell)
    h = o.base_cell
    for plane, z in planes(g, o).zones.items():
        below = f"{plane}Upstream"
        acts.append(f"{{name {below}; type cellSet; action new; source boxToCell; box (-1 -1 -1) {vec([1, 1, z*.001])};}}")
        for card in range(len(g.card_x)):
            (x0, y0), (x1, y1) = _card_rect(g, card)
            name = f"{plane}{card}"
            acts.append(f"{{name {name}; type faceSet; action new; source cellToFace; set {below}; option outside;}}")
            acts.append(f"{{name {name}; type faceSet; action subset; source boxToFace; "
                        f"box {vec([x0*.001, y0*.001, (z-h)*.001])} {vec([x1*.001, y1*.001, (z+h)*.001])};}}")
            acts.append(f"{{name {name}; type faceSet; action subtract; source boundaryToFace;}}")
            acts.append(f"{{name {name}; type faceZoneSet; action new; source setsToFaceZone; faceSet {name}; cellSet {below};}}")
    return header("topoSetDict")+"actions\n(\n"+"\n".join(acts)+"\n);\n"


def disk_planes(g: GeometryParams, o: CaseOptions) -> list[tuple[str, tuple[float, float], float]]:
    """(faceZone name, axis centre, plane z) of each actuator disk, mm."""
    if not o.disk:
        return []
    d, p = o.domain, planes(g, o)
    out = []
    if o.rpm:
        out.append((disk.INTAKE, (0.0, 0.0), disk.disk_plane(p.at, -d.approach_depth, 0.0, o.base_cell)))
    if o.pull_rpm:
        f = collector_.fan_face(o.placed_collector)
        out.append((disk.EXHAUST, f.centre, disk.disk_plane(p.at, f.z, f.z+d.approach_depth, o.base_cell)))
    return out


def porosity_properties(zones: list[dict], f: FinModel, grilles: list[dict] = ()) -> str:
    """Fin zones (transverse flow blocked, scaled by f.resistance), then grille slabs (axial Forchheimer only)."""
    out = header("porosityProperties")
    axes = "coordinateSystem {type cartesian; origin (0 0 0); coordinateRotation {type axesRotation; e1 (1 0 0); e2 (0 1 0);}}"
    for z in zones:
        D, F = z["D"]*f.resistance, z["F"]*f.resistance
        out += f"{z['zone']} {{type DarcyForchheimer; cellZone {z['zone']}; DarcyForchheimerCoeffs {{d (1e9 1e9 {D}); f (0 0 {F}); {axes}}}}}\n"
    for z in grilles:
        out += f"{z['zone']} {{type DarcyForchheimer; cellZone {z['zone']}; DarcyForchheimerCoeffs {{d (0 0 0); f (0 0 {z['F']}); {axes}}}}}\n"
    return out


def thermal_properties(g: GeometryParams, zones: list[dict], f: FinModel) -> dict:
    return dict(cardStart=g.chamber_length*.001+f.start, cardLength=f.length, **THERMAL,
                Hvol=porous.thermal_hvol(zones, f), pathHvol=porous.thermal_path_hvol(zones, f))


def air_passage(g: GeometryParams) -> mf.Manifold:
    """`build_duct(g).inner` without the printable part: the union of the two branch passages. build_duct spends
    minutes on the dilated shell, collars and fit checks the fluid never sees (V28: 6 s vs ~6 min under load); the
    flow STL is byte-identical (flow_stl_sha256 of runs/v28-pp-v3). Falls back to build_duct when the CAD module
    no longer has the helper."""
    from ..cad import geometry
    passages, fan_half = getattr(geometry, "_passages", None), getattr(geometry, "_fan_half", None)
    if passages is None or fan_half is None:
        return build_duct(g).inner
    inners, _, sections, *_ = passages(g)
    for side in (0, 1):  # build_duct's check that the fan face opens only into the two branches
        area = next(r["area_mm2"] for r in sections if r["side"] == side and r["z_mm"] == 0)
        assert abs(area-fan_half(g, side).area) < .1, f"uncovered fan-face region in branch {side}"
    inner = geometry.union(*inners)
    inner.num_tri()  # evaluate now, as build_duct's checks do: a lazy union would merge into fluid_solid's and
    return inner     # triangulate differently


def build(out: Path, g: GeometryParams, o: CaseOptions = CaseOptions(), inner: mf.Manifold | None = None) -> dict:
    """Write the case into `out` (created). `inner` reuses an already built duct air passage."""
    out = Path(out)
    inner = air_passage(g) if inner is None else inner
    solids, rules = o.extra_solids, o.extra_rules
    if o.disk:
        solids, rules = solids+(disk.intake_room(o.domain, o.room),), rules+disk.intake_rules(o.domain)
    if o.bracket is not None:
        bs, br = bracket_.parts(g, o.bracket, o.domain, room=o.collector is None)
        solids, rules = solids+bs, rules+br
    if o.collector is not None:
        cs, cr = collector_.parts(g, o.placed_collector, o.domain, o.room if o.disk and o.pull_rpm else None,
                                  o.exhaust_annulus)
        solids, rules = solids+cs, rules+cr
    slots, refine_xy = [], []
    if o.collector is not None and o.panel_thickness:   # uncovered chassis slots under the mouth draw case air
        ss, sr, slots = collector_.open_slots(g, o.placed_collector, o.bracket.panel, o.domain)
        solids, rules = solids+ss, rules+sr
        zp = g.chamber_length+o.domain.card_envelope+o.panel_thickness
        refine_xy = [collector_.mouth(o.placed_collector, zp).bounds]+[
            (b[0], b[2], b[1], b[3]) for b in (s["case_air_box_mm"] for s in slots)]
    solid = domain.fluid_solid(g, inner, o.domain, solids, o.bracket.thickness if o.bracket else 0.0)
    mesh = domain.to_metres(solid)
    groups = domain.classify(mesh, g, o.domain, rules)
    if o.collector is not None or o.bracket is not None:  # the card exits open into a collector or still air
        assert not len(groups.pop("outletLeft")) and not len(groups.pop("outletRight")), "card exits left open"
    stl = out/"constant/triSurface/flow.stl"
    stl.parent.mkdir(parents=True, exist_ok=True)
    domain.write_stl(mesh, groups, stl)
    areas = domain.patch_areas(mesh, groups)

    values = _template_values(g, o, list(groups), solid.bounding_box(),
                              areas.get(collector_.PATCH) if not o.disk else None, refine_xy)
    for src in sorted(p for p in TEMPLATE.rglob("*") if p.is_file()):
        dst = out/src.relative_to(TEMPLATE)
        dst.parent.mkdir(parents=True, exist_ok=True)
        text = Template(src.read_text()).substitute(values)
        if collector_.CASE_AIR in groups and src.parent.name == "0":  # the templates name fixed patches only
            text = text.replace("\n walls ", f"\n {collector_.CASE_AIR} {CASE_AIR_BC[src.name]}\n walls ", 1)
        dst.write_text(text)

    zones = porous.zones(g, o.fins)
    grilles = grille_zones(g, o)
    thermal = thermal_properties(g, zones, o.fins)
    (out/"system/topoSetDict").write_text(topo_set(g, zones, o.domain, o))
    (out/"constant/porosityProperties").write_text(porosity_properties(zones, o.fins, grilles))
    (out/"constant/thermalProperties").write_text(
        header("thermalProperties")+"".join(f"{k} {vec(v) if isinstance(v, list) else v};\n" for k, v in thermal.items()))
    snappy = []
    if o.wall_layers != CaseOptions.wall_layers:
        snappy += [("addLayers", "false")] if not o.wall_layers else [
            ("addLayersControls/layers", f'{{".*walls" {{nSurfaceLayers {o.wall_layers};}}}}')]
    if o.cells_between_levels != CaseOptions.cells_between_levels:
        snappy.append(("castellatedMeshControls/nCellsBetweenLevels", o.cells_between_levels))
    if snappy:  # the template holds the reference mesh's values; only other meshes need foamDictionary
        foamdict.edit(out, [("system/snappyHexMeshDict", k, v) for k, v in snappy])
    disks = disk_planes(g, o)
    if disks:  # actuator disks: cyclic fan baffles (mesh.mesh runs createBaffles), kept whole on one rank each
        entries = []
        for name, centre, z in disks:
            intake = name == disk.INTAKE
            rpm = o.rpm if intake else o.pull_rpm
            entries.append(disk.baffle(name, rpm, o.fans if intake else 1, o.stack_efficiency, o.swirl,
                                       (centre[0]*.001, centre[1]*.001, z*.001), o.domain,
                                       *((fan.P12_PRO, None) if intake else (o.pull_model, o.exhaust_annulus))))
        (out/"system/createBafflesDict").write_text(disk.create_baffles_dict(entries))
        pp = " ".join(n for name, _, _ in disks for n in disk.patches(name))
        with open(out/"system/decomposeParDict", "a") as fh:
            fh.write(f"constraints {{fans {{type preservePatches; patches ({pp});}}}}\n")

    meta = dict(
        geometry=asdict(g),
        options=dict(base_cell_mm=o.base_cell, rpm=o.rpm, direction=o.direction, shoulder_refine=o.shoulder_refine,
                     domain=asdict(o.domain), fins=asdict(o.fins), wall_layers=o.wall_layers,
                     cells_between_levels=o.cells_between_levels),
        patches={n: dict(faces=len(groups[n]), area_m2=a) for n, a in areas.items()},
        flow_stl_sha256=hashlib.sha256(stl.read_bytes()).hexdigest(),
        zone_coefficients=zones,
        thermal=thermal,
        fan=dict(model="ARCTIC P12 Pro", chart_rpm=fan.CHART_RPM, fanPQ=[list(r) for r in fan.P12_PRO_3000],
                 fan_curve_type="manufacturer static PQ converted to total using annular outlet velocity pressure",
                 fan_reference_area_m2=math.pi*(o.domain.approach_radius**2-o.domain.hub_radius**2)*1e-6,
                 rpm=o.rpm, direction=o.direction),
    )
    if o.aligned:
        p = planes(g, o)
        meta["options"] |= dict(pull_rpm=o.pull_rpm, collector=o.collector is not None, grille_open_area=o.grille,
                                fans=o.fans, stack_efficiency=o.stack_efficiency, fan_model=o.fan_model, swirl=o.swirl)
        meta["planes_mm"] = dict(delta=p.delta, **p.zones, **p.stations, **p.duct_stations(g.chamber_length),
                                 grille=list(p.grille) if p.slab_cells else None)
        meta["grille_zones"] = grilles
        if o.bracket is not None:
            b = o.bracket
            areas_mm2 = bracket_.open_area(g, b)
            meta["bracket"] = dict(asdict(b), z_mm=p.exit_z, windows_mm=bracket_.windows(g, b),
                                   window_area_m2=b.length*b.width*1e-6,
                                   panel=None if b.panel is None else dict(
                                       source="duct.cad.hardware CaseParams", thickness_mm=b.panel_thickness,
                                       middle_blank=b.panel.middle_blank,
                                       z_mm=[p.exit_z, p.exit_z+b.panel_thickness], openings_mm=bracket_.openings(g, b),
                                       open_area_m2=[a*1e-6 for a in areas_mm2],
                                       blocked_fraction=[1-a/(b.length*b.width) for a in areas_mm2]),
                                   room=None if o.collector is not None else dict(
                                       bounds_mm=bracket_.bounds(g, b, b.room_margin), depth_mm=b.room_depth,
                                       z0_mm=p.exit_z+b.panel_thickness,
                                       far_field_patch="exhaust"))
        if o.rpm == 0:
            meta["fan"]["model"] = None
    if o.collector is not None:
        meta["open_slots"] = dict(patch=collector_.CASE_AIR if slots else None,
                                  covers=list(o.bracket.panel.covers) if o.panel_thickness else None, slots=slots,
                                  open_area_m2=sum(s["open_area_m2"] for s in slots))
    pf = o.exhaust_fan   # a non-default exhaust fan: its chart and annulus too
    pf_meta = {} if pf is None else dict(chart_rpm=pf.chart_rpm, fanPQ=[list(r) for r in pf.pq],
                                         hub_radius_mm=pf.hub_radius*1e3, tip_radius_mm=pf.tip_radius*1e3)
    if o.collector is not None and o.disk:
        meta["exhaust"] = dict(model=o.pull_model.name, **pf_meta, rpm=o.pull_rpm, fan_model="disk", patch=collector_.PATCH,
                               baffle=list(disk.patches(disk.EXHAUST)) if o.pull_rpm else None,
                               fan_face=asdict(collector_.fan_face(o.placed_collector)))
    elif o.collector is not None:
        meta["exhaust"] = dict(model=o.pull_model.name, **pf_meta, rpm=o.pull_rpm, direction="out", patch=collector_.PATCH,
                               area_m2=areas[collector_.PATCH], fan_face=asdict(collector_.fan_face(o.placed_collector)),
                               fan_curve_type="manufacturer static PQ plus the exhaust-patch velocity pressure "
                                              "(fanPressure out fixes the patch static pressure)")
    meta |= _fan_meta(g, o, disks, areas)
    (out/"case.json").write_text(json.dumps(meta, indent=2))
    return meta


def _fan_meta(g: GeometryParams, o: CaseOptions, disks, areas) -> dict:
    """Fan disks, collector and rooms for duct/viz (mm, duct frame, flow +z). Boundary-model fans sit on their patch."""
    d = o.domain
    planes_z = {name: (c, z) for name, c, z in disks}
    fans = []
    if o.rpm:
        c, z = planes_z.get(disk.INTAKE, ((0.0, 0.0), -d.approach_depth))
        fans.append(disk.fan_entry("intake", o.fan_model, o.rpm, [c[0], c[1], z], z, d.hub_radius, d.approach_radius,
                                   count_series=o.fans, stack_efficiency=o.stack_efficiency, swirl=o.swirl,
                                   patches=list(disk.patches(disk.INTAKE)) if o.disk else ["inlet"]))
    collector, rooms = dict(present=o.collector is not None), []
    if o.collector is not None:
        f = collector_.fan_face(o.placed_collector)
        collector |= dict(fan_face=asdict(f), inlet_z_mm=g.chamber_length+d.card_envelope+o.panel_thickness,
                          source=o.collector_source)
        if o.pull_rpm:
            c, z = planes_z.get(disk.EXHAUST, (f.centre, f.z+d.approach_depth))
            hub, tip = o.exhaust_annulus or (d.hub_radius, d.approach_radius)
            fans.append(disk.fan_entry("exhaust", o.fan_model, o.pull_rpm, [c[0], c[1], z], z, hub,
                                       min(tip, f.radius), swirl=o.swirl,
                                       patches=list(disk.patches(disk.EXHAUST)) if o.disk else [collector_.PATCH]))
    if o.disk:
        rooms.append(dict(role="intake", centre=[0.0, 0.0], radius_mm=o.room.radius,
                          z0_mm=-d.approach_depth-o.room.depth, z1_mm=-d.approach_depth, far_field_patch="inlet"))
        if o.pull_rpm:
            f = collector_.fan_face(o.placed_collector); z = f.z+d.approach_depth
            rooms.append(dict(role="exhaust", centre=list(f.centre), radius_mm=o.room.radius, z0_mm=z,
                              z1_mm=z+o.room.depth, far_field_patch=collector_.PATCH))
    return dict(fans=fans, collector=collector, rooms=rooms)
