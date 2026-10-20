"""Duct-shape diagnostics from a solved case: flow split, card-face uniformity, total-pressure loss and loss hotspots.

Pressures in the case are kinematic (p/ρ); results here are in Pa with ρ = 1.2. The card face is
sampled just inside the fin ports (L + 2 mm), upstream of the porous zones (L + 8 mm).
"""
import numpy as np

RHO = 1.2
FACE_OFFSET_MM = 2.0     # card-face sampling plane, past the seat face
FAN_FACE_MM = 1.0        # fan-face sampling plane, just downstream of the bridging disk
PORT_NAMES = ("main", "lower side", "upper side")


def _plane(mesh, z_m: float):
    """Slice at z with cell areas, cell-centre Uz and total pressure (kinematic)."""
    sl = mesh.slice(normal="z", origin=(0, 0, z_m))
    U = np.asarray(sl.point_data["U"])
    sl.point_data["pt"] = np.asarray(sl.point_data["p"])+.5*(U**2).sum(1)
    sl.point_data["w"] = U[:, 2]
    cells = sl.point_data_to_cell_data().compute_cell_sizes(length=False, area=True, volume=False)
    return dict(xy=np.asarray(cells.cell_centers().points)[:, :2]*1e3, area=np.asarray(cells["Area"]),
                w=np.asarray(cells["w"]), pt=np.asarray(cells["pt"]))


def _mass_mean(s, sel=slice(None)):
    q = s["w"][sel]*s["area"][sel]
    return float((s["pt"][sel]*q).sum()/q.sum())


def card_face(mesh, ports, L_mm: float) -> dict:
    """Flow per card and per port, and the Uz uniformity index over the port areas, at L + FACE_OFFSET_MM.
    ports: [(card, port, (x0, x1, y0, y1)) mm]."""
    s = _plane(mesh, (L_mm+FACE_OFFSET_MM)*1e-3)
    x, y = s["xy"].T
    flows, inside = {}, np.zeros(len(x), bool)
    for card, port, (x0, x1, y0, y1) in ports:
        sel = (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)
        inside |= sel
        flows[(card, port)] = float((s["w"][sel]*s["area"][sel]).sum())
    total = sum(flows.values())
    cards = [sum(v for (c, _), v in flows.items() if c == i) for i in (0, 1)]
    w, a = s["w"][inside], s["area"][inside]
    mean = (w*a).sum()/a.sum()
    sigma = np.sqrt(((w-mean)**2*a).sum()/a.sum())
    return dict(
        plane_z_mm=L_mm+FACE_OFFSET_MM, flow_m3s=total,
        card_split_pct=[100*c/total for c in cards],
        port_split_pct=[[100*flows[(c, p)]/cards[c] for p in range(len(PORT_NAMES))] for c in (0, 1)],
        port_names=list(PORT_NAMES), uniformity=float(1-sigma/mean), uz_mean=float(mean), uz_sigma=float(sigma),
        pt_mass_mean=_mass_mean(s, inside),
    )


def hotspots(grid, z_range_mm: tuple[float, float], n: int = 3, separation_mm: float = 15.0) -> list[dict]:
    """Top-n local maxima of |∇p_total| (Pa/mm) on the export grid, at interior fluid nodes (all six
    neighbours fluid, so wall-adjacent nodes don't dominate), separated by at least separation_mm."""
    pt = grid.fields["p"]+.5*(grid.U**2).sum(-1)
    h = grid.spacing_mm
    gz, gy, gx = np.gradient(pt, h)
    mag = np.sqrt(gx**2+gy**2+gz**2)*RHO
    m = grid.mask
    interior = m.copy()
    for ax in range(3):
        for sh in (1, -1):
            interior &= np.roll(m, sh, axis=ax)
    nz, ny, nx = m.shape
    z = grid.origin_mm[2]+np.arange(nz)*h
    interior &= ((z >= z_range_mm[0]) & (z <= z_range_mm[1]))[:, None, None]
    cand = np.flatnonzero(np.where(interior, mag, 0).ravel())
    order = cand[np.argsort(-mag.ravel()[cand])]
    out = []
    for idx in order:
        k, j, i = np.unravel_index(idx, m.shape)
        p = np.array(grid.origin_mm)+h*np.array([i, j, k])
        if all(np.linalg.norm(p-np.array(o["xyz_mm"])) >= separation_mm for o in out):
            out.append(dict(xyz_mm=[round(float(v), 1) for v in p], grad_pa_per_mm=float(mag[k, j, i])))
        if len(out) == n:
            break
    return out


def analyse(mesh, grid, ports, L_mm: float, collar_mm: float, fan_total_pa: float | None) -> dict:
    fan_face = _plane(mesh, FAN_FACE_MM*1e-3)
    face = card_face(mesh, ports, L_mm)
    loss = (_mass_mean(fan_face)-face["pt_mass_mean"])*RHO
    return dict(
        **face, duct_loss_pa=float(loss), fan_total_pa=fan_total_pa,
        duct_loss_pct_of_fan=100*loss/fan_total_pa if fan_total_pa else None,
        hotspots=hotspots(grid, (FAN_FACE_MM+2, L_mm+collar_mm)),
    )
