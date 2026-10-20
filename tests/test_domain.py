import json
import math
import re
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import trimesh
from scipy.spatial import cKDTree

from duct import env
from duct.cad.geometry import build_duct
from duct.cfd import case, domain, mesh, porous
from duct.params import V23

ROOT = Path(__file__).resolve().parents[1]
# Prefer `tar -xzf fixtures/validation.tgz -C runs/fixtures` (gitignored); fixtures/upper-r6 also works.
FIXTURE = next((p for p in (ROOT/'runs/fixtures/upper-r6', ROOT/'fixtures/upper-r6') if p.exists()), ROOT/'runs/fixtures/upper-r6')
needs_fixture = pytest.mark.skipif(not FIXTURE.exists(), reason='validation fixture not extracted')


@pytest.fixture(scope='module')
def inner():
    return build_duct(V23).inner


@pytest.fixture(scope='module')
def surface(inner):
    m = domain.to_metres(domain.fluid_solid(V23, inner))
    return m, domain.classify(m, V23)


@pytest.fixture(scope='module')
def built(inner, tmp_path_factory):
    out = tmp_path_factory.mktemp('case')
    # the upper-r6 fixture: no bracket plate, legacy 17 mm fan hub
    o = case.CaseOptions(shoulder_refine=True, bracket=None, domain=domain.DomainParams(hub_radius=17.0))
    return out, case.build(out, V23, o, inner=inner)


def test_patch_set_and_areas(surface):
    m, groups = surface
    assert list(groups) == list(domain.PATCHES)
    assert sum(len(i) for i in groups.values()) == len(m.faces)
    a = domain.patch_areas(m, groups)
    n, d = 128, domain.DOMAIN   # manifold cylinders have 128 segments
    annulus = .5*n*math.sin(2*math.pi/n)*(d.approach_radius**2-d.hub_radius**2)*1e-6
    assert a['inlet'] == pytest.approx(annulus, rel=1e-9)
    for card, patch in enumerate(['outletLeft', 'outletRight']):
        rects = sum((x1-x0)*(y1-y0) for c, _, (x0, x1, y0, y1) in V23.port_boxes if c == card)*1e-6
        assert a[patch] == pytest.approx(rects, rel=1e-9)
    assert np.all(m.triangles[groups['cardWalls']][:, :, 2] >= V23.chamber_length*1e-3-domain.TOL)


def test_extra_rule_runs_first(surface):
    m, _ = surface
    exit_z = (V23.chamber_length+domain.DOMAIN.card_envelope)*1e-3
    rule = ('collector', lambda t: np.abs(t[:, :, 2]-exit_z).max(1) < domain.TOL)
    groups = domain.classify(m, V23, rules=[rule])
    assert list(groups)[-1] == 'collector' and len(groups['collector']) == 12
    assert len(groups['outletLeft']) == len(groups['outletRight']) == 0


def _stl_patches(path):
    return {n: g for n, g in trimesh.load(path).geometry.items()}


def _point_triangle_distance(p, a, b, c):
    """Exact distance from points p to triangles (a, b, c), row by row (Ericson, Real-Time Collision Detection 5.1.5)."""
    dot = lambda u, v: np.einsum('ij,ij->i', u, v)  # noqa: E731
    ab, ac, ap = b-a, c-a, p-a
    d1, d2 = dot(ab, ap), dot(ac, ap)
    bp, cp = p-b, p-c
    d3, d4, d5, d6 = dot(ab, bp), dot(ac, bp), dot(ab, cp), dot(ac, cp)
    va, vb, vc = d3*d6-d5*d4, d5*d2-d1*d6, d1*d4-d3*d2
    with np.errstate(divide='ignore', invalid='ignore'):
        denom = va+vb+vc
        v, w = vb/denom, vc/denom
        q = a+ab*v[:, None]+ac*w[:, None]                                    # interior
        for mask, pt in [
            ((vc <= 0) & (d1 >= 0) & (d3 <= 0), a+ab*(d1/(d1-d3))[:, None]),   # edge ab
            ((vb <= 0) & (d2 >= 0) & (d6 <= 0), a+ac*(d2/(d2-d6))[:, None]),   # edge ac
            ((va <= 0) & (d4-d3 >= 0) & (d5-d6 >= 0), b+(c-b)*((d4-d3)/((d4-d3)+(d5-d6)))[:, None]),  # edge bc
            ((d1 <= 0) & (d2 <= 0), a), ((d3 >= 0) & (d4 <= d3), b), ((d6 >= 0) & (d5 <= d6), c)]:
            q = np.where(mask[:, None], pt, q)
    return np.linalg.norm(p-q, axis=1)


