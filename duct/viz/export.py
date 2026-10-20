"""Export a solved OpenFOAM case's flow field for the live airflow view in the preview page.

The internal-mesh point fields (U, and p, k when present) are probed onto regular grid blocks covering the
fluid domain; grid nodes outside the fluid are masked. Blocks are stacked along z, so each region gets its
own resolution: the duct, the bracket/collector and the fan disks at `spacing_mm`; the long, axially uniform
card section coarser along z; an ambient room (when the case has one) coarser still. Each field is
quantized to int16 (scale and offset per field over all blocks), packed with the mask, gzipped and
base64-encoded so the page can inflate it with `DecompressionStream('gzip')`. Coordinates stay in the CFD
frame (metres in the case, millimetres in the export): fan face at z = 0, x across the cards, y along them,
which is also the preview's frame. Pressures are kinematic (p/ρ), as in the case.
"""
import base64
import gzip
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..cfd.domain import DOMAIN
from ..params import PRESETS, V23, GeometryParams
from . import analysis

SPACING_MM = 2.0
SCALARS = ("p", "k")  # the page reads p (total-pressure loss) and k; nut is not exported
OUTLIER_FACTOR = 1.5  # probe outliers (a few nodes in degenerate cells) are clipped to this × the 99.9th-percentile speed
CARD_DZ_MM = 8.0      # z spacing in the card section: the porous fin flow is axial and uniform along z
CARD_MARGIN_MM = (10.0, 30.0)  # fine grid past the duct collar (fin entry) and before the bracket plane (grille)
ROOM_NODES = 120_000  # node budget of an ambient room block; its spacing grows to fit


@dataclass
class FieldGrid:
    origin_mm: tuple[float, float, float]
    spacing_mm: float | tuple[float, float, float]  # isotropic, or (hx, hy, hz)
    dims: tuple[int, int, int]           # nx, ny, nz; x varies fastest in the flat arrays
    U: np.ndarray                        # (nz, ny, nx, 3) float32, m/s; zero where masked
    mask: np.ndarray                     # (nz, ny, nx) bool, True inside the fluid
    fields: dict[str, np.ndarray] = field(default_factory=dict)  # (nz, ny, nx) float32 scalars; zero where masked
    role: str = "domain"                 # room-in, duct, cards, outlet, room-out, or domain (one block)

    @property
    def h3(self) -> tuple[float, float, float]:
        s = self.spacing_mm
        return tuple(float(v) for v in s) if isinstance(s, (tuple, list)) else (float(s),)*3


@dataclass
class AirflowExport:
    grid: FieldGrid                      # the duct block (analysis, hotspots), or the only block
    meta: dict = field(default_factory=dict)
    blocks: list[FieldGrid] | None = None  # all blocks, z-stacked; None: just `grid`

    def payload(self) -> dict:
        """JSON-able dict: metadata, block layout and the base64 gzip of the int16 fields over all blocks in order
        (U xyz-interleaved first, then each scalar; each field byte-shuffled, which gzips ~20 % smaller) followed by
        the uint8 mask. Value = offset + scale·int16; one offset/scale per field over all blocks."""
        blocks = self.blocks or [self.grid]
        names = [n for n in blocks[0].fields if all(n in b.fields for b in blocks)]
        layout, chunks = [], []
        for name, comps in [("U", 3)]+[(n, 1) for n in names]:
            arr = np.concatenate([(b.U if name == "U" else b.fields[name]).ravel() for b in blocks])
            lo, hi = (float(arr.min()), float(arr.max())) if comps == 1 else (-float(np.abs(arr).max()), float(np.abs(arr).max()))
            offset, scale = (lo+hi)/2, ((hi-lo)/2 or 1.0)/32000
            q = np.round((arr-offset)/scale).astype("<i2")
            chunks.append(q.view(np.uint8).reshape(-1, 2).T.tobytes())  # byte-shuffled: all low bytes, then all high bytes
            layout.append(dict(name=name, comps=comps, offset=offset, scale=scale))
        raw = b"".join(chunks)+b"".join(b.mask.astype(np.uint8).tobytes() for b in blocks)
        b64 = base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode()
        return dict(meta=self.meta, grid=dict(
            blocks=[dict(role=b.role, origin=list(b.origin_mm), spacing=list(b.h3), dims=list(b.dims)) for b in blocks],
            fields=layout, encoding="gzip:int16 byte-shuffled fields over all blocks+uint8 mask"), data=b64)


