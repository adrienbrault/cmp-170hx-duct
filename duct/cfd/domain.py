"""CFD fluid surface: duct air passage, fan approach and card envelopes, with patch classification.

CAD units (mm) in; the surface is written in metres. Extra solids (e.g. a push-pull exhaust
collector) are unioned in, and extra rules classify their faces before the default rules.
"""
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import manifold3d as mf
import numpy as np
import trimesh

from ..cad.geometry import cube, cylinder, union
from ..params import GeometryParams
from . import fan

PATCHES = ("walls", "cardWalls", "inlet", "outletLeft", "outletRight")
TOL = 1e-7  # m, plane-membership tolerance of the classification rules

# (patch, predicate over (n, 3, 3) triangle vertices in m -> bool mask); first match wins.
Rule = tuple[str, Callable[[np.ndarray], np.ndarray]]


@dataclass(frozen=True)
class DomainParams:
    hub_radius: float = fan.HUB_RADIUS*1e3        # fan hub; the approach is an annulus
    approach_radius: float = fan.TIP_RADIUS*1e3   # fan blade tip
    approach_depth: float = 5.0      # approach starts this far upstream of the fan face; inlet patch
    approach_lip: float = 0.0        # disk model: quarter-round radius rounding the approach annulus's outer entry edge (a bellmouth
                                     # into the intake room, whose downstream face moves this far upstream); 0: the sharp edge
    card_envelope: float = 267.0     # card port boxes extend this far past the seat face; outlet patches
    simplify: float = .002           # manifold simplification tolerance


DOMAIN = DomainParams()


def fluid_solid(g: GeometryParams, inner: mf.Manifold, d: DomainParams = DOMAIN,
                extra: Sequence[mf.Manifold] = (), port_cut: float = 0.0) -> mf.Manifold:
    """Union of the duct air passage, a thin fan-face bridging disk, the hub annulus approach and the card ports;
    `port_cut` (mm) stops the ports short of the card exit plane (the bracket plate's thickness). With the hub fairing
    (GeometryParams.hub_fairing) the bridge is an annulus outside its base: the fairing continues the hub."""
    L = g.chamber_length
    bridge = cylinder(g.fan_radius, .01, -.005)
    if g.hub_fairing:
        bridge -= cylinder(g.hub_fairing_d/2, .03, -.015)
    approach = (cylinder(d.approach_radius, d.approach_depth+.01, -d.approach_depth)
                - cylinder(d.hub_radius, d.approach_depth+.01, -d.approach_depth))
    ports = [cube([x1-x0, y1-y0, d.card_envelope+.005-port_cut], [x0, y0, L-.005]) for _, _, (x0, x1, y0, y1) in g.port_boxes]
    return union(inner, bridge, approach, *ports, *extra).as_original().simplify(d.simplify)


def to_metres(solid: mf.Manifold) -> trimesh.Trimesh:
    raw = solid.to_mesh64()
    mesh = trimesh.Trimesh(vertices=np.asarray(raw.vert_properties)[:, :3], faces=np.asarray(raw.tri_verts), process=True)
    assert mesh.is_watertight, "fluid surface is not watertight"
    return mesh.apply_scale(.001)


def classify(mesh: trimesh.Trimesh, g: GeometryParams, d: DomainParams = DOMAIN,
             rules: Sequence[Rule] = ()) -> dict[str, np.ndarray]:
    """Face indices per patch for a fluid surface in metres. Extra rules run first, in order; a rule
    may reuse a default patch name (e.g. collector faces into `walls`), and its faces are merged."""
    tri = mesh.triangles; x, z = tri[:, :, 0], tri[:, :, 2]
    L, exit_z = g.chamber_length*.001, (g.chamber_length+d.card_envelope)*.001
    on = lambda plane: np.abs(z-plane).max(1) < TOL  # noqa: E731
    outlet = on(exit_z)
    default = [
        ("inlet", on(-d.approach_depth*.001)),
        ("outletLeft", outlet & (x.mean(1) < 0)),
        ("outletRight", outlet & (x.mean(1) >= 0)),
        ("cardWalls", (z.min(1) >= L-TOL) & (np.ptp(z, 1) > 1e-6)),
        ("walls", np.ones(len(tri), bool)),
    ]
    free = np.ones(len(tri), bool); groups = {}
    for name, mask in [(n, p(tri)) for n, p in rules]+default:
        picked = np.flatnonzero(mask & free); free &= ~mask
        groups[name] = np.union1d(groups[name], picked) if name in groups else picked
    order = dict.fromkeys(list(PATCHES)+[n for n, _ in rules])
    return {n: groups[n] for n in order}


def write_stl(mesh: trimesh.Trimesh, groups: dict[str, np.ndarray], path: Path) -> None:
    """Multi-solid ASCII STL; snappyHexMesh names each solid as a region of the `fluid` surface."""
    lines = []
    for name, idx in groups.items():
        assert len(idx), f"empty patch {name}"
        tri = mesh.triangles[idx]
        n = np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0]); norm = np.linalg.norm(n, axis=1)[:, None]
        n = np.divide(n, norm, out=np.zeros_like(n), where=norm > 0)  # zero-area facet: 0 normal (OpenFOAM rejects nan)
        lines.append(f"solid {name}")
        for t, nv in zip(tri.tolist(), n.tolist()):
            lines.append("facet normal "+" ".join(f"{v:.9g}" for v in nv)+"\nouter loop")
            lines.extend("vertex "+" ".join(f"{c:.9g}" for c in v) for v in t)
            lines.append("endloop\nendfacet")
        lines.append(f"endsolid {name}")
    Path(path).write_text("\n".join(lines)+"\n")


def patch_areas(mesh: trimesh.Trimesh, groups: dict[str, np.ndarray]) -> dict[str, float]:
    return {n: float(mesh.area_faces[i].sum()) for n, i in groups.items()}
