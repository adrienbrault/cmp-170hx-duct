"""Duct-flow metrics of a solved case (docs/push-aero-plan.md, "CFD / Metrics"): the duct's own loss, how evenly the air
enters the card fins, and the dead core behind the fan hub. Written to summary.json as `duct_flow`.

- Duct loss: the pressure breakdown's `duct` term (inlet station past the fan to the seatUp station just before the
  seat face) and `card_face` (seatUp to cardEntry, the card face's contraction into the ports), when the case has seatUp.
- Card entry: Uz sampled on a plane inside the fin zones, where the porous fins force purely axial flow, so the flow
  per fin row is the same at any depth: per port the CoV of Uz, its share of the card's flow, and the flow per fin row
  (FinModel.channels equal bands across the port's y extent): the main port's row profile and every port's row CoV.
- Hub wake, from the cell field (centres, volumes, Uz) in 0 < z < L: the reverse-flow (Uz < 0) volume, split at the
  fan axis distance r < CORE_R (core) and r > PERIPHERY_R (periphery); the core fill length (the first z from which
  the mean Uz inside the hub radius stays at least FILL (each) of the section's mean Uz up to the seat); per plane,
  the slow-area fraction (Uz below SLOW of the section's mean Uz) by region, and the periphery's reverse area.
- Bay quadrant: on a plane BAY_DZ before the seat, each card's flow-weighted total pressure in the passage quadrant
  beside the connector bay (x < card centre, y > 0: both cards' plugs sit on the -x side) below the passage mean.

The plane metrics use points on a regular SPACING grid interpolated from the cell field (equal-area samples); points
outside the fluid are dropped. Lengths in mm, velocities in m/s, pressures in Pa (kinematic values x fan.RHO).
"""
import json
from dataclasses import fields
from pathlib import Path

import numpy as np

from ..params import V23, GeometryParams, from_toml
from . import fan
from .porous import FINS, FinModel
from .run import case_meta

CORE_R, PERIPHERY_R = 45.0, 50.0       # mm from the fan axis (plan): the hub wake's core and the peripheral ring
SLOW = 0.5                             # slow: Uz below this fraction of the section's mean Uz
FILL = (0.5, 0.8)                      # the core is filled where its mean Uz reaches these fractions of the section's
WAKE_Z = (30.0, 45.0, 58.0)            # slow-area planes (mm from the fan face)
PERIPHERY_Z = (2.0, 5.0, 10.0)         # periphery reverse-area planes
FILL_DZ = 1.0                          # core fill length: plane pitch
FIN_DEPTH = 10.0                       # card-entry plane this far into the fin zone
BAY_DZ = 1.5                           # bay-quadrant plane this far before the seat face
SPACING = 0.5                          # mm, plane sample grid


# --- pure metrics (numpy arrays, testable without OpenFOAM) -------------------------------------------------------

def reverse_volumes(centres: np.ndarray, volumes: np.ndarray, uz: np.ndarray, L: float,
                    core_r: float = CORE_R, periphery_r: float = PERIPHERY_R) -> dict:
    """Reverse-flow volume (cm3) of the cells centred in 0 < z < L (mm), total and split by distance from the fan axis."""
    z = centres[:, 2]; duct = (z > 0) & (z < L)
    r = np.hypot(centres[:, 0], centres[:, 1])[duct]; v = volumes[duct]; rev = uz[duct] < 0
    air = float(v.sum())
    return dict(air_cm3=air*1e-3, reverse_cm3=float(v[rev].sum())*1e-3, reverse_fraction=float(v[rev].sum()/air) if air else 0.0,
                core_reverse_cm3=float(v[rev & (r < core_r)].sum())*1e-3, periphery_reverse_cm3=float(v[rev & (r > periphery_r)].sum())*1e-3,
                core_r_mm=core_r, periphery_r_mm=periphery_r)


def plane_regions(xy: np.ndarray, uz: np.ndarray, slow: float = SLOW, core_r: float = CORE_R,
                  periphery_r: float = PERIPHERY_R) -> dict:
    """Equal-area samples of one section: the slow-area fraction of each region (of that region's area) and the reverse
    area in the periphery (of the whole section)."""
    r = np.hypot(xy[:, 0], xy[:, 1]); mean = float(uz.mean()); s = uz < slow*mean
    frac = lambda m: float(s[m].mean()) if m.any() else None  # noqa: E731
    core, per = r < core_r, r > periphery_r
    return dict(uz_mean_mps=mean, slow_fraction=float(s.mean()), slow_fraction_core=frac(core), slow_fraction_periphery=frac(per),
                reverse_fraction=float((uz < 0).mean()), periphery_reverse_fraction=float(((uz < 0) & per).mean()))


