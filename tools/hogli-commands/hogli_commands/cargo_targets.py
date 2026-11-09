from __future__ import annotations

import os
import re
import json
import fcntl
import tomllib
import contextlib
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

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
        result = subprocess.run(
            ["pgrep", "-x", "cargo|rustc|cargo-nextest"], capture_output=True, text=True, timeout=5, check=False
        )
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


def looks_like_cargo_target(path: Path) -> bool:
    # Cargo writes CACHEDIR.TAG into every target dir it creates, and other build tools also make `target/release`.
    return (path / "CACHEDIR.TAG").is_file()


@dataclass(frozen=True, kw_only=True)
class SharedCargoTarget:
    path: Path
    reason: str


def shared_cargo_targets() -> list[SharedCargoTarget]:
    """Cargo target dirs that live outside any checkout, so builds from every repo and worktree go into them."""

    # A target inside a checkout is that checkout's own, and only a caller that checks git may remove it.
    return [shared for shared in configured_cargo_targets() if not _inside_git_work_tree(shared.path)]


def configured_cargo_targets() -> list[SharedCargoTarget]:
    """The target dirs that CARGO_TARGET_DIR, build.target-dir in the Cargo config, or the old Flox env point Cargo at."""

    cargo_home = Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo")
    candidates: list[SharedCargoTarget] = []
    if env_target := os.environ.get("CARGO_TARGET_DIR"):
        candidates.append(SharedCargoTarget(path=Path(env_target), reason="CARGO_TARGET_DIR points here."))
    else:
        candidates.append(
            SharedCargoTarget(
                path=Path.home() / ".cargo" / "target",
                reason="Cargo built here while the Flox env set CARGO_TARGET_DIR.",
            )
        )
    if config_target := _configured_target_dir(cargo_home / "config.toml"):
        candidates.append(
            SharedCargoTarget(
                path=config_target,
                reason=f"build.target-dir in {cargo_home / 'config.toml'} points here.",
            )
        )

    unique: dict[InodeKey, SharedCargoTarget] = {}
    for candidate in candidates:
        if candidate.path.is_absolute() and (key := inode_key(candidate.path)) is not None:
            unique.setdefault(key, candidate)
    return list(unique.values())


def _inside_git_work_tree(path: Path) -> bool:
    """Whether *path* or a folder above it holds a `.git` entry, which also catches a checkout whose git metadata is broken."""

    return any((directory / ".git").exists() for directory in (path, *path.parents))


def _configured_target_dir(config: Path) -> Path | None:
    try:
        target_dir = tomllib.loads(config.read_text()).get("build", {}).get("target-dir")
    except (OSError, ValueError, AttributeError):
        return None
    return Path(target_dir) if isinstance(target_dir, str) else None


def unused_cargo_target(target: Path, built_before_epoch: float) -> bool:
    """Whether no build used *target* after *built_before_epoch* and no cargo runs that could be using it now."""

    return last_cargo_build_epoch(target) < built_before_epoch and idle_cargo_target(target)


def idle_cargo_target(target: Path) -> bool:
    """Whether *target* is a real Cargo target dir and no cargo or rustc runs that could be writing to it."""

    if target.is_symlink() or not looks_like_cargo_target(target):
        return False
    # A shell with another environment can build here, and its CARGO_TARGET_DIR is not visible from this process.
    return _cargo_pids() == []


def unused_legacy_cargo_target(built_before_epoch: float) -> Path | None:
    """The ~/.cargo/target that Cargo used when the Flox env set CARGO_TARGET_DIR, if no build used it after *built_before_epoch*."""

    target = Path.home() / ".cargo" / "target"
    if os.environ.get("CARGO_TARGET_DIR"):
        return None
    return target if unused_cargo_target(target, built_before_epoch) else None


_METADATA_HASH = re.compile(r"-([0-9a-f]{16})(?=\.|$)")
_UNIT_OUTPUT_DIRS = ("deps", "build", "examples")


@dataclass(frozen=True, kw_only=True)
class _CargoUnit:
    fingerprint_dir: Path
    built_epoch: float
    dependency_fingerprints: list[str]


