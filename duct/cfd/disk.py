"""Fans as actuator disks inside the flow, with still-air rooms around them.

The `boundary` fan model puts the intake fan on the inlet patch (fanPressure) and the exhaust fan on the
exhaust patch. The `disk` model instead extends the domain: a cylindrical room of ambient air upstream of
the intake hub annulus (and downstream of the exhaust annulus in push-pull), with far-field totalPressure 0
patches, and each fan as a cyclic baffle across its annulus (OpenFOAM `fan`: a pressure jump from the fan's
total-pressure curve against the volume flow through the disk). Swirl is a tangential velocity jump on the
same baffle (`swirlFanVelocity`): Euler's turbomachine equation, Δp_t = ρ·ω·r·c_θ/η (no inlet swirl; e.g.
Dixon & Hall, Fluid Mechanics and Thermodynamics of Turbomachinery, 7th ed., ch. 1/5), so c_θ = Δp_t/(ρ ω r η).
`swirl` scales that ideal (η = 1) swirl: fanEff = 1/|swirl|; its sign is the rotor sense, + = counter-clockwise
seen from the intake (front) side, the usual axial-fan datasheet convention (not verified for the P12 Pro).
Lengths in mm in the duct frame (flow +z), metres in the case.
"""
from dataclasses import dataclass

import manifold3d as mf
import numpy as np

from ..cad.geometry import cylinder
from . import fan
from .domain import DOMAIN, TOL, DomainParams, Rule


@dataclass(frozen=True)
class RoomParams:
    radius: float = 100.0   # mm, ~1.7 fan diameters across
    depth: float = 100.0    # mm, ~0.85 fan diameter along the axis


ROOM = RoomParams()
INTAKE, EXHAUST = "intakeFan", "exhaustFan"


def intake_room(d: DomainParams = DOMAIN, r: RoomParams = ROOM) -> mf.Manifold:
    """Still air upstream of the intake approach: its far face and side are the far-field `inlet`. With an approach lip
    (DomainParams.approach_lip, rho) the approach's outer entry edge is a quarter round of radius rho, a bellmouth: the
    room's downstream face beyond the tip ring moves rho upstream and curves into the approach wall (r = tip radius)."""
    room = cylinder(r.radius, r.depth+.01, -d.approach_depth-r.depth)
    rho = d.approach_lip
    if not rho:
        return room
    z0, a = -d.approach_depth, d.approach_radius
    arc = [(a+rho+rho*np.cos(v), z0+rho*np.sin(v)) for v in np.linspace(np.pi, 1.5*np.pi, 49)]   # (a, z0) to (a+rho, z0-rho)
    lip = [(a, z0+1.0), *arc, (r.radius+1, z0-rho), (r.radius+1, z0+1.0)]
    return room-mf.Manifold.revolve(mf.CrossSection([np.array(lip)]), 256)


def exhaust_room(centre: tuple[float, float], z_out: float, r: RoomParams = ROOM) -> mf.Manifold:
    """Still air downstream of the exhaust approach end z_out: its far face and side are the far-field `exhaust`."""
    return cylinder(r.radius, r.depth+.01, z_out-.01).translate([centre[0], centre[1], 0])


def intake_rules(d: DomainParams = DOMAIN) -> tuple[Rule, ...]:
    """Room side and far face -> inlet; the plane at the approach start (hub disk, ring around the tip) -> walls; with an
    approach lip, also the lip and the room's moved downstream face (z0 - lip <= z <= z0: the room's side ends there)."""
    z = -d.approach_depth*.001; zl = z-d.approach_lip*.001
    lip = (("walls", lambda t: (t[:, :, 2].min(1) > zl-TOL) & (t[:, :, 2].max(1) < z+TOL)),) if d.approach_lip else ()
    return lip+(("inlet", lambda t: t[:, :, 2].min(1) < z-TOL),
                ("walls", lambda t: np.abs(t[:, :, 2]-z).max(1) < TOL))


def exhaust_rules(z_out_m: float) -> tuple[Rule, ...]:
    return (("exhaust", lambda t: t[:, :, 2].max(1) > z_out_m+TOL),
            ("walls", lambda t: np.abs(t[:, :, 2]-z_out_m).max(1) < TOL))


def disk_plane(planes_at, z_lo: float, z_hi: float, base: float) -> float:
    """The level-0 grid plane strictly inside an approach (z_lo, z_hi), mm: cell faces lie on it at any level.
    `planes_at(k)` = exit_z - delta - k·base (case.Planes.at)."""
    k = int(np.floor((planes_at(0)-z_lo-base/8)/base))
    z = planes_at(k)
    if not z_lo+base/8 < z < z_hi-base/8:
        raise ValueError(f"no grid plane inside the fan approach ({z_lo}, {z_hi}) mm at base cell {base}")
    return z


