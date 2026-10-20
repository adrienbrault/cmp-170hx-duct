# Validation fixtures

`validation.tgz` is not tracked in git. It holds:

- `reference55/`: the only CFD run that passed the original strict gates (V8-derived 55 mm duct, 2500 rpm, 250 W/card). It includes the mesh, the `0` and `1200` fields, the thermal results and `study-result.json`. Stage 4 restarts it warm and Stage 5 reruns it cold to validate the new solver profiles.
- `upper-r6/`: the V23 fluid surface (`constant/triSurface/flow.stl`) and its `geometry.json` from the old builder, used to check that the new fluid-domain builder reproduces it.

The expected checksum is in `validation.sha256`. Extract it here with `tar -xzf validation.tgz`. Tests that need these files are skipped when they're missing.

`v23/` (tracked): the original V23 generator's fillet profiles and checks, which `tests/test_cad.py` compares the rebuilt V23 against.
