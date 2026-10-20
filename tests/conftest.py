"""Suite-wide test setup: the build cache and the `slow` tier (docs/testing.md).

1. Build cache. Every duct/collector build and export in the suite goes through duct.cache (content-addressed by params,
   source and library versions), so V23/V29/A29/collector builds are made once and reused within a run and across runs.
   The drop-ins are installed on the CAD modules here, before any test module imports them. DUCT_CACHE=0 runs the
   suite from source with no cache.

2. Parallel runs: `pytest -n 4 --dist loadfile` (pytest-xdist, docs/testing.md). Workers that need the same part wait for
   the one building it (a lock in duct.cache) and load it; each worker runs the printability gates in-process
   (DUCT_GATE_WORKERS=1) instead of four gate processes per worker.

3. Tiers. `pytest -m "not slow"` is the fast tier (logic of every module, one V23 duct and one v1 collector build);
   plain `pytest` is the full suite and the release gate. Tests are marked slow here, centrally, by node id and by the
   heavy fixtures they use, rather than in each test file: a new test that uses a heavy fixture is slow automatically.
"""
import os
from fnmatch import fnmatch

import pytest

import duct.cad.exhaust
import duct.cad.export
import duct.cad.geometry
from duct import cache

# `cache` captured the real builders when it was imported; only now replace the module attributes.
duct.cad.geometry.build_duct = cache.build_duct
duct.cad.exhaust.build_collector = cache.build_collector
duct.cad.export.export_duct = cache.export_duct
duct.cad.export.export_collector = cache.export_collector

if os.environ.get('PYTEST_XDIST_WORKER'): os.environ.setdefault('DUCT_GATE_WORKERS', '1')   # the workers are the parallelism


# Tests that need a full duct build other than V23, a collector other than v1, the OpenFOAM mesher, or the full
# gates on a released duct STL. (Bambu Studio slices even V29 in ~3 s.) Node-id patterns (fnmatch), relative to the repo root.
SLOW_TESTS = [
    'tests/test_adjacent.py::test_3slot_family_rebuilds_byte_identical*',  # V28 and V29 rebuilt and exported
    'tests/test_cache.py::test_duct_from_disk_matches_a_fresh_build',      # V23 through a cold cache
    'tests/test_cad.py::test_dilation_memo_is_byte_identical',             # V23 built from source and exported
    'tests/test_cache.py::test_collector_export_served_matches_a_fresh_build',
    'tests/test_domain.py::test_mesh_coarse',                              # OpenFOAM blockMesh/snappyHexMesh
    'tests/test_exhaust.py::test_screw_mode_clears_thumb_screws',          # a second collector build
    'tests/test_fast.py::test_preview_agrees_with_the_full_gates*',        # full and preview gates on every released part
    'tests/test_hardware.py::test_v3_air_volume_contract*',                # v3 and v3l builds
    'tests/test_printability.py::test_v24_overhangs_pass',                 # overhang gate on the released V24
    'tests/test_printability.py::test_parallel_gates_match_serial',        # full gates x3 on a released collector
    'tests/test_preview_pages.py::test_release_page_without_a_field_draws_the_collector',   # the plug built and exported
]

# Module-scoped fixtures that build a part (or run the full gates): any test using one is slow.
HEAVY_FIXTURES = {
    'tests/test_adjacent.py': {'built_a29'},
    'tests/test_cad.py': {'built24', 'built27', 'built_sealed'},
    'tests/test_hardware.py': {'v2', 'v3', 'fit2', 'fit3'},
    'tests/test_printability.py': {'v25'},
}


def pytest_configure(config):
    config.addinivalue_line('markers', 'slow: full builds of the heavier presets, the slicer, full gates on released parts; '
                                       'deselect with -m "not slow" (docs/testing.md)')


def _is_slow(item) -> bool:
    nodeid = item.nodeid
    path = nodeid.split('::', 1)[0]
    if not path.startswith('tests/'): nodeid = 'tests/'+nodeid; path = 'tests/'+path   # run from inside tests/
    return any(fnmatch(nodeid, p) for p in SLOW_TESTS) or bool(HEAVY_FIXTURES.get(path, set()) & set(item.fixturenames))


def pytest_collection_modifyitems(config, items):
    for item in items:
        if _is_slow(item): item.add_marker(pytest.mark.slow)