def _one_sided_hausdorff(points, mesh, max_edge=2e-3):
    """max over points of the exact distance to `mesh`. Subdividing to max_edge bounds every triangle's
    centroid radius by r, so the nearest triangle's centroid lies within (kNN upper bound + r)."""
    v, f = trimesh.remesh.subdivide_to_size(mesh.vertices, mesh.faces, max_edge)
    tri = v[f]; c = tri.mean(1); r = np.linalg.norm(tri-c[:, None], axis=2).max()
    dist = lambda i, t: _point_triangle_distance(points[i], tri[t, 0], tri[t, 1], tri[t, 2])  # noqa: E731
    _, near = cKDTree(c).query(points, k=4)
    upper = dist(np.repeat(np.arange(len(points)), 4), near.ravel()).reshape(near.shape).min(1)
    balls = cKDTree(c).query_ball_point(points, upper+r)
    i = np.repeat(np.arange(len(points)), [len(x) for x in balls]); t = np.concatenate(balls).astype(int)
    d = np.full(len(points), np.inf); np.minimum.at(d, i, dist(i, t))
    return d.max()


@needs_fixture
def test_flow_stl_matches_old_builder(built):
    out, _ = built
    new, old = _stl_patches(out/'constant/triSurface/flow.stl'), _stl_patches(FIXTURE/'constant/triSurface/flow.stl')
    assert set(new) == set(old)
    for name in old:
        assert new[name].area == pytest.approx(old[name].area, rel=1e-4), name
    a, b = (trimesh.util.concatenate(list(s.values())) for s in (new, old))
    pa = np.vstack([a.vertices, trimesh.sample.sample_surface(a, 20000, seed=1)[0]])
    pb = np.vstack([b.vertices, trimesh.sample.sample_surface(b, 20000, seed=2)[0]])
    hausdorff_mm = max(_one_sided_hausdorff(pa, b), _one_sided_hausdorff(pb, a))*1e3
    assert hausdorff_mm < .01


def test_porous_coefficients():
    zs = porous.zones(V23)
    assert [z['zone'] for z in zs] == [f'card{c}path{p}' for c in (0, 1) for p in (0, 1, 2)]
    assert porous.thermal_hvol(zs) == 15394.443601722938
    assert zs[0]['D'] == 1628140.142011858 and zs[0]['F'] == 14.457234060789416
    for a, b in zip(zs[:3], zs[3:]):
        assert {k: v for k, v in a.items() if k not in ('zone', 'side', 'box')} == {k: v for k, v in b.items() if k not in ('zone', 'side', 'box')}


@needs_fixture
def test_porous_matches_fixture():
    ref = json.loads((FIXTURE/'geometry.json').read_text())['zone_coefficients']
    for new, old in zip(porous.zones(V23), ref, strict=True):
        assert {k: new[k] for k in old} == old


def _balanced(text):
    depth = {'{': 0, '(': 0}
    for ch in text:
        if ch in '{(': depth[ch] += 1
        elif ch == '}': depth['{'] -= 1
        elif ch == ')': depth['('] -= 1
        assert min(depth.values()) >= 0
    return all(v == 0 for v in depth.values())