def topo_actions(name: str, centre: tuple[float, float], z: float, d: DomainParams, base: float,
                 tip: float | None = None) -> list[str]:
    """+z-oriented faceZone `name` across the annulus at plane z (mm): the interface of the cells centred upstream.
    `tip`: the fan's tip radius, mm (None: the domain's approach_radius)."""
    from .case import vec  # noqa: PLC0415 (case imports this module)
    below, r = f"{name}Upstream", (tip or d.approach_radius)+1
    lo = [centre[0]-r, centre[1]-r, z-base]; hi = [centre[0]+r, centre[1]+r, z+base]
    return [
        f"{{name {below}; type cellSet; action new; source boxToCell; box (-1 -1 -1) {vec([1, 1, z*.001])};}}",
        f"{{name {name}; type faceSet; action new; source cellToFace; set {below}; option outside;}}",
        f"{{name {name}; type faceSet; action subset; source boxToFace; box {vec([v*.001 for v in lo])} {vec([v*.001 for v in hi])};}}",
        f"{{name {name}; type faceSet; action subtract; source boundaryToFace;}}",
        f"{{name {name}; type faceZoneSet; action new; source setsToFaceZone; faceSet {name}; cellSet {below};}}",
    ]


def station_actions(name: str, z: float, base: float) -> list[str]:
    """+z-oriented faceZone `name` through the whole cross-section at plane z (mm): a pressure station beside a
    disk (a cyclic fan patch's own face values straddle the jump) or past the bracket. Only one passage (approach,
    duct, collector or still-air box) may cross z there."""
    from .case import vec  # noqa: PLC0415
    below = f"{name}Upstream"
    return [
        f"{{name {below}; type cellSet; action new; source boxToCell; box (-1 -1 -1) {vec([1, 1, z*.001])};}}",
        f"{{name {name}; type faceSet; action new; source cellToFace; set {below}; option outside;}}",
        f"{{name {name}; type faceSet; action subset; source boxToFace; box {vec([-1, -1, (z-base)*.001])} {vec([1, 1, (z+base)*.001])};}}",
        f"{{name {name}; type faceSet; action subtract; source boundaryToFace;}}",
        f"{{name {name}; type faceZoneSet; action new; source setsToFaceZone; faceSet {name}; cellSet {below};}}",
    ]


STATIONS = {INTAKE: ("intakeFanDownstream", 1), EXHAUST: ("exhaustFanUpstream", -1)}  # faceZone, side in base cells


def baffle(name: str, rpm: float, count: int, efficiency: float, swirl: float, centre_m, d: DomainParams,
           model: fan.FanModel = fan.P12_PRO, annulus: tuple[float, float] | None = None) -> str:
    """createBaffles entry: a cyclic pair with the fan jump (`model`'s curve) on p and, with swirl, the tangential jump on
    U across `annulus` ((hub, tip) mm; None: the domain's)."""
    hub, tip = annulus or (d.hub_radius, d.approach_radius)
    if swirl:
        # swirlFanVelocity: tangential direction = (mean master normal, +z) x r, i.e. counter-clockwise about +z;
        # a negative rpm reverses it (stabilise keeps the sign), so + swirl (CCW from the front) is -rpm.
        U = (f"{{type swirlFanVelocity; patchType cyclic; rpm {-np.sign(swirl)*rpm:.9g}; fanEff {1/abs(swirl):.9g}; "
             f"useRealRadius true; rInner {hub*1e-3:.9g}; rOuter {tip*1e-3:.9g}; "
             f"origin ({centre_m[0]:.9g} {centre_m[1]:.9g} {centre_m[2]:.9g}); jump uniform (0 0 0); value uniform (0 0 0);}}")
    else:
        U = "{type cyclic;}"
    fields = dict(p=fan.fan_jump_bc(rpm, count, efficiency, model), U=U, k="{type cyclic;}", omega="{type cyclic;}",
                  nut="{type cyclic;}", T="{type cyclic;}")
    body = " ".join(f"{k} {v}" for k, v in fields.items())
    return f"{name} {{type faceZone; zoneName {name}; patchPairs {{type cyclic; patchFields {{{body}}}}}}}"


def create_baffles_dict(entries: list[str]) -> str:
    from .case import header  # noqa: PLC0415
    return header("createBafflesDict")+"internalFacesOnly true;\nbaffles\n{\n"+"\n".join(entries)+"\n}\n"


def patches(name: str) -> tuple[str, str]:
    """createBaffles patchPairs names: master (upstream side, normal +z) and slave."""
    return f"{name}_master", f"{name}_slave"


def fan_entry(role: str, model: str, rpm: float, centre_mm, z_mm: float, hub_mm: float, tip_mm: float, **extra) -> dict:
    """case.json `fans` entry (mm, duct frame, flow +z), read by duct/viz/export.py. z_mm: the disk plane
    (disk model) or the fan patch plane (boundary model)."""
    return dict(role=role, model=model, rpm=rpm, centre=[float(c) for c in centre_mm], z_mm=float(z_mm),
                thickness_mm=0.0, hub_radius_mm=float(hub_mm), tip_radius_mm=float(tip_mm), axis=[0.0, 0.0, 1.0], **extra)
