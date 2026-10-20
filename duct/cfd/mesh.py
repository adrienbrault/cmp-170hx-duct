"""Mesh a case written by duct.cfd.case: blockMesh, snappyHexMesh, checkMesh, topoSet, and createBaffles for
actuator-disk cases. Logs land in the case."""
import re
from pathlib import Path

from .. import env

STEPS = ("blockMesh", "snappyHexMesh -overwrite", "checkMesh", "topoSet")


def mesh(case: Path) -> dict:
    """Run the meshing chain in `case`; raises unless checkMesh reports `Mesh OK.`. Returns mesh stats."""
    case = Path(case)
    steps = STEPS+(("createBaffles -overwrite",) if (case/"system/createBafflesDict").exists() else ())
    for cmd in steps:
        log = case/f"log.{cmd.split()[0]}"
        try:
            env.foam(cmd, cwd=case, log=log)
        except Exception as e:
            raise RuntimeError(f"{cmd} failed; see {log}") from e
    return check(case)


def check(case: Path) -> dict:
    """Mesh stats from log.checkMesh (which must say `Mesh OK.`) and zone sizes from log.topoSet."""
    text = (Path(case)/"log.checkMesh").read_text()
    if "Mesh OK." not in text:
        raise RuntimeError(f"checkMesh failed; see {Path(case)/'log.checkMesh'}")
    num = lambda key: int(re.search(rf"^\s*{key}:\s+(\d+)", text, re.M).group(1))  # noqa: E731
    stats = dict(cells=num("cells"), faces=num("faces"), points=num("points"))
    m = re.search(r"non-orthogonality Max: ([\d.]+)", text)
    stats["max_non_orthogonality"] = float(m.group(1)) if m else None
    topo = Path(case)/"log.topoSet"
    stats["zones"] = {n: int(k) for n, k in re.findall(r"ZoneSet (\w+) now size (\d+)", topo.read_text())} if topo.exists() else {}
    return stats