def test_case_dictionaries(built):
    out, meta = built
    files = [p for p in out.rglob('*') if p.is_file() and p.suffix != '.stl' and p.name != 'case.json']
    assert {str(p.relative_to(out)) for p in files} >= {
        'system/blockMeshDict', 'system/snappyHexMeshDict', 'system/controlDict', 'system/fvSchemes', 'system/fvSolution',
        'system/topoSetDict', 'system/decomposeParDict', 'constant/porosityProperties', 'constant/thermalProperties',
        'constant/transportProperties', 'constant/turbulenceProperties', '0/p', '0/U', '0/k', '0/omega', '0/nut', '0/T'}
    for p in files:
        text = p.read_text()
        assert text.startswith('FoamFile {') and _balanced(text), p
        assert '$' not in text and '/Users' not in text and 'Metal' not in text and '.dylib' not in text, p
    for f in ('p', 'U', 'k', 'omega', 'nut', 'T'):
        text = (out/'0'/f).read_text()
        for patch in ('inlet', 'walls', 'cardWalls', 'background'):
            assert re.search(rf'\b{patch} ', text), (f, patch)
        assert '"outlet(Left|Right)"' in text
    s = lambda rel: (out/rel).read_text()  # noqa: E731
    assert '(35 35 90)' in s('system/blockMeshDict') and '-0.012' in s('system/blockMeshDict') and '0.347' in s('system/blockMeshDict')
    assert 'type fanPressure' in s('0/p') and 'direction in' in s('0/p')
    assert 'shoulder0 {mode inside; levels ((1e15 2));}' in s('system/snappyHexMeshDict')
    assert 'application porousSimpleFoam' in s('system/controlDict')
    assert s('constant/porosityProperties').count('type DarcyForchheimer') == 6
    topo = s('system/topoSetDict')
    assert topo.count('setToCellZone') == 6 and 'faceZoneSet' in topo and 'cardExit0' in topo and 'cardExit1' in topo
    assert 'Hvol 15394.443601722938;' in s('constant/thermalProperties')
    assert 'pathHvol (' in s('constant/thermalProperties')
    assert meta['thermal']['pathHvol'] == porous.thermal_path_hvol(meta['zone_coefficients'])
    assert meta['options']['fins']['port_coupling'] == (1.0, 1.0, 1.0)
    assert meta['patches']['inlet']['area_m2'] > 0 and len(meta['zone_coefficients']) == 6
    assert json.loads((out/'case.json').read_text())['fan']['fanPQ'][0] == [0.0, 6.9]


def test_shoulder_refinement_default_off(inner, tmp_path):
    case.build(tmp_path, V23, case.CaseOptions(bracket=None), inner=inner)
    text = (tmp_path/'system/snappyHexMeshDict').read_text()
    assert 'shoulder' not in text and 'refinementRegions {};' in text


def test_pull_direction(inner, tmp_path):
    case.build(tmp_path, V23, case.CaseOptions(direction='pull', bracket=None), inner=inner)
    p, u = (tmp_path/'0/p').read_text(), (tmp_path/'0/U').read_text()
    assert 'direction out' in p and '"outlet(Left|Right)" {type totalPressure;' in p and 'uniform (0 0 -1)' in u


@pytest.mark.skipif(not env.has_openfoam(), reason='OpenFOAM missing')
def test_mesh_coarse(inner, tmp_path):
    case.build(tmp_path, V23, case.CaseOptions(base_cell=8.0, bracket=None), inner=inner)
    stats = mesh.mesh(tmp_path)
    assert stats['cells'] > 10000
    boundary = (tmp_path/'constant/polyMesh/boundary').read_text()
    for card, patch in enumerate(['outletLeft', 'outletRight']):   # the exit faceZones are exactly the outlet faces
        n = int(re.search(rf'{patch}\s*{{[^}}]*?nFaces\s+(\d+);', boundary).group(1))
        assert stats['zones'][f'cardExit{card}'] == n
    zones = (tmp_path/'constant/polyMesh/faceZones').read_text()
    assert 'cardExit0' in zones and 'cardExit1' in zones
    assert 'card1path2' in (tmp_path/'constant/polyMesh/cellZones').read_text()


# --- push-pull: collector, exhaust fan, bracket windows ---------------------------------------------

from duct.cad import hardware  # noqa: E402
from duct.cfd import collector, run  # noqa: E402


@pytest.fixture(scope='module')
def pushpull(inner, tmp_path_factory):
    out = tmp_path_factory.mktemp('pushpull')
    o = case.CaseOptions(collector=collector.placeholder(V23), pull_rpm=2500)
    return out, case.build(out, V23, o, inner=inner), o