def load_case(case: Path, time: float | None = None):
    """(internalMesh with point fields, time) at the latest (or given) time of a reconstructed case."""
    import pyvista as pv
    case = Path(case)
    foam = case/"case.foam"
    if not foam.exists():
        foam.touch()
    reader = pv.POpenFOAMReader(str(foam))
    times = [t for t in reader.time_values if t > 0] or reader.time_values
    t = times[-1] if time is None else time
    reader.set_active_time_value(t)
    reader.disable_all_patch_arrays()
    reader.enable_patch_array("internalMesh")
    reader.cell_to_point_creation = True
    reader.enable_all_cell_arrays()
    mesh = reader.read()["internalMesh"]
    assert "U" in mesh.point_data, f"no U field at time {t} in {case}"
    return mesh, float(t)


def _probe(mesh, origin, h3, dims, scalars, role) -> FieldGrid:
    """Probe point fields of `mesh` (metres) at the nodes origin + i·h (mm); vtkValidPointMask marks fluid nodes."""
    import pyvista as pv
    grid = pv.ImageData(dimensions=dims, spacing=tuple(h*1e-3 for h in h3), origin=tuple(o*1e-3 for o in origin))
    probe = pv.PolyData(grid.points).sample(mesh, pass_point_data=False)
    mask = np.asarray(probe["vtkValidPointMask"]).astype(bool)
    U = np.asarray(probe["U"], dtype=np.float32).copy()
    U[~mask] = 0
    nx, ny, nz = dims
    fields = {}
    if mask.any():
        speed = np.linalg.norm(U, axis=1)
        cap = OUTLIER_FACTOR*np.percentile(speed[mask], 99.9)
        U *= np.minimum(1, cap/np.maximum(speed, 1e-12))[:, None].astype(np.float32)
        for name in scalars:
            if name not in probe.point_data:
                continue
            s = np.asarray(probe[name], dtype=np.float32).copy()
            lo_, hi_ = np.percentile(s[mask], [.01, 99.99])
            s = np.clip(s, lo_, hi_)
            s[~mask] = 0
            fields[name] = s.reshape(nz, ny, nx)
    h = h3[0] if len(set(h3)) == 1 else tuple(h3)
    return FieldGrid(tuple(float(v) for v in origin), h, tuple(dims), U.reshape(nz, ny, nx, 3), mask.reshape(nz, ny, nx), fields, role)


def sample_grid(mesh, spacing_mm: float = SPACING_MM, scalars=SCALARS) -> FieldGrid:
    """One isotropic grid over the mesh bounds, centred on them."""
    b = np.asarray(mesh.bounds, dtype=float)*1e3
    lo, hi = b[0::2], b[1::2]
    dims = tuple(int(np.ceil((h-l)/spacing_mm))+1 for l, h in zip(lo, hi))
    origin = tuple(float(v) for v in (lo+hi)/2-(np.array(dims)-1)*spacing_mm/2)
    return _probe(mesh, origin, (spacing_mm,)*3, dims, scalars, "domain")


