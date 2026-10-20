# Testing and the design loop

## Test tiers

```sh
uv run pytest -m "not slow"   # fast tier: every module's logic; one V23 duct and one v1 collector build
uv run pytest                 # full suite: the release gate
DUCT_CACHE=0 uv run pytest    # full suite with no build cache: every part built from source
uv run pytest -n 4 --dist loadfile   # either tier on 4 pytest-xdist workers (recommended for the full suite)
```

Parallel runs (`-n 4 --dist loadfile`, pytest-xdist in the dev group): `loadfile` keeps each test file on one worker, so
its module fixtures and per-file build dicts are made once. Workers that need the same part wait for the one building it
(a file lock per cache entry in `duct.cache`) and then load it instead of building it again, and each worker runs the
printability gates in-process (`DUCT_GATE_WORKERS=1`, set by `tests/conftest.py`). `-n` is not in the pytest addopts:
`pytest -k one_test` stays a plain single-process run.

The fast tier is for the inner loop. The full suite is the release gate: run it before committing geometry, gate or
export changes, and before `duct release`.

Measured (2026-10, a shared and loaded M-series machine, so treat as upper bounds): fast tier 27 s with a warm build
cache, 1 min 40 s cold; full suite 7 min warm, against 2 h before the cache on the same loaded machine (23-33 min
unloaded), where six full builds of V24-A29 took 91 % of the time. Later (2026-10-19, same loaded machine, 318 tests):
full suite cold 29 min serial / 22 min with `-n 4`, warm 7 min 40 s serial / 2 min 44 s with `-n 4`; fast tier warm
3 min 20 s (it now includes the v4 collectors and the push-aero ducts). Cache keys follow only the code a part reaches,
so most commits (a new preset, docs, CFD, the other part) keep the suite warm.

Tests are marked `slow` centrally in `tests/conftest.py` (`SLOW_TESTS` node-id patterns, and `HEAVY_FIXTURES`: a test that
uses a fixture building a heavier preset is slow automatically). Slow means a full build of a preset other than V23, a
collector other than v1, the OpenFOAM mesher, or the full gates on a released duct STL (the slicer stays in the fast
tier: Bambu Studio slices even V29 in ~3 s). When you add such a test, either use one of those fixtures or add its node
id to `SLOW_TESTS`.

## Build cache

Every duct and collector build and export in the test suite, `duct cad` and `duct verify` goes through `duct.cache`.
Entries live in `build/cache/` (gitignored), keyed by the sha256 of everything that affects the output: the params
dataclass repr (every field), the code the part reaches (every module-level definition of the `duct` package that the
builder, and for exports the exporter, can reach through names, imports and module aliases, hashed as its AST, plus the
params class and the cache's serialization), the Python/numpy/scipy/shapely/trimesh/manifold3d versions and platform, and for
exports the simplification tolerances (the version name only names the files: one entry serves every name). Change a parameter, code the part reaches or a library and you get a new
entry, never a stale one; a new preset, a comment, a docstring or an edit to code the part does not reach (the collector
for the duct, the duct builder for the collector, the CFD) keeps it (`tests/test_cache.py`). Old entries are only left
behind: `rm -rf build/cache` when it grows.

- `DUCT_CACHE=0` turns it off; `DUCT_CACHE_DIR=/path` moves it (e.g. one cache shared by several worktrees).
- `duct release` never uses it: a release always builds from source.
- Exports are always made from solids built in the process, never from solids reloaded from the cache (manifold3d's
  internal state does not survive the mesh round trip exactly), so exporting a cached design at new tolerances rebuilds it once. `duct cad` then
  `duct verify --fast --preset ... --param ...` on the same design does not rebuild.

A design you already built (by the tests, `duct cad` or `duct verify`) loads in about 0.1 s; a new design (any
`--param` change) is a full build: V23 20-30 s, the V24+ presets with the 3-D shell dilation minutes (V29: about 5 min,
16 min in the saturated baseline run). The shell dilation (`geometry.dilate`, ~95 % of a build) is memoised in the
process by its exact input meshes, so presets that differ only downstream of it (V29 and V30, A29 and A30: the hub
fairing) dilate once per process (V30 after V29: ~9 s, byte-identical STLs). It is not cached on disk: manifold3d 3.5.4
does not restore a solid's tolerance from its mesh (the dilation's 8e-6 mm comes back as 7e-11, and `set_tolerance`
re-simplifies it), so a reloaded dilation exports a different STL.