def test_placeholder_collector_covers_ports():
    c = collector.placeholder(V23)
    assert c.genus() == 0 and c.volume() > 0
    exit_z = V23.chamber_length+domain.DOMAIN.card_envelope
    assert c.bounding_box()[2] == pytest.approx(exit_z)
    x0, y0, x1, y1 = c.slice(exit_z+5).bounds()    # plenum mouth
    assert (x0, x1) == pytest.approx((-53, 53), abs=1e-3) and y1-y0 == pytest.approx(104, abs=1e-3)
    for _, _, (px0, px1, py0, py1) in V23.port_boxes:
        assert x0 < px0 and px1 < x1 and y0 < py0 and py1 < y1
    face = collector.fan_face(c)
    assert face.z == pytest.approx(exit_z+40) and face.radius == pytest.approx(58, abs=1e-3)


def test_classify_merges_repeated_rule_names(surface):
    m, base = surface
    rule = ('walls', lambda t: np.abs(t[:, :, 2]-domain.DOMAIN.approach_depth*-1e-3).max(1) < domain.TOL)
    groups = domain.classify(m, V23, rules=[rule])
    assert len(groups['inlet']) == 0 and list(groups) == list(domain.PATCHES)
    assert np.array_equal(groups['walls'], np.union1d(base['walls'], base['inlet']))


def test_pushpull_patches(pushpull):
    out, meta, o = pushpull
    assert list(meta['patches']) == ['walls', 'cardWalls', 'inlet', 'exhaust', 'caseAir']
    n, d = 128, domain.DOMAIN
    annulus = .5*n*math.sin(2*math.pi/n)*(58.0**2-d.hub_radius**2)*1e-6   # capped by the 58 mm face
    assert meta['exhaust']['area_m2'] == pytest.approx(annulus, rel=1e-6)
    stl = _stl_patches(out/'constant/triSurface/flow.stl')
    exit_z = (V23.chamber_length+d.card_envelope)*1e-3
    # the collector's flange on the rear panel's outer face (duct.cad.hardware.placed), past the bracket plane
    zp = exit_z+o.bracket.panel_thickness*1e-3
    assert stl['cardWalls'].vertices[:, 2].max() <= zp+domain.TOL   # collector walls are not slip (window sides are)
    assert o.bracket.panel_thickness == hardware.CASE.panel and meta['collector']['inlet_z_mm']*1e-3 == pytest.approx(zp)
    assert stl['exhaust'].vertices[:, 2] == pytest.approx(zp+.045)
    assert stl['walls'].vertices[:, 2].max() == pytest.approx(zp+.045)
    # the author's case has no slot covers: of the open slots (-3, 0, 3) only the middle one lies under the placeholder's
    # mouth (x ±53); its opening joins a box of case air upstream whose sides and far face are caseAir, clear of the ports
    case_ = hardware.CASE
    assert case_.open_slots == (-3, 0, 3) and meta['open_slots']['patch'] == 'caseAir' and meta['open_slots']['covers'] == []
    [ms] = meta['open_slots']['slots']
    assert ms['slot'] == 0 and meta['open_slots']['open_area_m2'] == ms['open_area_m2']
    x0, x1, y0, y1 = ms['opening_mm']
    assert x1-x0 == pytest.approx(case_.opening_width) and y1-y0 == pytest.approx(case_.opening_height)
    assert ms['open_area_m2'] == pytest.approx(case_.opening_width*(y1-max(y0, -52))*1e-6)   # the mouth ends at y -52
    air = stl['caseAir'].vertices*1e3
    bx0, bx1, by0, by1, bz0, bz1 = ms['case_air_box_mm']
    assert air[:, 0].min() == pytest.approx(bx0) and air[:, 0].max() == pytest.approx(bx1) and bz1 == exit_z*1e3
    assert air[:, 2].min() == pytest.approx(bz0) and air[:, 2].max() == pytest.approx(bz1)
    for f in ('p', 'U', 'k', 'omega', 'nut', 'T'):
        assert re.search(r'^ caseAir \{type ', (out/'0'/f).read_text(), re.M), f
    assert 'caseAir {type totalPressure; p0 uniform 0;' in (out/'0/p').read_text() and 'caseAirFlow' in run.functions(out)


