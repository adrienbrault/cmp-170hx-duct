"""Batched `foamDictionary` edits. Each launcher call costs ~1.5 s, so edits are grouped."""
import gzip
import shlex
from pathlib import Path

from .. import env

REMOVE = object()


def gunzip(case: Path, rel: str) -> None:
    """foamDictionary rewrites `x` beside `x.gz`; expand first so only one copy remains."""
    p, gz = case / rel, case / (rel + ".gz")
    if not p.exists() and gz.exists():
        p.write_bytes(gzip.decompress(gz.read_bytes()))
        gz.unlink()


def edit(case: Path, edits: list[tuple[str, str, object]]) -> None:
    """Apply (file, entry, value) edits; value REMOVE deletes the entry. `-set` adds missing entries."""
    cmds = []
    for rel, entry, value in edits:
        gunzip(case, rel)
        action = "-remove" if value is REMOVE else f"-set {shlex.quote(str(value))}"
        cmds.append(f"foamDictionary {shlex.quote(rel)} -entry {shlex.quote(entry)} {action} >/dev/null")
    if cmds:
        env.foam(" && ".join(cmds), cwd=case)


def get(case: Path, rel: str, entries: list[str]) -> dict[str, str | None]:
    """Read entry values (None when absent) in one launcher call."""
    gunzip(case, rel)
    sep = "@@DUCT@@"
    cmds = [f"echo {sep}; foamDictionary {shlex.quote(rel)} -entry {shlex.quote(e)} -value 2>/dev/null || true"
            for e in entries]
    out = env.foam("; ".join(cmds), cwd=case).stdout.split(sep + "\n")[1:]
    return {e: (o.strip() or None) for e, o in zip(entries, out)}
