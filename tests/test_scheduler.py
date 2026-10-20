"""Core pool shared by concurrent simulate runs (duct.cfd.scheduler): real processes, no OpenFOAM."""
import subprocess
import sys
import textwrap

import pytest

from duct.cfd import scheduler


def _holder(tmp_path, n, total):
    """A child process holding n tokens until its stdin closes."""
    code = textwrap.dedent(f"""
        import sys
        from duct.cfd.scheduler import Pool
        p = Pool({str(tmp_path)!r}, {total})
        p.acquire({n})
        print("held", flush=True)
        sys.stdin.read()
    """)
    proc = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    return proc


def test_pool_blocks_across_processes(tmp_path):
    child = _holder(tmp_path, 3, 4)
    try:
        p = scheduler.Pool(tmp_path, 4)
        assert p.in_use() == 3
        p.acquire(1, timeout=0)
        with pytest.raises(TimeoutError):
            scheduler.Pool(tmp_path, 4).acquire(1, timeout=0.2)
        p.release()
    finally:
        child.stdin.close()
        child.wait()
    p = scheduler.Pool(tmp_path, 4)       # the child's locks died with it
    p.acquire(4, timeout=0)
    assert len(p.held) == 4
    p.release()


def test_pool_dies_with_a_killed_holder(tmp_path):
    child = _holder(tmp_path, 4, 4)
    child.kill()
    child.wait()
    scheduler.Pool(tmp_path, 4).acquire(4, timeout=2)


def test_pool_resize_and_clamp(tmp_path):
    p = scheduler.Pool(tmp_path, 4)
    p.acquire(1)
    p.resize(3)
    assert len(p.held) == 3
    p.resize(1)
    assert len(p.held) == 1
    p.resize(16)                          # more ranks than the pool: clamped, never deadlocks
    assert len(p.held) == 4
    p.release()
    assert p.held == []


def test_pool_resize_waits_for_the_whole_request(tmp_path):
    child = _holder(tmp_path, 2, 4)
    try:
        p = scheduler.Pool(tmp_path, 4)
        p.acquire(1)
        p.resize(2)                       # one more is free: grows in place
        with pytest.raises(TimeoutError):
            p.release(), p.acquire(3, timeout=0.2)
        assert p.held == []               # a failed request holds nothing
    finally:
        child.stdin.close()
        child.wait()


def test_pool_disabled_and_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCT_CORES", "0")
    monkeypatch.setenv("DUCT_POOL", str(tmp_path / "pool"))
    p = scheduler.Pool()
    assert p.total == 0 and p.dir == tmp_path / "pool"
    assert p.acquire(64) == 0.0 and p.held == []
    monkeypatch.delenv("DUCT_CORES")
    assert scheduler.Pool().total == scheduler.DEFAULT_CORES
