"""Per-port thermal closure and conservative fin/base exchange."""
from dataclasses import replace

import numpy as np
import pytest

from duct.cfd import case, porous
from duct.params import V29


def test_port_conductance_uses_own_fin_area():
    f = replace(porous.FINS, heat_scale=1.3, port_coupling=(1.0, .25, .75))
    zs = porous.zones(V29, f)
    props = case.thermal_properties(V29, zs, f)
    for z in zs[:3]:
        path = z['path']
        volume = np.prod(np.subtract(z['box'][1], z['box'][0]))
        x0, x1, y0, y1 = V29.fin_ports[path]
        width, height = (y1-y0)*.001, (x1-x0)*.001
        n = f.channels[path]
        effective_area = (2*n*height*z['fin_eta']+n*z['gap'])*f.length
        assert props['pathHvol'][path]*volume == pytest.approx(
            z['h']*effective_area*f.heat_scale*f.port_coupling[path])
    assert props['pathHvol'][1] != props['pathHvol'][0]*.25


def test_zero_side_coupling_restores_legacy():
    f = replace(porous.FINS, port_coupling=(1.0, 0.0, 0.0))
    zs = porous.zones(V29, f)
    props = case.thermal_properties(V29, zs, f)
    assert props['pathHvol'] == [porous.thermal_hvol(zs, f), 0.0, 0.0]
    assert zs == porous.zones(V29)  # heat coupling must not alter hydraulic coefficients


@pytest.mark.parametrize('coupling', [(1, -.1, 1), (1, 1.1, 1), (1, float('nan'), 1), (1, 1)])
def test_invalid_port_coupling(coupling):
    with pytest.raises(ValueError, match='port_coupling'):
        replace(porous.FINS, port_coupling=coupling)