def core_fill_length(zs, core_mean, section_mean, fill: float = FILL[0]) -> float | None:
    """The first z from which the core's mean Uz stays at least `fill` x the section's mean Uz to the last plane;
    None if it never does, zs[0] if it always does."""
    ok = np.asarray(core_mean) >= fill*np.asarray(section_mean)
    if not ok[-1]: return None
    bad = np.flatnonzero(~ok)
    return float(zs[bad[-1]+1]) if len(bad) else float(zs[0])


def port_uniformity(xy: np.ndarray, uz: np.ndarray, g: GeometryParams, f: FinModel = FINS) -> dict:
    """Per card and port, from equal-area samples on a plane inside the fins: flow share, CoV of Uz and the flow per fin
    row (rows: f.channels equal bands across the port's y extent, each row's flow / the port's mean row flow)."""
    cards = []
    for card in range(len(g.card_x)):
        ports = []
        for c, port, (x0, x1, y0, y1) in g.port_boxes:
            if c != card: continue
            m = (xy[:, 0] > x0) & (xy[:, 0] < x1) & (xy[:, 1] > y0) & (xy[:, 1] < y1)
            u = uz[m]; y = xy[m, 1]; n = f.channels[port]
            band = np.minimum(((y-y0)/(y1-y0)*n).astype(int), n-1)
            rows = np.array([u[band == k].mean() for k in range(n)])*(y1-y0)/n*(x1-x0)   # flow per row (m/s x mm2)
            ports.append(dict(port=port, flow=float(u.mean()*(x1-x0)*(y1-y0)), uz_cov=float(u.std()/u.mean()),
                              row_cov=float(rows.std()/rows.mean()), peak_row=float(rows.max()/rows.mean()),
                              rows=(rows/rows.mean()).round(4).tolist()))
        total = sum(p["flow"] for p in ports)
        for p in ports: p["share"] = p.pop("flow")/total
        cards.append(dict(card=card, ports=ports))
    main = [c["ports"][0] for c in cards]
    return dict(cards=cards, main_uz_cov=max(p["uz_cov"] for p in main), main_row_cov=max(p["row_cov"] for p in main),
                main_peak_row=max(p["peak_row"] for p in main))


def bay_deficit(xy: np.ndarray, uz: np.ndarray, pt: np.ndarray, g: GeometryParams) -> dict:
    """Per card: the flow-weighted total pressure of the passage minus that of its bay quadrant (x < card centre, y > 0)."""
    out = []
    for card, cx in enumerate(g.card_x):
        side = (xy[:, 0] < 0) if card == 0 else (xy[:, 0] >= 0)
        quad = side & (xy[:, 0] < cx) & (xy[:, 1] > 0)
        w = lambda m: float((uz[m]*pt[m]).sum()/uz[m].sum())  # noqa: E731
        out.append(dict(card=card, pt_passage_pa=w(side), pt_bay_quadrant_pa=w(quad), deficit_pa=w(side)-w(quad),
                        bay_quadrant_flow_share=float(uz[quad].sum()/uz[side].sum())))
    return dict(cards=out, deficit_pa=max(c["deficit_pa"] for c in out))


# --- case I/O -----------------------------------------------------------------------------------------------------

def geometry(meta: dict) -> GeometryParams:
    names = {f.name for f in fields(GeometryParams)}
    return from_toml({k: v for k, v in meta["geometry"].items() if k in names}, V23)


def _grid(x0, x1, y0, y1, spacing):
    gx = np.arange(x0+spacing/2, x1, spacing); gy = np.arange(y0+spacing/2, y1, spacing)
    x, y = (a.ravel() for a in np.meshgrid(gx, gy))
    return np.c_[x, y]


def _probe(mesh, xy: np.ndarray, z: float):
    """(xy, U, p) at the points of xy (mm) on plane z that lie in the fluid; U in m/s, p in Pa."""
    import pyvista as pv
    probe = pv.PolyData(np.c_[xy, np.full(len(xy), z)]*1e-3).sample(mesh, pass_point_data=False)
    ok = np.asarray(probe["vtkValidPointMask"]).astype(bool)
    return xy[ok], np.asarray(probe["U"])[ok], np.asarray(probe["p"])[ok]*fan.RHO


