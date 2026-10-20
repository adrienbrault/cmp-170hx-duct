"""Fast printability preview for design iteration. NOT a release check.

The same geometric gates as duct.print.printability.run_gates (unsupported_overhang, solid_regions, seal, seat_coverage)
with the same allowlists and limits, on a coarser mesh and voxel grid:
- the mesh is simplified to PREVIEW_TOLERANCE (V29: 323k -> ~58k triangles);
- seal (b) uses PREVIEW.voxel (0.6 mm: still two voxels across the 1.2 mm wall);
- the slicer gate, when asked for (`slicer=`), slices the STL as given: Bambu Studio takes ~3 s even on V29's 323k
  triangles, so coarsening it would save nothing (without it, tier B of unsupported_overhang still applies the slicer's
  support rule geometrically).
A part built from params goes through duct.cache, so an unchanged design is not rebuilt.

Draft geometry (`draft(g)`, `duct verify --fast --draft`): the duct with a coarser shell dilation (DRAFT: a 16-segment
kernel on the passage skin simplified to 0.01 mm, several times faster to build), for iterating on a design only. It is
a different shape from the release geometry (facets up to ~0.01 mm off), so its results say so (draft=True, DRAFT_LABEL)
and duct.print.release refuses it.

A preview result carries release_check=False and LABEL. duct.print.release always runs the full gates (default
Thresholds, the exported STL, the slicer) and refuses on any failure: a preview never stands in for them. tests/test_fast.py
measures that the preview agrees with the full gates on the released parts.
"""
import time
from dataclasses import dataclass, replace
from pathlib import Path

import manifold3d as mf
import numpy as np
import trimesh

from ..params import GeometryParams
from . import printability as P

PREVIEW_TOLERANCE = 0.02                 # mm: Manifold.simplify of the mesh (the release exports: 0.0025-0.01)
PREVIEW = replace(P.Thresholds(), voxel=0.6)
LABEL = (f'FAST PREVIEW - NOT A RELEASE CHECK: geometric gates on the mesh simplified to {PREVIEW_TOLERANCE} mm, seal voxels '
         f'{PREVIEW.voxel} mm. `duct release` runs the full gates and refuses on any failure.')
DRAFT = dict(shell_simplify=0.01, kernel_segments=16.0)   # the draft shell dilation (release: 0.002 mm, 32 segments since V24)
DRAFT_LABEL = (f'DRAFT GEOMETRY - NOT FOR RELEASE: the shell dilation coarsened to {DRAFT}; `duct release` refuses draft '
               'params and builds the release geometry.')


@dataclass(frozen=True)
class DraftParams(GeometryParams):
    """GeometryParams of a draft build (draft()): its own type, so the build cache keys it apart and release refuses it."""


def draft(g: GeometryParams) -> DraftParams:
    """g with the coarser DRAFT shell dilation, for iteration only (see the module docstring). NOT for release."""
    return DraftParams(**{**{f: getattr(g, f) for f in g.__dataclass_fields__}, **DRAFT})


def coarse(mesh, tolerance: float = PREVIEW_TOLERANCE) -> trimesh.Trimesh:
    """The part simplified to `tolerance`, as the float32 mesh the gates load (z = 0 stays the bed)."""
    m = mesh if isinstance(mesh, trimesh.Trimesh) else trimesh.load(Path(mesh))
    s = mf.Manifold(mf.Mesh(np.asarray(m.vertices, dtype=np.float32), np.asarray(m.faces, dtype=np.uint32)))
    s = s.set_tolerance(tolerance).simplify(tolerance)
    assert s.status() == mf.Error.NoError and not s.is_empty(), s.status()
    raw = s.to_mesh()
    return trimesh.Trimesh(np.asarray(raw.vert_properties)[:, :3], np.asarray(raw.tri_verts), process=False)


def preview_gates(stl, spec: P.PartSpec, tolerance: float = PREVIEW_TOLERANCE, t: P.Thresholds = PREVIEW,
                  slicer: dict | None = None) -> dict:
    """run_gates' result for `stl` (a path or a trimesh) at preview resolution, labelled as a preview. `slicer`:
    slicer_support kwargs (out_dir, ...) to add the slicer gate, run on `stl` itself (a path)."""
    t0 = time.perf_counter()
    m = coarse(stl, tolerance)
    result = P.run_gates(m, spec, t)
    if slicer is not None:
        g = P.slicer_support(stl, t=t, spec=spec, **slicer)
        result['gates'][g.name] = g.to_dict()
        result['passed'] = result['passed'] and g.passed
        if not g.passed: result['failed'].append(g.name)
    result.update(release_check=False, label=LABEL,
                  preview=dict(tolerance_mm=tolerance, voxel_mm=t.voxel, triangles=len(m.faces),
                               slicer='on the given STL' if slicer is not None else 'not run',
                               seconds=round(time.perf_counter()-t0, 2)))
    return result


def preview_duct(g, stl=None, tolerance: float = PREVIEW_TOLERANCE, version: str = 'preview', slicer: dict | None = None) -> dict:
    """Preview gates of the duct `g`: of `stl` when given, else of g's export (through duct.cache: a design built and
    exported before, by `duct cad`, `duct verify` or the tests, is not rebuilt; `version` only names the files). The
    CAD-side sweep collisions are added when the solids are at hand."""
    from .. import cache
    extra = {}
    if stl is None:
        from ..cad.export import stl_name
        stl = cache.duct_export_dir(g, version)/stl_name(version)   # first: on a miss it builds, and build_duct reuses that
        s = cache.build_duct(g)
        extra = dict(plug_latch_collisions_mm3=list(s.plug_latch_collisions_mm3), bay_collisions_mm3=list(s.bay_collisions_mm3))
    if isinstance(g, DraftParams): extra.update(draft=True, draft_label=DRAFT_LABEL)
    return {**preview_gates(stl, P.duct_spec(g), tolerance, slicer=slicer), **extra}


def preview_collector(c, stl=None, tolerance: float = PREVIEW_TOLERANCE, version: str = 'collector-preview',
                      slicer: dict | None = None) -> dict:
    """Preview gates of the collector `c`: of `stl` when given, else of c's export under `version` (as preview_duct)."""
    from .. import cache
    if stl is None:
        from ..cad.export import collector_names
        stl = cache.collector_export_dir(c, version)/collector_names(version)[0]
    return preview_gates(stl, P.collector_spec(c), tolerance, slicer=slicer)