def test_pushpull_dictionaries(pushpull):
    out, meta, o = pushpull
    s = lambda rel: (out/rel).read_text()  # noqa: E731
    p = s('0/p')
    assert re.search(r'\binlet \{type fanPressure;.*direction in; p0 uniform 0; value uniform [\d.]+;', p)
    assert re.search(r'\bexhaust \{type fanPressure;.*direction out; p0 uniform 0; value uniform -[\d.]+;', p)
    for f in ('p', 'U', 'k', 'omega', 'nut', 'T'):
        assert re.search(r'^ exhaust \{', s(f'0/{f}'), re.M) and 'outlet(Left|Right)' not in s(f'0/{f}'), f
    assert '(0 0 1)' in s('0/U')
    # background z faces at exit_z - delta - k·base; the bracket plate between two of them
    pl = case.planes(V23, o)
    z0 = float(re.search(r'vertices \(\([^)]* ([-\d.e]+)\)', s('system/blockMeshDict')).group(1))*1e3
    assert (pl.exit_z-pl.delta-z0) % o.base_cell == pytest.approx(0, abs=1e-6)
    assert pl.slab_cells == 0 and meta['planes_mm']['grille'] is None and not meta.get('grille_zones')
    assert meta['bracket']['room'] is None and 'bracket {mode inside; levels ((1e15 2));}' in s('system/snappyHexMeshDict')
    topo = s('system/topoSetDict')
    for plane in ('cardEntry', 'cardBracket', 'cardExit'):
        for card in (0, 1):
            assert f'name {plane}{card}; type faceZoneSet; action new; source setsToFaceZone' in topo
    assert 'name bracketDown; type faceZoneSet' in topo
    fos = run.functions(out)
    assert 'regionType faceZone; name cardExit0' in fos and 'name exhaust' in fos and 'outletLeft' not in fos


def test_planes_clear_porous_ends():
    # bracket plate faces on the refined lattice, porous ends on level 1: a quarter lattice clear of faces and centres
    for base in (2.0, 4.0):
        for o in (case.CaseOptions(base_cell=base), case.CaseOptions(base_cell=base, bracket=None, grille_open_area=.65)):
            p = case.planes(V23, o)
            fine = base/2**(o.bracket.refine+1) if o.bracket else base/4
            items = [(V23.chamber_length+8, base/4), (V23.chamber_length+238, base/4), (p.exit_z, fine)]
            items += [(p.exit_z-o.bracket.thickness, fine), (p.exit_z+o.bracket.panel_thickness, fine)] if o.bracket else []
            for z, lat in items:
                r = (p.exit_z-p.delta-z) % lat
                assert min(r, lat-r) >= lat/4-1e-9
    with pytest.raises(ValueError):
        case.planes(V23, case.CaseOptions(base_cell=8.0))


def test_pull_only_and_single_fan_grille(inner, tmp_path):
    case.build(tmp_path/'pull', V23, case.CaseOptions(rpm=0, collector=collector.placeholder(V23), pull_rpm=2500), inner=inner)
    p = (tmp_path/'pull/0/p').read_text()
    assert 'inlet {type totalPressure; p0 uniform 0; value uniform 0;}' in p and 'direction out' in p
    # the optional perforated-plate slab, without the bracket plate: one base cell... three at base 4, F = K/t
    o = case.CaseOptions(grille_open_area=.65, bracket=None)
    meta = case.build(tmp_path/'grille', V23, o, inner=inner)
    assert set(meta['patches']) == set(domain.PATCHES) and len(meta['grille_zones']) == 2
    assert '"outlet(Left|Right)" {type fixedValue; value uniform 0;}' in (tmp_path/'grille/0/p').read_text()
    assert run.functions(tmp_path/'grille') == run.FUNCTIONS
    pl = case.planes(V23, o)
    assert pl.slab_cells == 3 and meta['planes_mm']['grille'] == [pl.at(5), pl.at(2)]
    K = porous.perforated_plate_k(.65)
    assert [g['zone'] for g in meta['grille_zones']] == ['grille0', 'grille1']
    assert meta['grille_zones'][0]['F'] == pytest.approx(K/.012)
    pp = (tmp_path/'grille/constant/porosityProperties').read_text()
    assert pp.count('type DarcyForchheimer') == 8 and f"f (0 0 {meta['grille_zones'][0]['F']!r})" in pp
    with pytest.raises(AssertionError):
        case.CaseOptions(pull_rpm=2500)            # an exhaust fan needs a collector


