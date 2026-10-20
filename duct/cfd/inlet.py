"""Exhaust (pull) fan inlet profile of a solved push-pull case: how evenly the air arrives at the fan.

The axial velocity Uz is sampled on a plane `OFFSET` mm upstream of the exhaust fan (the actuator-disk plane, or the
boundary-model fan patch), inside the fan's approach annulus (hub to blade tip), on a uniform `SPACING` grid of points
interpolated from the cell field. Every collector design gets the same band whatever the mesh level around its fan
(the exhaustFanUpstream faceZone sits a base cell upstream of the disk: inside a collector's plenum, but upstream of
the rear panel for a fan gasketed straight onto it, so it is not used here).

Equal-area points: plain means are area averages; "mass-weighted" values are weighted by the local axial flux
(signed: reverse-flow points count against, as in a net energy flux).
"""
import json
from pathlib import Path

import numpy as np

from . import fan
from .run import case_meta, latest_time

OFFSET = 1.0     # mm upstream of the exhaust fan plane; the approach is 1.6-1.8 mm deep past a collector's fan face
SPACING = 1.0    # mm, sample grid


def _load(case: Path):
    import pyvista as pv
    foam = case/"case.foam"
    if not foam.exists():
        foam.touch()
    reader = pv.POpenFOAMReader(str(foam))
    reader.set_active_time_value(float(latest_time(case)))
    reader.disable_all_patch_arrays()
    reader.enable_patch_array("internalMesh")
    reader.cell_to_point_creation = True
    reader.enable_all_cell_arrays()
    return reader.read()["internalMesh"]


def fan_inlet_profile(case: Path, offset: float = OFFSET, spacing: float = SPACING) -> dict | None:
    """CoV of Uz and the area fraction with Uz < 0 over the exhaust fan's inlet annulus, the dynamic head and the
    mass-weighted static and total pressure there (Pa). None for a case without an exhaust fan."""
    import pyvista as pv
    case = Path(case)
    meta = case_meta(case)
    ex = next((f for f in meta.get("fans", []) if f["role"] == "exhaust"), None)
    if ex is None:
        return None
    (cx, cy, _), z = ex["centre"], ex["z_mm"]-offset
    r0, r1 = ex["hub_radius_mm"], ex["tip_radius_mm"]
    g = np.arange(-r1, r1+1e-9, spacing)
    x, y = (a.ravel() for a in np.meshgrid(g, g))
    r = np.hypot(x, y); keep = (r > r0) & (r < r1)
    pts = np.c_[cx+x[keep], cy+y[keep], np.full(keep.sum(), z)]*1e-3
    probe = pv.PolyData(pts).sample(_load(case), pass_point_data=False)
    valid = np.asarray(probe["vtkValidPointMask"]).astype(bool)
    U = np.asarray(probe["U"])[valid]; p = np.asarray(probe["p"])[valid]*fan.RHO
    uz = U[:, 2]; dyn = .5*fan.RHO*np.einsum("ij,ij->i", U, U)
    area = np.pi*(r1**2-r0**2)*1e-6
    mean = float(uz.mean()); flux = uz.sum()
    return dict(
        plane_z_mm=z, offset_mm=offset, spacing_mm=spacing, points=int(valid.sum()), points_outside=int((~valid).sum()),
        annulus_mm=[r0, r1], centre_mm=[cx, cy],
        uz_mean_mps=mean, uz_cov=float(uz.std()/mean), reverse_area_fraction=float((uz < 0).mean()),
        q_m3s=mean*area,                                              # sampled flux: a check against the exhaust flux
        dynamic_head_pa=float((uz*dyn).sum()/flux),                   # mass-weighted 0.5 rho |U|^2
        dynamic_head_area_pa=float(dyn.mean()),                       # area-mean 0.5 rho |U|^2
        uniform_head_pa=.5*fan.RHO*mean**2,                           # 0.5 rho (Q/A)^2: a uniform inlet's head
        p_pa=float((uz*p).sum()/flux), pt_pa=float((uz*(p+dyn)).sum()/flux))


def update_summary(case: Path) -> dict:
    """Add (or refresh) `fan_inlet` in the case's summary.json, and the per-card statics of the pressure breakdown
    (re-parsed from log.breakdown, no OpenFOAM run). Returns the updated summary."""
    from . import breakdown
    case = Path(case)
    path = case/"summary.json"
    summary = json.loads(path.read_text())
    meta = case_meta(case)
    if (case/"log.breakdown").exists() and summary.get("pressure_breakdown"):
        inlet, exits = breakdown.stations(meta)
        summary["pressure_breakdown"] = breakdown.parse(case/"log.breakdown", exits, meta, inlet)
    summary["fan_inlet"] = fan_inlet_profile(case)
    path.write_text(json.dumps(summary, indent=2, default=str))
    return summary