def duct_flow(case: Path, drops: dict | None = None, spacing: float = SPACING) -> dict:
    """The metrics above for a solved, reconstructed case; `drops`: its pressure breakdown's total_pressure_drops_pa
    (default: from summary.json)."""
    from .inlet import _load
    case = Path(case); meta = case_meta(case); g = geometry(meta); L = g.chamber_length
    mesh = _load(case)
    sized = mesh.compute_cell_sizes(length=False, area=False, volume=True)
    centres = np.asarray(mesh.cell_centers().points)*1e3; vols = np.abs(np.asarray(sized.cell_data["Volume"]))*1e9
    uz_cells = np.asarray(mesh.cell_data["U"])[:, 2]
    out = dict(reverse=reverse_volumes(centres, vols, uz_cells, L))
    intake = next((f for f in meta.get("fans", []) if f["role"] == "intake"), None)
    hub_r = intake["hub_radius_mm"] if intake else fan.HUB_RADIUS*1e3
    R = g.fan_plate/2
    section = _grid(-R, R, -R, R, spacing)

    def plane(z, grid=section):
        xy, U, _ = _probe(mesh, grid, z)
        return xy, U[:, 2]
    out["planes"] = {f"z{z:g}": plane_regions(*plane(z)) for z in sorted(set(WAKE_Z) | set(PERIPHERY_Z)) if z < L}
    out["periphery_reverse_fraction"] = float(np.mean([out["planes"][f"z{z:g}"]["periphery_reverse_fraction"] for z in PERIPHERY_Z]))
    # core fill length: a coarser grid is enough for the means
    coarse = _grid(-R, R, -R, R, 2*spacing); zs = np.arange(FILL_DZ, L-FILL_DZ/2, FILL_DZ); core, sec = [], []
    for z in zs:
        xy, uz = plane(z, coarse); c = np.hypot(xy[:, 0], xy[:, 1]) < hub_r
        core.append(float(uz[c].mean()) if c.any() else np.nan); sec.append(float(uz.mean()))
    core_ok = np.nan_to_num(core, nan=np.inf)   # no plane point inside the hub radius (a fairing there): not a dead core
    out["core_fill"] = dict(hub_r_mm=hub_r, **{f"length_mm_at_{f:g}": core_fill_length(zs, core_ok, sec, f) for f in FILL},
                            z_mm=zs.round(3).tolist(), core_over_section=(np.array(core)/np.array(sec)).round(4).tolist())
    # card entry, inside the fins
    f = FinModel(**{k: tuple(v) if isinstance(v, list) else v for k, v in meta["options"]["fins"].items()}) if "fins" in meta.get("options", {}) else FINS
    z_fin = L+f.start*1e3+FIN_DEPTH
    xy, U, _ = _probe(mesh, section, z_fin)
    out["card_entry"] = dict(plane_z_mm=z_fin, **port_uniformity(xy, U[:, 2], g, f))
    xy, U, p = _probe(mesh, section, L-BAY_DZ)
    out["bay"] = dict(plane_z_mm=L-BAY_DZ, **bay_deficit(xy, U[:, 2], p+.5*fan.RHO*np.einsum("ij,ij->i", U, U), g))
    if drops is None:
        summary = case/"summary.json"
        drops = (json.loads(summary.read_text()).get("pressure_breakdown") or {}).get("total_pressure_drops_pa", {}) if summary.exists() else {}
    out["loss_pa"] = {k: drops[k] for k in ("duct", "card_face", "intake_duct") if k in drops}
    out["settings"] = dict(core_r_mm=CORE_R, periphery_r_mm=PERIPHERY_R, slow=SLOW, fill=FILL, spacing_mm=spacing)
    return out


def update_summary(case: Path) -> dict:
    """Add (or refresh) `duct_flow` in the case's summary.json. Returns it."""
    case = Path(case); path = case/"summary.json"
    summary = json.loads(path.read_text()) if path.exists() else {}
    summary["duct_flow"] = duct_flow(case)
    path.write_text(json.dumps(summary, indent=2, default=str))
    return summary["duct_flow"]
