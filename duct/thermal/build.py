"""Build the canonical chtFinBase solver against the installed OpenFOAM."""
import shutil
from pathlib import Path

from .. import env

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "solvers/chtFinBase"
BUILD = ROOT / "runs/.build/chtFinBase"  # wmake writes objects next to Make/; keep them out of the tree
BIN = ROOT / "runs/.bin"
EXE = BIN / "chtFinBase"


def _sources() -> list[Path]:
    return [p for p in SOURCE.rglob("*") if p.is_file()]


def build(force: bool = False) -> Path:
    """Compile solvers/chtFinBase into runs/.bin when missing or older than its sources."""
    if not force and EXE.exists() and all(p.stat().st_mtime <= EXE.stat().st_mtime for p in _sources()):
        return EXE
    shutil.rmtree(BUILD, ignore_errors=True)
    shutil.copytree(SOURCE, BUILD)
    BIN.mkdir(parents=True, exist_ok=True)
    env.foam(f"export FOAM_USER_APPBIN='{BIN}' && wmake", cwd=BUILD, log=BUILD / "log.wmake")
    if not EXE.exists():
        raise RuntimeError(f"wmake did not produce {EXE}; see {BUILD / 'log.wmake'}")
    return EXE