def _channels(out, coupling):
    """Six disjoint straight passages: exact uniform flow, real port cross-sections."""
    from duct.cfd.case import header, vec

    f = replace(porous.FINS, start=0, port_coupling=coupling)
    g = replace(V29, chamber_length=70)
    zs = porous.zones(g, f)
    vertices, blocks, inlets, outlets, walls = [], [], [], [[], []], []
    for z in zs:
        x0, y0, z0 = z['box'][0]
        x1, y1, z1 = z['box'][1]
        offset = len(vertices)
        vertices += [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                     (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        def face(indices):
            return '('+' '.join(str(offset+i) for i in indices)+')'
        blocks.append(f'hex {face(range(8))} (1 4 32) simpleGrading (1 1 1)')
        inlets.append(face([0, 3, 2, 1]))
        outlets[z['side']].append(face([4, 5, 6, 7]))
        walls += [face(v) for v in ([0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7])]
    for d in ('0', 'system', 'constant'):
        (out/d).mkdir(parents=True)
    def dictionary(name, content, directory='system'):
        (out/directory/name).write_text(header(name)+content)
    boundary = ' '.join(f'{name} {{type patch; faces ({" ".join(faces)});}}' for name, faces in
                        [('inlet', inlets), ('outletLeft', outlets[0]), ('outletRight', outlets[1]), ('walls', walls)])
    dictionary('blockMeshDict', 'scale 1; vertices ('+' '.join(vec(v) for v in vertices)+'); blocks ('+
               ' '.join(blocks)+'); edges (); boundary ('+boundary+'); mergePatchPairs ();')
    (out/'system/topoSetDict').write_text(case.topo_set(g, zs, case.DOMAIN))
    dictionary('controlDict', 'application potentialFoam; startFrom startTime; startTime 0; stopAt endTime; '
               'endTime 1; deltaT 1; writeControl timeStep; writeInterval 1; writePrecision 15;')
    dictionary('fvSchemes', 'ddtSchemes {default steadyState;} gradSchemes {default Gauss linear;} '
               'divSchemes {default none;} laplacianSchemes {default Gauss linear uncorrected;} '
               'interpolationSchemes {default linear;} snGradSchemes {default uncorrected;} fluxRequired {default no; Phi;}')
    dictionary('fvSolution', 'solvers {Phi {solver PCG; preconditioner DIC; tolerance 1e-12; relTol 0;}} '
               'potentialFlow {nNonOrthogonalCorrectors 0;}')
    props = case.thermal_properties(g, zs, f) | dict(ny=8, nz=16)
    dictionary('thermalProperties', ''.join(f'{k} {vec(v) if isinstance(v, list) else v};\n' for k, v in props.items()), 'constant')
    for name, cls, dims, value, inlet, outlet in [
        ('U', 'volVectorField', '0 1 -1 0 0 0 0', '(0 0 2)', 'fixedValue; value uniform (0 0 2)', 'zeroGradient'),
        ('p', 'volScalarField', '0 2 -2 0 0 0 0', '0', 'zeroGradient', 'fixedValue; value uniform 0'),
        ('T', 'volScalarField', '0 0 0 1 0 0 0', '298.15', 'fixedValue; value uniform 298.15', 'zeroGradient'),
    ]:
        (out/'0'/name).write_text(
            f'FoamFile {{version 2.0; format ascii; class {cls}; object {name};}}\n'
            f'dimensions [{dims}]; internalField uniform {value}; boundaryField {{'
            f'inlet {{type {inlet};}} "outlet(Left|Right)" {{type {outlet};}} walls {{type zeroGradient;}}}}')
    return zs, f


@pytest.mark.parametrize('coupling', [(1, 0, 0), (1, .35, 1), 'legacy'])
def test_solver_path_energy_balance(tmp_path, coupling):
    """Exercise the C++ solve; independently check its exported base equation."""
    import json
    from duct import env
    from duct.thermal.run import run
    from duct.cfd.foamdict import REMOVE

    legacy = coupling == 'legacy'
    if legacy:
        coupling = (1, 0, 0)
    if not env.has_openfoam():
        pytest.skip('OpenFOAM v2606 is not installed')
    zs, f = _channels(tmp_path, coupling)
    env.foam('blockMesh', cwd=tmp_path, log=tmp_path/'log.mesh')
    env.foam('topoSet', cwd=tmp_path, log=tmp_path/'log.zones')
    env.foam('potentialFoam -writephi -initialiseUBCs', cwd=tmp_path, log=tmp_path/'log.potential')
    result = run(tmp_path, couplings={'pathHvol': REMOVE} if legacy else None)
    assert result.objective_converged
    assert result.exchange_energy_error < 1e-5
    assert result.energy_error < 1e-4
    for card in result.raw['cards']:
        paths = card['paths']
        assert len(paths) == 3
        assert sum(p['heat_W'] for p in paths) == pytest.approx(250, abs=.0025)
        assert sum(card['flow_by_y_m3s']) == pytest.approx(card['main_Q_m3s'])
        for p, z in zip(paths, zs[:3], strict=True):
            volume = np.prod(np.subtract(z['box'][1], z['box'][0]))
            # foamDictionary rewrites scalar lists at its default six-digit precision.
            assert p['Hvol_W_m3K'] == pytest.approx(z['Hvol']*f.port_coupling[p['path']], rel=1e-5)
            assert p['conductance_W_K'] == pytest.approx(p['Hvol_W_m3K']*volume)
            assert (p['heat_W'] > 0) == (coupling[p['path']] > 0)
    coeff = json.loads((tmp_path/'base-coupling.json').read_text())
    assert coeff['partition_error'] < 1e-14
    assert coeff['linear_projection_error_m'] < 1e-14
    ny, nz = coeff['ny'], coeff['nz']
    base = np.array(coeff['base']).reshape(2, nz, ny)
    exchange = np.array(coeff['exchange_coeffs']).reshape(2, nz, ny, 3, 3)
    np.testing.assert_allclose(exchange.sum(axis=(-1, -2)).ravel(), coeff['Hsum'], atol=1e-12)
    residual = -np.array(coeff['q']).reshape(base.shape)-np.array(coeff['HT']).reshape(base.shape)
    for c in range(2):
        for z in range(nz):
            for y in range(ny):
                for dz in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if 0 <= z+dz < nz and 0 <= y+dy < ny:
                            residual[c,z,y] += exchange[c,z,y,dz+1,dy+1]*base[c,z+dz,y+dy]
                for dz, dy, conductance in [(0,-1,coeff['Gy']), (0,1,coeff['Gy']),
                                             (-1,0,coeff['Gz']), (1,0,coeff['Gz'])]:
                    if 0 <= z+dz < nz and 0 <= y+dy < ny:
                        residual[c,z,y] += conductance*(base[c,z,y]-base[c,z+dz,y+dy])
    assert np.max(np.abs(residual)) < 1e-5


@pytest.mark.parametrize('value', [None, '0', '0.4'])
def test_cli_side_coupling(monkeypatch, value):
    from duct import cli

    def options(args):
        return cli._case_options(args, V29)
    monkeypatch.setattr(cli, 'cmd_simulate', options)
    args = ['simulate', 'test', '--preset', 'v29', '--np', '3']
    if value is not None:
        args += ['--side-port-coupling', value]
    o = cli.main(args)
    expected = 1.0 if value is None else float(value)
    assert o.fins.port_coupling == (1.0, expected, expected)