def test_actuator_disk_case(inner, tmp_path):
    from duct.cfd import disk, fan
    o = case.CaseOptions(fan_model='disk', swirl=1.0, collector=collector.placeholder(V23), pull_rpm=2500)
    meta = case.build(tmp_path, V23, o, inner=inner)
    assert list(meta['patches']) == ['walls', 'cardWalls', 'inlet', 'exhaust', 'caseAir']
    s = lambda rel: (tmp_path/rel).read_text()  # noqa: E731
    assert 'inlet {type totalPressure; p0 uniform 0;' in s('0/p') and 'exhaust {type totalPressure; p0 uniform 0;' in s('0/p')
    assert 'inlet {type inletOutlet;' in s('0/k') and 'inlet {level (0 0);' in s('system/snappyHexMeshDict')
    baffles = s('system/createBafflesDict')
    assert baffles.count('type fan; patchType cyclic; mode volumeFlowRate') == 2
    assert baffles.count('type swirlFanVelocity') == 2 and 'rpm -2500;' in baffles and 'fanEff 1;' in baffles
    assert 'preservePatches; patches (intakeFan_master intakeFan_slave exhaustFan_master exhaustFan_slave)' in s('system/decomposeParDict')
    topo = s('system/topoSetDict')
    assert 'name intakeFan; type faceZoneSet' in topo and 'name exhaustFan; type faceZoneSet' in topo
    intake, exhaust = meta['fans']
    assert intake['role'] == 'intake' and -5 < intake['z_mm'] < 0 and intake['hub_radius_mm'] == fan.HUB_RADIUS*1e3
    face = collector.fan_face(o.collector)
    assert face.z < exhaust['z_mm'] < face.z+5 and exhaust['patches'] == list(disk.patches(disk.EXHAUST))
    assert meta['collector']['present'] and [r['role'] for r in meta['rooms']] == ['intake', 'exhaust']


# sha256 of a push-pull case's exhaust-fan files before the per-fan exhaust model (CaseOptions.exhaust_fan): a 120 mm
# collector's case (no exhaust_fan: the P12 Pro on the domain's annulus) must stay byte-identical. (Not the flow STL: its
# triangulation depends on how far the module's shared `inner` was evaluated before.)
P12_PUSH_PULL_SHA256 = {
    'boundary': {'0/p': '9e2e49a285073206a11fea96f0f1397becfdc3424f82daf87359bdd3cd6a56f0',
                 'system/topoSetDict': 'ee9fa77714c910e67248bd0c095c7f77d112187c2e3503badcac8cdbe961f414',
                 'meta': '3f73831bb2389a04b0b636df1f4dd996bbfc8e5bc05f9ecf62df527e8520e730'},
    'disk': {'0/p': '508751d4b12068bdebdfac59ac96dc2772f6d53292f87086aff2c1a967eb873c',
             'system/createBafflesDict': '44b8acf7f122f7fbab8b28d3b70a76eae4e1db444fc1aee92c029a67c6803685',
             'system/topoSetDict': '7c90e0f81789bdd66bcb10cc1760f9c49a6e5aab427a5f64bdad2d283650b23a',
             'meta': 'e57f04c1333f78d07613dc09b2a7bc633520bbdfc2946be521a19c2f1e63e01b'},
}


@pytest.mark.parametrize('model', ['boundary', 'disk'])
def test_p12_exhaust_case_unchanged(inner, tmp_path, model):
    import hashlib
    kw = dict(fan_model='disk', swirl=1.0) if model == 'disk' else {}
    meta = case.build(tmp_path, V23, case.CaseOptions(collector=collector.placeholder(V23), pull_rpm=2500, **kw), inner=inner)
    h = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731
    got = {rel: h((tmp_path/rel).read_bytes()) for rel in P12_PUSH_PULL_SHA256[model] if rel != 'meta'}
    got['meta'] = h(json.dumps([meta['exhaust'], meta['fans']], sort_keys=True).encode())
    assert got == P12_PUSH_PULL_SHA256[model]