def sample_block(mesh, lo, hi, h3, scalars=SCALARS, role: str = "block") -> FieldGrid:
    """Grid with nodes exactly on lo and hi along z (blocks share their boundary planes) and centred on [lo, hi]
    in x and y; the z spacing is shrunk to fit a whole number of steps."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    nz = max(2, int(math.ceil((hi[2]-lo[2])/h3[2]-1e-9))+1)
    hz = round((hi[2]-lo[2])/(nz-1), 9)
    nxy = [int(np.ceil((hi[a]-lo[a])/h3[a]))+1 for a in (0, 1)]
    oxy = [(lo[a]+hi[a])/2-(nxy[a]-1)*h3[a]/2 for a in (0, 1)]
    return _probe(mesh, (oxy[0], oxy[1], lo[2]), (h3[0], h3[1], hz), (nxy[0], nxy[1], nz), scalars, role)


def plan_blocks(mesh, meta: dict, spacing_mm: float = SPACING_MM) -> list[tuple[str, tuple, tuple, tuple]]:
    """(role, lo, hi, (hx, hy, hz)) mm, stacked along z, from the domain extent and the case's key planes:
    room upstream of the intake fan disk, duct (to the fin entry), cards (coarse along z), outlet (grille, collector,
    exhaust fan), room downstream. Each block's x/y extent is the fluid's within its z range."""
    pts = np.asarray(mesh.points)*1e3
    zmin, zmax = float(pts[:, 2].min()), float(pts[:, 2].max())
    fans = meta.get("fans") or []
    intake = next((f for f in fans if f["role"] == "intake"), None)
    exhaust = next((f for f in fans if f["role"] == "exhaust"), None)
    duct_end = meta["chamber_length_mm"]+meta["collar_mm"]+CARD_MARGIN_MM[0]
    bracket = meta["cards"][0]["z1_mm"] if meta.get("cards") else zmax
    # Cut planes on the z = k·spacing lattice (fan face at k = 0), so every fine block steps exactly `spacing_mm`.
    # A room's cut lies just inside the fan approach annulus: the plane is fluid in both blocks, so particles cross it.
    h = spacing_mm
    snap = lambda z, f=round: f(z/h)*h  # noqa: E731
    z_in = intake["z0_mm"] if intake else zmin
    room_in = zmin < z_in-2*h
    cuts = [("room-in", snap(zmin, math.floor))] if room_in else []
    cuts.append(("duct", snap(z_in+.5, math.ceil) if room_in else snap(zmin, math.floor)))
    if bracket-CARD_MARGIN_MM[1]-duct_end > 2*CARD_DZ_MM:
        cuts += [("cards", snap(duct_end)), ("outlet", snap(bracket-CARD_MARGIN_MM[1]))]
    z_out = exhaust["z1_mm"] if exhaust else zmax
    if zmax > z_out+2*h:
        cuts.append(("room-out", snap(z_out-.5, math.floor)))
    cuts.append((None, snap(zmax, math.ceil)))
    cuts = [c for i, c in enumerate(cuts) if i == len(cuts)-1 or cuts[i+1][1] > c[1]+1e-6]  # drop empty slabs
    out = []
    for (role, z0), (_, z1) in zip(cuts, cuts[1:]):
        # x/y extent of the fluid in the slab: a room's whole cross-section; ducted blocks only their interior, so the
        # room's face on the approach plane does not widen the duct or outlet block.
        sel = pts[(pts[:, 2] >= z0-h) & (pts[:, 2] <= z1+h)] if role.startswith("room") else pts[(pts[:, 2] > z0+.25) & (pts[:, 2] < z1-.25)]
        lo, hi = (*sel[:, :2].min(0), z0), (*sel[:, :2].max(0), z1)
        if role == "cards":
            h3 = (h, h, CARD_DZ_MM)
        elif role.startswith("room"):
            vol = float(np.prod(np.subtract(hi, lo)))
            h3 = (max(2*h, (vol/ROOM_NODES)**(1/3)),)*3
        else:
            h3 = (h,)*3
        out.append((role, tuple(float(v) for v in lo), tuple(float(v) for v in hi), h3))
    return out


def plane_flow(mesh, z_m: float) -> float:
    """Volumetric flow (m³/s) through the plane z = z_m."""
    sl = mesh.slice(normal="z", origin=(0, 0, z_m))
    sl.point_data["w"] = np.asarray(sl.point_data["U"])[:, 2]
    return float(sl.integrate_data()["w"][0])


def _boxes(case: Path) -> list[list[list[float]]]:
    """Porous fin zone boxes (m): case.json zone_coefficients, else the fin boxToCell boxes of system/topoSetDict
    (not the measurement-plane `...Upstream` half-spaces of aligned cases)."""
    built = _read(case, "case.json")
    if built.get("zone_coefficients"):
        return [z["box"] for z in built["zone_coefficients"]]
    p = case/"system/topoSetDict"
    if not p.exists():
        return []
    num = r"(-?[\d.eE+-]+)"
    pat = rf"name\s+(\w+);[^}}]*?boxToCell;\s*box\s*\(\s*{num}\s+{num}\s+{num}\s*\)\s*\(\s*{num}\s+{num}\s+{num}\s*\)"
    return [[[float(v) for v in m[1:4]], [float(v) for v in m[4:]]] for m in re.findall(pat, p.read_text())
            if not m[0].endswith("Upstream")]


def _read(case: Path, name: str) -> dict:
    return json.loads((case/name).read_text()) if (case/name).exists() else {}


def case_geometry(case: Path) -> GeometryParams:
    """Geometry of a `duct cfd` case (case.json); legacy cases fall back to V23 with their chamber length."""
    from dataclasses import fields as dc_fields, replace
    built, legacy = _read(case, "case.json"), _read(case, "geometry.json")
    if "geometry" in built:
        names = {f.name for f in dc_fields(GeometryParams)}
        tup = lambda v: tuple(map(tup, v)) if isinstance(v, list) else v  # noqa: E731
        return replace(V23, **{k: tup(v) for k, v in built["geometry"].items() if k in names})
    return replace(V23, chamber_length=float(legacy.get("L_mm", V23.chamber_length)))


def geometry_preset(case: Path) -> dict:
    """Release preset nearest to the case geometry: name (e.g. 'v24'), exact match, differing parameters.
    Compared over the parameters both sides have (older case.json files predate some)."""
    from dataclasses import asdict
    g = _read(Path(case), "case.json").get("geometry")
    if not g:
        return dict(name="v23", exact=False, differing=None)
    def diff(p):
        a = json.loads(json.dumps(asdict(p)))
        return [k for k in a.keys() & g.keys() if a[k] != g[k]]
    name = min(PRESETS, key=lambda n: (len(diff(PRESETS[n])), n))
    d = diff(PRESETS[name])
    return dict(name=name, exact=not d and set(g) == set(json.loads(json.dumps(asdict(PRESETS[name])))), differing=sorted(d))


def _mm(v, metres: bool):
    return [float(x)*(1e3 if metres else 1) for x in v] if isinstance(v, (list, tuple)) else float(v)*(1e3 if metres else 1)


def _declared_fans(built: dict) -> list[dict]:
    """case.json `fans` (duct.cfd.disk.fan_entry: role, model, rpm, centre, z_mm, hub/tip_radius_mm; mm, duct frame).
    Tolerant of other spellings and of metres (radii below 1); entries without a z and a tip radius are skipped."""
    raw = built.get("fans") or built.get("fan_disks") or built.get("actuator_disks")
    if isinstance(raw, dict):
        raw = [dict(v, role=v.get("role", k)) for k, v in raw.items() if isinstance(v, dict)]
    out = []
    for i, f in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(f, dict):
            continue
        tip = next((f[k] for k in ("tip_radius_mm", "tip_r_mm", "radius_mm", "tip_radius", "r_tip", "radius") if k in f), None)
        c = f.get("centre") or f.get("center") or [0, 0]
        z = next((f[k] for k in ("z_mm", "z", "z_m") if k in f), c[2] if len(c) == 3 else None)
        if tip is None or z is None:
            continue
        metres = float(tip) < 1
        hub = next((f[k] for k in ("hub_radius_mm", "hub_r_mm", "hub_radius", "r_hub") if k in f), 0.0)
        role = str(f.get("role") or ("intake" if i == 0 else "exhaust")).lower()
        out.append(dict(role="exhaust" if any(w in role for w in ("exhaust", "pull")) else "intake",
                        centre=_mm(list(c[:2]), metres), z_mm=_mm(z, metres), hub_r_mm=_mm(hub, metres), tip_r_mm=_mm(tip, metres),
                        model=f.get("model"), rpm=f.get("rpm"), count_series=f.get("count_series")))
    return out


def fan_disks(built: dict) -> list[dict]:
    """Intake and exhaust fans (mm, duct frame, flow +z through both). z0_mm..z1_mm is the fan's hub-annulus
    approach (intake: approach_depth upstream of the fan face; exhaust: past the collector's fan face); z_mm is
    the actuator-disk plane (disk model) or the fan patch plane (boundary model). From case.json `fans` when
    declared, else derived from the domain and the collector's fan face."""
    declared = {f["role"]: f for f in _declared_fans(built)}
    opts = built.get("options", {})
    d = {**DOMAIN.__dict__, **opts.get("domain", {})}
    depth = float(d["approach_depth"])
    di = declared.get("intake", {})
    out = [dict(role="intake", centre=di.get("centre", [0.0, 0.0]), z_mm=di.get("z_mm", -depth), z0_mm=-depth, z1_mm=0.0,
                hub_r_mm=di.get("hub_r_mm", float(d["hub_radius"])), tip_r_mm=di.get("tip_r_mm", float(d["approach_radius"])),
                model=di.get("model") or "boundary", rpm=di.get("rpm") or float(opts.get("rpm", 2500)),
                count_series=di.get("count_series") or opts.get("fans") or 1)]
    ex = built.get("exhaust") or {}
    ff = ex.get("fan_face") or (built.get("collector") or {}).get("fan_face")
    de = declared.get("exhaust")
    if ff or de:
        z_face = float(ff["z"]) if ff else de["z_mm"]-depth
        de = de or {}
        out.append(dict(role="exhaust", centre=de.get("centre", [float(v) for v in ff["centre"]] if ff else [0.0, 0.0]),
                        z_mm=de.get("z_mm", z_face+depth), z0_mm=z_face, z1_mm=z_face+depth,
                        hub_r_mm=de.get("hub_r_mm", float(d["hub_radius"])),
                        tip_r_mm=de.get("tip_r_mm", min(float(d["approach_radius"]), float(ff["radius"])) if ff else float(d["approach_radius"])),
                        model=de.get("model") or ex.get("fan_model") or "boundary", rpm=de.get("rpm") or ex.get("rpm") or opts.get("pull_rpm")))
    return out


def breakdown(case: Path) -> dict | None:
    """Push-pull / grille pressure breakdown: summary.json pressure_breakdown, else parsed from log.breakdown."""
    case = Path(case)
    bd = _read(case, "summary.json").get("pressure_breakdown")
    if not bd and (case/"log.breakdown").exists():
        try:
            from ..cfd import breakdown as bdm
            built = _read(case, "case.json")
            inlet, exits = bdm.stations(built)  # fan patches, or the faceZones beside actuator disks
            bd = bdm.parse(case/"log.breakdown", exits, built, inlet)
        except Exception:  # noqa: BLE001 - optional panel data
            bd = None
    if not bd:
        return None
    net = bd.get("network") or {}
    return dict(q_m3s=bd.get("q_m3s"), drops_pa=bd.get("total_pressure_drops_pa", {}), grille=bd.get("grille"),
                collector_k=net.get("collector_k"), bracket_k=net.get("bracket_k"),
                collector_k_with_bracket=net.get("collector_k_with_bracket"),
                stations={k: dict(p_pa=v["p_pa"], pt_pa=v["pt_pa"]) for k, v in bd.get("stations", {}).items()})


def _bracket(b: dict | None) -> dict | None:
    """Bracket plate at the card exits (mm, duct frame): plane z, thickness, top edge y and one window per card
    [x0, x1, y0, y1]; the still-air room past it in single-fan cases."""
    if not b or not b.get("windows_mm"):
        return None
    return dict(z_mm=float(b["z_mm"]), thickness_mm=float(b.get("thickness", 1.0)), top_y_mm=b.get("top_y"),
                windows_mm=[[float(v) for v in w] for w in b["windows_mm"]], window_area_m2=b.get("window_area_m2"),
                room=b.get("room"))


def case_metadata(case: Path, mesh, time: float, g: GeometryParams) -> dict:
    """Name, rpm, CFD flow and geometry context. Works for the legacy rounding-study layout
    (geometry.json, fan-operating-point.json) and for `duct cfd` cases (case.json)."""
    case = Path(case)
    legacy, op, built = _read(case, "geometry.json"), _read(case, "fan-operating-point.json"), _read(case, "case.json")
    summary = _read(case, "summary.json")
    L = g.chamber_length
    opts = built.get("options", {})
    rpm = float(opts.get("rpm", legacy.get("rpm", 2500)))
    envelope = float(opts.get("domain", {}).get("card_envelope", DOMAIN.card_envelope))
    q_plane = plane_flow(mesh, (L*.5)*1e-3)
    q = float(op.get("flow_m3s", q_plane))
    boxes = _boxes(case)
    porous_z = [min(b[0][2] for b in boxes)*1e3, max(b[1][2] for b in boxes)*1e3] if boxes else None
    name = legacy.get("name") or (case.parent.name if case.name == "case" else case.name)
    fans = fan_disks(built) if built else fan_disks({})
    inlet = summary.get("flow", {}).get("inlet", {})
    ex = built.get("exhaust")
    planes = built.get("planes_mm") or {}
    collector = None
    declared = built.get("collector") if isinstance(built.get("collector"), dict) else {}
    if opts.get("collector") or ex or declared.get("present"):
        collector = dict(bracket_z_mm=L+envelope, fan_face=(ex or {}).get("fan_face") or declared.get("fan_face"),
                         grille_z_mm=planes.get("grille"), grille_open_area=opts.get("grille_open_area"),
                         source=declared.get("source"))   # which collector the run modelled (duct.viz.web.collector_version)
    return dict(
        case=name, time=time, rpm=rpm, flow_m3s=q, flow_plane_m3s=q_plane,
        flow_source="fan-operating-point.json" if "flow_m3s" in op else f"U·n integrated at z = {L*.5:g} mm",
        fan_total_pa=op.get("fan_total_pressure_Pa"),
        chamber_length_mm=L, collar_mm=g.collar_length, pitch_mm=g.pitch,
        fan=dict(hub_r_mm=fans[0]["hub_r_mm"], tip_r_mm=fans[0]["tip_r_mm"], z0_mm=fans[0]["z0_mm"], z1_mm=fans[0]["z1_mm"]),
        fans=fans, intake_count=int(inlet.get("count_series") or fans[0]["count_series"] or 1),
        pull_rpm=opts.get("pull_rpm") or (ex or {}).get("rpm"),
        collector=collector, geometry_preset=geometry_preset(case),
        cards=[dict(x_mm=cx, w_mm=float(g.bore[0]), h_mm=float(g.bore[1]), z0_mm=L+g.collar_length, z1_mm=L+envelope) for cx in g.card_x],
        porous_z_mm=porous_z,
        porous_boxes_mm=[[[v*1e3 for v in lo], [v*1e3 for v in hi]] for lo, hi in boxes],
        grilles_mm=[[[v*1e3 for v in z["box"][0]], [v*1e3 for v in z["box"][1]]] for z in built.get("grille_zones") or []],
        bracket=_bracket(built.get("bracket")), rooms_mm=built.get("rooms") or [],
        breakdown=breakdown(case),
    )


def export_case(case: Path, spacing_mm: float = SPACING_MM, time: float | None = None, label: str = "",
                badge: str = "", blocks: bool = True) -> AirflowExport:
    """badge: the short provenance line shown with the field, e.g. 'qualitative, V23 upper-r6 @400, not fully converged'.
    blocks: z-stacked blocks (coarse card section and room); False: one isotropic grid over the domain."""
    from ..cfd import fan
    case = Path(case)
    mesh, t = load_case(case, time)
    g = case_geometry(case)
    meta = case_metadata(case, mesh, t, g)
    if blocks:
        grids = [sample_block(mesh, lo, hi, h, role=role) for role, lo, hi, h in plan_blocks(mesh, meta, spacing_mm)]
        grid = next(b for b in grids if b.role == "duct")
    else:
        grid = sample_grid(mesh, spacing_mm); grids = [grid]
    speed = np.linalg.norm(grid.U[grid.mask], axis=1)
    fan_total = meta["fan_total_pa"] or float(fan.total_pressure(meta["flow_m3s"], meta["rpm"]))
    meta.update(label=label or meta["case"], badge=badge or f"qualitative, {label or meta['case']} @{t:g}",
                speed_p50=float(np.percentile(speed, 50)), speed_p98=float(np.percentile(speed, 98)),
                speed_max=float(speed.max()), fluid_nodes=int(sum(b.mask.sum() for b in grids)),
                analysis=analysis.analyse(mesh, grid, g.port_boxes, g.chamber_length, g.collar_length, fan_total) if "p" in grid.fields else None)
    return AirflowExport(grid, meta, grids)
