"""External tool discovery. The only module that knows where tools live on disk."""
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

OPENFOAM_APPS = [
    Path.home() / "Applications/OpenFOAM-v2606.app",
    Path("/Applications/OpenFOAM-v2606.app"),
]
BAMBU = Path("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def openfoam_launcher() -> Path | None:
    """The app's `openfoam` launcher, which runs a command inside the OpenFOAM environment."""
    if env := os.environ.get("DUCT_OPENFOAM_APP"):
        candidates = [Path(env)]
    else:
        candidates = OPENFOAM_APPS
    for app in candidates:
        launcher = app / "Contents/Resources/etc/openfoam"
        if launcher.exists():
            return launcher
    return None


def foam(command: str, cwd: Path | None = None, log: Path | None = None,
         check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command inside the OpenFOAM environment."""
    launcher = openfoam_launcher()
    if launcher is None:
        raise RuntimeError("OpenFOAM v2606 not found; run `duct doctor`")
    out = open(log, "w") if log else subprocess.PIPE
    try:
        return subprocess.run([str(launcher), "-c", command], cwd=cwd, stdout=out,
                              stderr=subprocess.STDOUT, text=True, check=check)
    finally:
        if log:
            out.close()


def perf_cores() -> int:
    """Performance-core count (Apple silicon); MPI runs stop scaling past it."""
    try:
        return int(subprocess.run(["sysctl", "-n", "hw.perflevel0.physicalcpu"], capture_output=True,
                                  text=True, check=True).stdout)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return max(1, (os.cpu_count() or 2) // 2)


def has_openfoam() -> bool:
    return openfoam_launcher() is not None


def doctor() -> list[Check]:
    checks = []
    launcher = openfoam_launcher()
    if launcher is None:
        checks.append(Check("openfoam", False, "install: brew install --cask gerlero/openfoam/openfoam@2606"))
    else:
        try:
            r = foam("porousSimpleFoam -help >/dev/null && mpirun --version | head -1 && echo $WM_PROJECT_VERSION")
            checks.append(Check("openfoam", True, f"{launcher.parents[3].name}: {' / '.join(r.stdout.split(chr(10))[:2])}"))
        except subprocess.CalledProcessError as e:
            checks.append(Check("openfoam", False, f"{launcher} failed: {e.stdout[-300:] if e.stdout else e}"))
    checks.append(Check("bambu-studio", BAMBU.exists(), str(BAMBU)))
    ffmpeg = shutil.which("ffmpeg")
    checks.append(Check("ffmpeg", ffmpeg is not None, ffmpeg or "brew install ffmpeg"))
    try:
        import pyvista  # noqa: F401
        checks.append(Check("pyvista", True, pyvista.__version__))
    except ImportError:
        checks.append(Check("pyvista", False, "uv sync --extra viz"))
    return checks