def test_p14_exhaust_disk(inner, tmp_path):
    """A 140 mm exhaust fan (CaseOptions.exhaust_fan): its chart on the exhaust baffle, its annulus for the approach, the
    baffle's faceZone, the fan entry and case.json; the intake keeps the P12 Pro."""
    from duct.cfd import fan
    pf = fan.P14_PRO_REVERSE
    placeholder = collector.placeholder(V23, face_radius=70.0)
    o = case.CaseOptions(fan_model='disk', collector=placeholder, pull_rpm=2500, exhaust_fan=pf)
    meta = case.build(tmp_path, V23, o, inner=inner)
    baffles = (tmp_path/'system/createBafflesDict').read_text()
    intake, exhaust = baffles.split('\nexhaustFan ')
    assert fan.fan_jump_bc(2500) in intake and fan.fan_jump_bc(2500, model=pf) in exhaust
    assert fan.fan_jump_bc(2500, model=pf) != fan.fan_jump_bc(2500)
    ex = meta['fans'][1]
    assert (ex['hub_radius_mm'], ex['tip_radius_mm']) == (28.0, 68.0) and meta['fans'][0]['tip_radius_mm'] == 58.5
    assert meta['exhaust']['model'] == pf.name and meta['exhaust']['chart_rpm'] == 2650.0
    face = collector.fan_face(o.placed_collector)
    r = 69e-3   # the faceZone box spans the 68 mm tip
    assert f"box ({face.centre[0]*1e-3-r:.9g} {face.centre[1]*1e-3-r:.9g}" in (tmp_path/'system/topoSetDict').read_text()
    # the approach annulus: hub 28, tip 68 (inside the 70 mm face)
    tri = domain.to_metres(collector.exhaust_approach(face, o.domain, o.exhaust_annulus))
    r_xy = np.hypot(tri.vertices[:, 0]-face.centre[0]*1e-3, tri.vertices[:, 1]-face.centre[1]*1e-3)
    assert r_xy.min() == pytest.approx(.028, abs=2e-4) and r_xy.max() == pytest.approx(.068, abs=2e-4)


def test_bracket_windows(inner, tmp_path):
    from duct.cfd import bracket
    meta = case.build(tmp_path, V23, case.CaseOptions(), inner=inner)
    assert list(meta['patches']) == ['walls', 'cardWalls', 'inlet', 'exhaust']
    b, exit_z = meta['bracket'], V23.chamber_length+domain.DOMAIN.card_envelope
    assert b['z_mm'] == exit_z and b['window_area_m2'] == pytest.approx(81*25e-6)
    for (x0, x1, y0, y1), card in zip(b['windows_mm'], (0, 1)):
        xs = [x for c, _, (a, e, _, _) in V23.port_boxes if c == card for x in (a, e)]
        assert (x0+x1)/2 == pytest.approx((min(xs)+max(xs))/2) and x1-x0 == pytest.approx(25)
        assert y1 == pytest.approx(bracket.BRACKET_TOP_Y-8) and y1-y0 == pytest.approx(81)
    assert 'exhaust {type totalPressure; p0 uniform 0;' in (tmp_path/'0/p').read_text()
    assert 'exhaust {level (0 0);' in (tmp_path/'system/snappyHexMeshDict').read_text()
    # the rear panel past the plate: open where each window meets the two chassis slot openings (the rib between them,
    # 20.32 - 13.25 = 7.07 mm, is steel): 25 - 7.07 = 17.93 mm of the window's width, 1452.33 of 2025 mm²
    pan, zp = b['panel'], exit_z+hardware.CASE.panel
    assert pan['thickness_mm'] == hardware.CASE.panel and pan['z_mm'] == [exit_z, zp]
    assert [len(c) for c in pan['openings_mm']] == [2, 2]
    assert pan['open_area_m2'] == pytest.approx([17.93*81e-6]*2) and pan['blocked_fraction'] == pytest.approx([7.07/25]*2)
    stl = _stl_patches(tmp_path/'constant/triSurface/flow.stl')
    assert stl['exhaust'].vertices[:, 2].min() == pytest.approx(zp*1e-3)    # the room's sides and far face, past the panel
    assert stl['exhaust'].vertices[:, 2].max() == pytest.approx((zp+b['room_depth'])*1e-3)
    # the plate and panel: open only through the strips (the room floor is wall on the panel face, the ribs behind each
    # window wall on the bracket plane); the strip sides are wall too
    w = stl['walls'].triangles; z = w[:, :, 2]
    band = (z.min(1) > exit_z*1e-3-domain.TOL) & (z.max(1) < zp*1e-3+domain.TOL)
    on = lambda plane: band & (np.abs(z-plane*1e-3).max(1) < domain.TOL)  # noqa: E731
    area = lambda m: stl['walls'].area_faces[m].sum()*1e6  # noqa: E731
    assert area(on(exit_z)) == pytest.approx(2*7.07*81, rel=1e-6)
    assert len(w[on(zp)]) and 'name bracketDown; type faceZoneSet' in (tmp_path/'system/topoSetDict').read_text()
    # no panel: the whole window opens onto the room at the bracket plane (the runs before the panel)
    nopanel = case.build(tmp_path/'nopanel', V23, case.CaseOptions(bracket=replace(bracket.BRACKET, panel=None)), inner=inner)
    assert nopanel['bracket']['panel'] is None
    assert _stl_patches(tmp_path/'nopanel/constant/triSurface/flow.stl')['exhaust'].vertices[:, 2].min() == pytest.approx(exit_z*1e-3)