## Parallel gates

`printability.run_gates` runs the four geometric gates in separate Python processes (plain subprocesses importing `duct`
from the caller's `sys.path`; each loads the STL itself) and the slicer gate meanwhile in the caller; the result is the
same as in-process, key order included (`tests/test_printability.py`). `DUCT_GATE_WORKERS=1` runs them in-process,
`DUCT_GATE_WORKERS=n` caps the processes (default: up to 4). `duct release` also runs its slices (automatic supports, the
no-supports trial, a collector's fit gauge) alongside the geometric gates; the slicer gate waits for the supports slice.
Bambu Studio is not deterministic run to run even serially (the minutes can differ in the fourth digit), so
slicer-checks.json numbers may move by that much on any re-release.

## Fast gate preview: `duct verify --fast` (NOT a release check)

```sh
duct verify --fast releases/v29/dual-170hx-continuous-v29.stl --preset v29   # preview an STL
duct verify --fast --preset v29 --param upper_radius=5                      # preview a design (built through the cache)
duct verify --fast --part collector --collector v2                          # preview a collector preset
```

Python: `duct.print.fast.preview_gates(stl, spec)`, `preview_duct(g)`, `preview_collector(c)`.

Draft geometry, for iterating on a design only: `duct verify --fast --draft --preset v30 [--param ...]` (Python:
`preview_duct(fast.draft(g))`) builds the duct with a coarser shell dilation (`fast.DRAFT`: the passage skin simplified
to 0.01 mm, a 16-segment kernel; release: 0.002 mm, 32), about 4x faster to build (V30 preview cold: ~1 min against
~4-5 min). It is a different shape (facets up to ~0.01 mm off), so its output carries `DRAFT GEOMETRY - NOT FOR RELEASE`
and `draft: true`, it is cached under its own type (`DraftParams`), and `duct release` refuses it.

The preview runs the same geometric gates as the release (overhang tiers A and B, solid regions, seal, seat coverage)
with the same allowlists and limits, on the mesh simplified to 0.02 mm and 0.6 mm seal voxels, plus the slicer gate on
the STL as given (`--no-slice` skips it), without the CAD-vs-STL checks of `verify()`. Its output says
`FAST PREVIEW - NOT A RELEASE CHECK`, and results carry `release_check: false`. `duct release` always runs the full gates
on the exported STL and refuses on any failure.

Agreement of the geometric gates with the full ones on the released parts (`tests/test_fast.py`, slow tier): the same
gates fail with as many findings, at the same places and sizes within about 1 %:

| part | full gates fail | preview | full s | preview s |
|---|---|---|---|---|
| V25 | overhang, solid, seat | same | 21 | 11 |
| V27 | seat | same | 14 | 9 |
| V28 | seat (latch notch over the open-area budget) | same | 18 | 10 |
| V29 | - | same | 24 | 9 |
| A29 | - | same | 31 | 12 |
| collector v1 / v2 / v3 | - | same | 6 / 5 / 5 | 4 / 3 / 3 |

(Times on a heavily loaded machine.) At 0.05 mm collector v2's seal already disagrees, so 0.02 mm is the coarsest
setting kept.

Where the time goes: the build takes minutes; the full geometric gates on V29's 323k-triangle STL 12-25 s depending on
load, the slicer ~3 s. `duct verify --fast` on V29 (STL or cached preset) takes 8-9 s, `duct verify` 21 s with the
cached build (before the cache it also rebuilt V29). A parameter change still pays one full build before its first
preview: the preview cannot skip that without gating different geometry.
