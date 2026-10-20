"""Animated streamline video from a solved case (secondary output; the preview page runs the airflow live).

Streamlines are seeded on the fan annulus just downstream of the fan face and animated as dashes moving
at the true relative travel time. Each line gets a random phase offset so the dashes don't march as one band.
CLI wiring (suggested): `duct video CASE --out X.mp4 [--frames 150] [--stl releases/v23/...stl]`.
"""
from pathlib import Path

import numpy as np

from ..cfd.domain import DOMAIN
from .export import load_case


def render_video(case, stl, out_mp4, frames: int = 150, seeds: int = 420, size: tuple[int, int] = (1600, 900),
                 card_envelope_mm: tuple[float, float] = (82.0, 337.0), seed: int = 1) -> Path:
    """Write an mp4 of animated streamlines through the duct STL (mm, CFD frame) and card envelopes."""
    import pyvista as pv
    mesh, _ = load_case(Path(case))
    rng = np.random.default_rng(seed)
    r0, r1 = (DOMAIN.hub_radius+2)*1e-3, (DOMAIN.approach_radius-1.5)*1e-3
    r = np.sqrt(rng.uniform(r0**2, r1**2, seeds))
    t = rng.uniform(0, 2*np.pi, seeds)
    lines = mesh.streamlines_from_source(
        pv.PolyData(np.c_[r*np.cos(t), r*np.sin(t), np.full(seeds, .002)]), vectors="U",
        integration_direction="forward", max_steps=4000, initial_step_length=.2, step_unit="cl",
        max_length=.6, compute_vorticity=False)

    # Travel time along each line, so dashes move at the true relative speed; one random phase per line.
    speed = np.linalg.norm(lines["U"], axis=1)
    tof = np.zeros(lines.n_points)
    segs, line_of_seg = [], []
    for i in range(lines.n_cells):
        ids = np.asarray(lines.get_cell(i).point_ids)
        seg = np.linalg.norm(np.diff(lines.points[ids], axis=0), axis=1)
        v = .5*(speed[ids][1:]+speed[ids][:-1])+1e-6
        tof[ids] = np.concatenate([[0], np.cumsum(seg/v)])
        segs.append(np.c_[np.full(len(ids)-1, 2), ids[:-1], ids[1:]])
        line_of_seg.append(np.full(len(ids)-1, i))
    segs, line_of_seg = np.vstack(segs), np.concatenate(line_of_seg)
    seg_mesh = pv.PolyData(lines.points.copy(), lines=segs.ravel())
    seg_mesh["speed"] = speed
    seg_tof = .5*(tof[segs[:, 1]]+tof[segs[:, 2]])
    period = np.percentile(tof, 90)
    dash = period/9
    seg_tof = seg_tof+rng.uniform(0, dash, lines.n_cells)[line_of_seg]
    clim = (0, np.percentile(speed, 98))

    duct = pv.read(str(stl)).scale(.001, inplace=False)
    pl = pv.Plotter(off_screen=True, window_size=size)
    pl.set_background("#0b0d10", top="#1c2128")
    pl.enable_anti_aliasing("ssaa")
    pl.add_mesh(duct, color="#c9a46a", opacity=.18, smooth_shading=True, specular=.3)
    pl.add_mesh(duct.extract_feature_edges(25), color="#e8c98f", opacity=.35, line_width=1)
    z0, z1 = (v*1e-3 for v in card_envelope_mm)
    for cx in (-.03048, .03048):
        pl.add_mesh(pv.Box((cx-.0192, cx+.0192, -.049, .049, z0, z1)), color="#5a6270", opacity=.22, smooth_shading=True)
    pl.add_mesh(pv.Disc(center=(0, 0, -.0005), inner=DOMAIN.hub_radius*1e-3, outer=DOMAIN.approach_radius*1e-3, c_res=96),
                color="#3a7bd5", opacity=.35)
    pl.add_mesh(lines, color="white", opacity=.04, line_width=1)
    sbar = dict(title="Air speed (m/s)", color="white", vertical=False, position_x=.3, position_y=.04, width=.4)
    actor = None
    out = Path(out_mp4)
    out.parent.mkdir(parents=True, exist_ok=True)
    pl.open_movie(str(out), framerate=30, quality=8, macro_block_size=1)
    for f in range(frames):
        phase = f/frames*dash*6
        saw = ((seg_tof-phase) % dash)/dash
        dashes = seg_mesh.extract_cells(np.flatnonzero(saw < .35)).extract_surface()
        if actor is not None:
            pl.remove_actor(actor)
        actor = pl.add_mesh(dashes, scalars="speed", cmap="turbo", clim=clim, line_width=3,
                            render_lines_as_tubes=True, show_scalar_bar=actor is None, scalar_bar_args=sbar)
        az = np.radians(-38+30*f/frames)
        pl.camera.focal_point = (0, 0, .13)
        pl.camera.position = (.46*np.sin(az), .17, .13-.46*np.cos(az))
        pl.camera.up = (0, 1, 0)
        pl.write_frame()
    pl.close()
    return out