def test_no_bracket_station_past_a_flat_fan():
    # a fan gasketed straight onto the panel (2 mm air past the bracket plane): no grid plane fits before its face
    from duct.cad.geometry import cube
    exit_z = V23.chamber_length+domain.DOMAIN.card_envelope
    flat = cube([120, 120, 1.2], [-60, -60, exit_z])
    assert case.planes(V23, case.CaseOptions(collector=flat, pull_rpm=2500)).stations == {}
    assert 'bracketDown' in case.planes(V23, case.CaseOptions(collector=collector.placeholder(V23), pull_rpm=2500)).stations


def test_collector_kinds_follow_the_duct():
    # presets are laid out for the duct (CollectorParams.for_duct): the 4-slot bare fan sits over the open slots ±2.5
    from duct import params
    from duct.params import A29
    air, _ = collector.default(A29, kind='bare')
    z = A29.chamber_length+domain.DOMAIN.card_envelope
    assert air.bounding_box()[2] == pytest.approx(z)
    _, rules, slots = collector.open_slots(A29, air.translate([0, 0, hardware.CASE.panel]), hardware.CASE)
    assert [s['slot'] for s in slots] == [-2.5, 2.5] and rules[0][0] == 'caseAir'
    for kind, name in (('v4a', 'COLLECTOR_V4A'), ('v4b', 'COLLECTOR_V4B')):
        if not hasattr(params, name):
            with pytest.raises(ValueError, match=name):
                collector.default(A29, kind=kind)


def test_covered_slots(inner, tmp_path):
    # covers in every empty slot (the v1 / v2 assumption): the collector draws through the card windows only
    from duct.cfd import bracket
    b = replace(bracket.BRACKET, panel=hardware.CASE_COVERED)
    meta = case.build(tmp_path, V23, case.CaseOptions(collector=collector.placeholder(V23), pull_rpm=2500, bracket=b), inner=inner)
    assert list(meta['patches']) == ['walls', 'cardWalls', 'inlet', 'exhaust']
    assert meta['open_slots'] == dict(patch=None, covers=[-3, 0, 3], slots=[], open_area_m2=0)
    assert 'caseAir' not in (tmp_path/'0/p').read_text() and 'caseAirFlow' not in run.functions(tmp_path)


def test_bracket_loss_estimate():
    from duct.cfd import bracket
    assert bracket.contraction_coefficient(0) == pytest.approx(.609, abs=1e-3)     # thin sharp orifice, small f
    assert bracket.exit_loss_heads(1.0) == pytest.approx(1/(.57+.043/.1)**2)
    assert bracket.plenum_loss_heads(.5, 0) == pytest.approx(bracket.exit_loss_heads(.5))