def unused_cargo_units(target: Path, built_before_epoch: float) -> list[Path] | None:
    """The paths of the units in *target* that no unit compiled after *built_before_epoch* needs, and the incremental caches not written since then.

    Cargo does not touch the fingerprint of a unit it reuses, and the file
    systems this runs on do not record reads, so a unit's own age cannot show
    that a build still uses it. Its dependents can: every unit's fingerprint
    JSON names the fingerprints of the units it depends on. A unit stays when
    any unit compiled in the window reaches it through that graph. A build in
    which every unit was fresh compiles nothing, so a profile that Cargo
    locked in the window without compiling a unit there is kept whole. Deleting
    a unit only costs a rebuild, because Cargo rebuilds a unit whose files are
    missing. Returns None, and nothing should be removed, when a fingerprint
    cannot be read, because a dependency edge could be missing.
    """

    try:
        target = target.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    units: dict[Path, _CargoUnit] = {}
    unit_by_fingerprint: dict[str, Path] = {}
    profiles = _cargo_profiles(target)
    unit_dirs_by_profile: dict[Path, list[Path]] = {}
    try:
        for profile in profiles:
            unit_dirs = [
                entry for entry in (profile / ".fingerprint").iterdir() if entry.is_dir() and not entry.is_symlink()
            ]
            unit_dirs_by_profile[profile] = unit_dirs
            for unit_dir in unit_dirs:
                unit = _read_cargo_unit(unit_dir, unit_by_fingerprint)
                if unit is None:
                    return None
                units[unit_dir] = unit
    except OSError:
        return None

    live: set[Path] = set()
    pending = [unit_dir for unit_dir, unit in units.items() if unit.built_epoch >= built_before_epoch]
    while pending:
        unit_dir = pending.pop()
        if unit_dir in live:
            continue
        live.add(unit_dir)
        for fingerprint in units[unit_dir].dependency_fingerprints:
            if (dependency := unit_by_fingerprint.get(fingerprint)) is not None:
                pending.append(dependency)

    unused: list[Path] = []
    for profile, unit_dirs in unit_dirs_by_profile.items():
        locked_without_compiling = _mtime(profile / ".cargo-lock") >= built_before_epoch and not any(
            units[unit_dir].built_epoch >= built_before_epoch for unit_dir in unit_dirs
        )
        if locked_without_compiling:
            continue
        outputs_by_hash: dict[str, list[Path]] = {}
        for output_dir in _UNIT_OUTPUT_DIRS:
            try:
                entries = list((profile / output_dir).iterdir())
            except OSError:
                continue
            for entry in entries:
                if match := _METADATA_HASH.search(entry.name):
                    outputs_by_hash.setdefault(match.group(1), []).append(entry)
        for unit_dir in unit_dirs:
            if unit_dir not in live:
                unused.append(unit_dir)
                unused.extend(outputs_by_hash.get(unit_dir.name.rpartition("-")[2], []))
        try:
            incremental = [entry for entry in (profile / "incremental").iterdir() if entry.is_dir()]
        except OSError:
            incremental = []
        # An incremental cache only speeds up recompiling its crate, and a compile writes a new session into it.
        unused.extend(entry for entry in incremental if _newest_child_mtime(entry) < built_before_epoch)
    # A symlinked folder inside the target, such as an incremental dir, would make a removal follow it out of the target.
    return [
        path for path in unused if os.path.realpath(path.parent) == str(path.parent) and path.is_relative_to(target)
    ]


def _cargo_profiles(target: Path) -> list[Path]:
    # Tools such as rust-analyzer and cargo-llvm-cov build into <target>/<tool>/<triple>/<profile>.
    return [
        fingerprints.parent
        for pattern in ("*/.fingerprint", "*/*/.fingerprint", "*/*/*/.fingerprint")
        for fingerprints in target.glob(pattern)
    ]


@contextlib.contextmanager
def cargo_target_locked(target: Path) -> Iterator[bool]:
    """Hold Cargo's own build lock on every profile of *target* until the block ends, or yield False when a build holds one.

    Cargo takes an exclusive flock on <profile>/.cargo-lock for every build,
    so while this holds them, a build that starts waits instead of reading
    files that the caller is removing.
    """

    held: list[IO[str]] = []
    try:
        for profile in _cargo_profiles(target):
            lock = (profile / ".cargo-lock").open("a")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                lock.close()
                yield False
                return
            held.append(lock)
        yield True
    finally:
        for held_lock in held:
            held_lock.close()


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _read_cargo_unit(unit_dir: Path, unit_by_fingerprint: dict[str, Path]) -> _CargoUnit | None:
    dependency_fingerprints: list[str] = []
    try:
        for entry in unit_dir.iterdir():
            if entry.suffix == ".json":
                for dependency in json.loads(entry.read_text())["deps"]:
                    # Cargo stores each fingerprint as a u64, written little-endian in hex in the unit's hash file.
                    dependency_fingerprints.append(int(dependency[3]).to_bytes(8, "little").hex())
            elif entry.is_file() and not entry.name.startswith(("dep-", "output-", "invoked")):
                unit_by_fingerprint[entry.read_text().strip()] = unit_dir
    except (OSError, ValueError, KeyError, IndexError, TypeError, OverflowError):
        return None
    return _CargoUnit(
        fingerprint_dir=unit_dir,
        built_epoch=_newest_child_mtime(unit_dir),
        dependency_fingerprints=dependency_fingerprints,
    )


def _newest_child_mtime(directory: Path) -> float:
    newest = 0.0
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                newest = max(newest, entry.stat(follow_symlinks=False).st_mtime)
    except OSError:
        return float("inf")
    return newest
