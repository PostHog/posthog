from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .processes import process_cwds


@dataclass(frozen=True, kw_only=True)
class InodeKey:
    """Identifies a directory independent of symlinks and of path case on a case-insensitive file system."""

    device: int
    inode: int


def inode_key(path: Path) -> InodeKey | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return InodeKey(device=stat.st_dev, inode=stat.st_ino)


def _cargo_pids() -> list[int] | None:
    try:
        result = subprocess.run(["pgrep", "-x", "cargo|rustc"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode not in (0, 1):
        return None
    return [int(pid) for pid in result.stdout.split() if pid.isdigit()]


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def worktrees_running_cargo(worktrees: Sequence[Path]) -> set[Path] | None:
    """The worktrees where cargo or rustc runs, or None when a running build cannot be traced to a directory."""

    pids = _cargo_pids()
    if pids is None:
        return None
    if not pids:
        return set()

    cwd_by_pid = process_cwds(pids)
    if any(pid not in cwd_by_pid and _is_alive(pid) for pid in pids):
        return None

    worktree_by_key = {key: worktree for worktree in worktrees if (key := inode_key(worktree)) is not None}
    busy: set[Path] = set()
    for cwd in cwd_by_pid.values():
        for directory in (Path(cwd), *Path(cwd).parents):
            key = inode_key(directory)
            if key in worktree_by_key:
                busy.add(worktree_by_key[key])
                break
    return busy


def last_cargo_build_epoch(target: Path) -> float:
    """Newest mtime under each .fingerprint dir, at <profile>/ or at <target-triple>/<profile>/, which Cargo rewrites for every unit it builds."""

    newest = 0.0
    for fingerprint_dir in (*target.glob("*/.fingerprint"), *target.glob("*/*/.fingerprint")):
        try:
            with os.scandir(fingerprint_dir) as units:
                unit_dirs = [Path(unit.path) for unit in units if unit.is_dir(follow_symlinks=False)]
            newest = max(newest, fingerprint_dir.stat().st_mtime)
        except OSError:
            continue
        for unit_dir in unit_dirs:
            try:
                with os.scandir(unit_dir) as entries:
                    for entry in entries:
                        newest = max(newest, entry.stat(follow_symlinks=False).st_mtime)
            except OSError:
                continue

    if newest == 0.0:
        try:
            newest = target.stat().st_mtime
        except OSError:
            pass
    return newest


def unused_legacy_cargo_target(built_before_epoch: float) -> Path | None:
    """The ~/.cargo/target that Cargo used when the Flox env set CARGO_TARGET_DIR, if no build used it after *built_before_epoch*."""

    target = Path.home() / ".cargo" / "target"
    if os.environ.get("CARGO_TARGET_DIR") or not target.is_dir() or target.is_symlink():
        return None
    if last_cargo_build_epoch(target) >= built_before_epoch:
        return None
    # A shell with an older Flox env can still build here, and its CARGO_TARGET_DIR is not visible from this process.
    return target if _cargo_pids() == [] else None
