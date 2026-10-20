"""Core tokens shared by concurrent `duct simulate` runs on one machine, so a sweep never oversubscribes the CPU.

A pool is a directory of `total` token files; holding a token is holding an exclusive `flock` on its file. The kernel
drops the locks when a process exits however it dies, so there is no stale state to clean up. A run takes one
token for its serial phases (CAD, snappyHexMesh, thermal, post-processing) and one per MPI rank for the flow solve,
trading them at the phase boundary; a request waits until it can take all its tokens at once (polling, never holding
part of a request while it waits, so two runs cannot deadlock).

Pool size: DUCT_CORES (default `DEFAULT_CORES`), directory: DUCT_POOL (default runs/.cores). DUCT_CORES=0 disables
the pool (every request is granted at once).
"""
import fcntl
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# 6 performance + 12 efficiency cores. V28 push-pull v3 fine mesh, 200 iterations from cold, s/iteration: 3 ranks
# 0.60, 4 0.49, 6 0.39, 8 0.46 (measured at load averages 45-290 from other jobs, so provisional): ranks past the
# performance cores buy nothing. Two 6-rank solves plus two serial phases (snappy, thermal: one core each).
DEFAULT_CORES = 14
DEFAULT_RANKS = 6
POLL_S = 1.0


def pool_size() -> int:
    v = os.environ.get("DUCT_CORES")
    return DEFAULT_CORES if v is None or v == "" else int(v)


def pool_dir() -> Path:
    return Path(os.environ.get("DUCT_POOL") or Path("runs") / ".cores")


class Pool:
    def __init__(self, directory: Path | None = None, total: int | None = None):
        self.dir = Path(directory) if directory is not None else pool_dir()
        self.total = pool_size() if total is None else total
        self.held: list = []           # open, locked token files

    def _try(self, n: int) -> list | None:
        """Lock `n` free tokens without blocking, or none of them."""
        got = []
        for i in range(self.total):
            if len(got) == n:
                break
            f = open(self.dir / f"core-{i:03d}.lock", "a+")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                f.close()
                continue
            got.append(f)
        if len(got) == n:
            return got
        for f in got:
            f.close()       # closing drops the lock
        return None

    def acquire(self, n: int, timeout: float | None = None, label: str = "") -> float:
        """Take `n` tokens (clamped to the pool size) on top of those already held; returns the seconds waited."""
        if self.total <= 0:
            return 0.0
        n = max(0, min(n, self.total - len(self.held)))
        self.dir.mkdir(parents=True, exist_ok=True)
        t0, told = time.time(), False
        while (got := self._try(n)) is None:
            if timeout is not None and time.time() - t0 > timeout:
                raise TimeoutError(f"no {n} free cores in {self.dir} after {timeout:g} s")
            if not told:
                print(f"waiting for {n} of {self.total} cores ({self.dir}){': ' + label if label else ''}",
                      file=sys.stderr, flush=True)
                told = True
            time.sleep(POLL_S)
        self.held += got
        return time.time() - t0

    def release(self, n: int | None = None) -> None:
        """Drop `n` held tokens (all by default)."""
        n = len(self.held) if n is None else min(n, len(self.held))
        for _ in range(n):
            self.held.pop().close()

    def resize(self, n: int, label: str = "") -> float:
        """Hold exactly `n` tokens: growing waits for the extra ones while keeping what is held."""
        if self.total <= 0:
            return 0.0
        n = min(n, self.total)
        if n <= len(self.held):
            self.release(len(self.held) - n)
            return 0.0
        if (got := self._try(n - len(self.held))) is not None:
            self.held += got
            return 0.0
        # never hold part of a request while waiting: drop everything, then take the whole amount at once
        self.release()
        return self.acquire(n, label=label)

    def in_use(self) -> int:
        """Tokens currently held by any process (probe; racy by nature, for display and tests)."""
        if not self.dir.exists():
            return 0
        busy = 0
        for i in range(self.total):
            p = self.dir / f"core-{i:03d}.lock"
            if not p.exists():
                continue
            with open(p, "a+") as f:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    busy += 1
        return busy - len(self.held)

    @contextmanager
    def hold(self, n: int, label: str = ""):
        self.acquire(n, label=label)
        try:
            yield self
        finally:
            self.release()
