from __future__ import annotations

import os
import sys
import json
import math
import time
import fcntl
import shutil
import subprocess
import dataclasses
from datetime import UTC, datetime
from pathlib import Path

import pytest
from unittest.mock import Mock, patch

import click
from click.testing import CliRunner
from hogli import telemetry
from hogli.cli import cli
from hogli_commands import worktrees
from hogli_commands.cargo_targets import (
    cargo_target_locked,
    shared_cargo_targets,
    unused_cargo_target,
    unused_cargo_units,
    unused_legacy_cargo_target,
    worktrees_running_cargo,
)
from hogli_commands.devbox import (
    coder as devbox_coder,
    config as devbox_config,
    mutagen as devbox_mutagen,
)
from hogli_commands.worktrees import (
    Worktree,
    WorktreeBox,
    _belongs_to_repo,
    _boxes_of_removed_worktrees,
    _clean_worktree_boxes,
    _collect_artifacts,
    _compute_git_state,
    _discover_root_worktrees,
    _execute,
    _git_approved_artifacts,
    _in_use,
    _include_orphans,
    _is_under,
    _leftover_worktree_dirs,
    _match_worktree_boxes,
    _parse_cutoff,
    _parse_mode,
    _populate_sizes,
    _reclaimed_bytes,
    _registered_worktrees,
    _resolve_box_action,
    _resolve_orphan_policy,
    _unattended_lock,
    _worktree_roots,
)


def _box(
    name: str, git_dir: Path | str = "admin", workspace_id: str | None = None, worktree_id: str | None = None
) -> devbox_config.WorktreeBoxRecord:
    return devbox_config.WorktreeBoxRecord(
        workspace=name, git_dir=str(git_dir), workspace_id=workspace_id, worktree_id=worktree_id
    )


def _make_worktree(path: Path) -> Worktree:
    return Worktree(source="claude", path=path, registered=True, locked=False, branch="", last_activity=0.0)


def _git_stub(responses: dict[str, tuple[int, str]]):
    # responses keyed by the git subcommand (first arg); returns (returncode, stdout).
    def _run(cwd, args, timeout=30.0):
        rc, out = responses.get(args[0], (128, ""))
        return subprocess.CompletedProcess(args=list(args), returncode=rc, stdout=out, stderr="")

    return _run


_FAKE_CLI = """\
import json, os, sys

state_path = os.environ["HOGLI_TEST_BOUNDARY_STATE"]
with open(state_path) as f:
    state = json.load(f)
tool, args = os.path.basename(sys.argv[0]), sys.argv[1:]

def save(command):
    state["commands"].append([tool, *command])
    with open(state_path, "w") as f:
        json.dump(state, f)

def selected(sessions, selector):
    key, _, value = selector.partition("=")
    return [s for s in sessions if s["labels"].get(key) == value]

if tool == "coder" and args == ["users", "show", "me", "--output", "json"]:
    print(json.dumps({"username": "test-user"}))
elif tool == "coder" and args == ["list", "--output", "json"]:
    print(json.dumps(state["workspaces"]))
elif tool == "coder" and args[:1] == ["delete"] and args[2:] == ["--yes"]:
    if not any(w["name"] == args[1] for w in state["workspaces"]):
        sys.exit(1)
    state["workspaces"] = [w for w in state["workspaces"] if w["name"] != args[1]]
    save(args)
elif tool == "mutagen" and args[:2] == ["sync", "list"] and "--label-selector" in args:
    print(json.dumps(selected(state["sessions"], args[args.index("--label-selector") + 1])))
elif tool == "mutagen" and args[:3] == ["sync", "terminate", "--label-selector"]:
    matched = selected(state["sessions"], args[3])
    state["sessions"] = [s for s in state["sessions"] if s not in matched]
    save(args)
else:
    sys.exit(1)
"""


class _FakeCoderAndMutagen:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bin_dir = tmp_path / "fake-bin"
        bin_dir.mkdir()
        for tool in ("coder", "mutagen"):
            executable = bin_dir / tool
            executable.write_text(f"#!{sys.executable}\n{_FAKE_CLI}")
            executable.chmod(0o755)
        self._state_path = tmp_path / "boundary.json"
        self._write({"workspaces": [], "sessions": [], "commands": []})
        monkeypatch.setenv("HOGLI_TEST_BOUNDARY_STATE", str(self._state_path))
        monkeypatch.setattr(devbox_coder, "_MANAGED_CODER_DIR", bin_dir)
        monkeypatch.setattr(devbox_mutagen, "_MANAGED_MUTAGEN_DIR", bin_dir)
        monkeypatch.setattr(worktrees, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_coder, "get_username", devbox_coder.get_username.__wrapped__)

    def add_running_box(self, name: str, workspace_id: str) -> None:
        state = self._read()
        state["workspaces"].append({"name": name, "id": workspace_id, "latest_build": {"status": "running"}})
        state["sessions"].append({"name": name, "labels": {"hogli-workspace": name}})
        self._write(state)

    def commands(self) -> list[list[str]]:
        return self._read()["commands"]

    def _read(self) -> dict:
        return json.loads(self._state_path.read_text())

    def _write(self, state: dict) -> None:
        self._state_path.write_text(json.dumps(state))


# Frozen reference clock (2023-11-14T22:13:20Z) for deterministic cutoff math.
_NOW = 1_700_000_000.0


@pytest.mark.parametrize(
    ("cwd", "expected"),
    [
        (Path("/repo/.claude/worktrees/a"), True),
        (Path("/repo/.claude/worktrees/a/frontend/src"), True),
        (Path("/repo/.claude/worktrees/ab"), False),
        (Path("/repo"), False),
    ],
    ids=["worktree itself", "subdirectory", "sibling with same prefix", "parent"],
)
def test_in_use_matches_the_worktree_and_its_subdirectories(cwd: Path, expected: bool) -> None:
    assert _in_use(Path("/repo/.claude/worktrees/a"), {cwd}) is expected


@pytest.mark.parametrize(
    "lsof",
    [
        Mock(side_effect=FileNotFoundError("lsof")),
        Mock(side_effect=subprocess.TimeoutExpired("lsof", 30)),
        Mock(return_value=subprocess.CompletedProcess(["lsof"], 0, stdout="", stderr="")),
    ],
    ids=["missing", "timed out", "empty"],
)
def test_process_cwds_is_none_when_lsof_gives_nothing(lsof: Mock, monkeypatch) -> None:
    monkeypatch.setattr(worktrees.sys, "platform", "darwin")
    with patch.object(worktrees.subprocess, "run", lsof):
        assert worktrees._process_cwds() is None


def test_reclaimed_properties_sum_across_unattended_tiers() -> None:
    with click.Context(click.Command("worktrees:clean")) as ctx:
        worktrees._add_reclaimed_properties(1.5e9, 2)
        worktrees._add_reclaimed_properties(-1.0, 1)

        assert ctx.meta[telemetry.COMMAND_PROPERTIES_META_KEY] == {"reclaimed_gb": 1.5, "worktrees_removed": 3}


class TestUnattendedLock:
    @pytest.fixture(autouse=True)
    def _lock_path(self, tmp_path, monkeypatch) -> Path:
        path = tmp_path / "worktrees-clean.lock"
        monkeypatch.setattr(worktrees, "_UNATTENDED_LOCK", path)
        return path

    def _take(self, dry_run: bool) -> bool:
        lock = _unattended_lock(dry_run)
        if lock is None:
            return False
        lock.close()
        return True

    def test_unattended_tiers_skip_hand_made_worktrees_and_still_clean_the_old_cargo_target(
        self, tmp_path, monkeypatch
    ) -> None:
        hand_made = tmp_path / "projects" / "repo-wt-feature"
        hand_made.mkdir(parents=True)
        discovered_sources: list[str] = []
        real_discover = worktrees._discover_candidate_worktrees

        def discover(*args, **kwargs):
            found = real_discover(*args, **kwargs)
            discovered_sources.extend(source for source, _ in found)
            return []

        legacy_cleanups: list[float] = []
        monkeypatch.setattr(worktrees, "_discover_candidate_worktrees", discover)
        monkeypatch.setattr(
            worktrees, "_registered_worktrees", lambda repo_root: {hand_made.resolve(): {"locked": False, "branch": ""}}
        )
        monkeypatch.setattr(worktrees, "_claude_scratchpad_root", lambda: tmp_path / "scratchpads")
        monkeypatch.setattr(worktrees, "_process_cwds", lambda: {Path("/nowhere")})
        monkeypatch.setattr(
            worktrees, "_clean_legacy_cargo_target", lambda cutoff, *args: legacy_cleanups.append(cutoff)
        )
        monkeypatch.setattr(worktrees, "_leftover_worktree_dirs", lambda *args: [])

        result = CliRunner().invoke(worktrees.worktrees_clean, ["--unattended", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "other" not in discovered_sources
        assert len(legacy_cleanups) == 1

    def test_second_run_same_day_is_refused(self) -> None:
        assert self._take(dry_run=False)
        assert not self._take(dry_run=False)

    def test_dry_run_does_not_consume_the_day(self) -> None:
        assert self._take(dry_run=True)
        assert self._take(dry_run=False)

    def test_concurrent_run_holding_the_lock_is_refused(self, _lock_path: Path) -> None:
        with _lock_path.open("a") as other_shell:
            fcntl.flock(other_shell, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert not self._take(dry_run=False)

    def test_run_older_than_a_day_is_due(self, _lock_path: Path) -> None:
        _lock_path.write_text(str(time.time() - 25 * 3600))
        assert self._take(dry_run=False)


class TestParseCutoff:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self, monkeypatch):
        monkeypatch.setattr("hogli_commands.worktrees.time.time", lambda: _NOW)

    @pytest.mark.parametrize(
        ("value", "expected_offset"),
        [
            ("30s", 30),
            ("15m", 15 * 60),
            ("3h", 3 * 3600),
            ("7d", 7 * 86400),
            ("2w", 2 * 604800),
        ],
        ids=["seconds", "minutes", "hours", "days", "weeks"],
    )
    def test_interval_subtracts_from_now(self, value, expected_offset) -> None:
        cutoff, _ = _parse_cutoff(value)
        assert cutoff == _NOW - expected_offset

    def test_all_includes_everything(self) -> None:
        cutoff, label = _parse_cutoff("all")
        assert cutoff == math.inf
        assert label == "all ages"

    def test_past_date_uses_local_timestamp(self) -> None:
        from datetime import datetime

        cutoff, _ = _parse_cutoff("2023-01-01")
        assert cutoff == datetime(2023, 1, 1).timestamp()

    @pytest.mark.parametrize(
        "value",
        ["nonsense", "7", "d7", "3 days", "", "0d", "0h", "2024-01-01"],
        ids=["word", "no-unit", "unit-first", "spaced", "empty", "zero-days", "zero-hours", "future-date"],
    )
    def test_invalid_or_everything_inputs_rejected(self, value) -> None:
        # Zero intervals and future dates would silently select everything, so
        # they must be rejected — only 'all' may mean everything.
        with pytest.raises(click.BadParameter):
            _parse_cutoff(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("deps", "deps"), ("build,deps", "deps,build"), (" BUILD , build ", "build"), ("full", "full")],
)
def test_parse_mode_normalizes_kinds(value: str, expected: str) -> None:
    assert _parse_mode(value) == expected


@pytest.mark.parametrize("value", ["full,deps", "deps,cache", "", ","])
def test_parse_mode_rejects_full_with_kinds_and_unknown_kinds(value: str) -> None:
    with pytest.raises(click.BadParameter):
        _parse_mode(value)


class TestBelongsToRepo:
    def test_path_inside_repo_belongs(self, tmp_path) -> None:
        repo = tmp_path / "repo"
        (repo / ".claude" / "worktrees" / "wt").mkdir(parents=True)
        wt = (repo / ".claude" / "worktrees" / "wt").resolve()
        assert _belongs_to_repo(wt, repo.resolve(), (repo / ".git").resolve())

    def test_out_of_repo_worktree_matched_via_commondir(self, tmp_path) -> None:
        repo = tmp_path / "main"
        common = repo / ".git"
        gitdir = common / "worktrees" / "wt"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n")  # gitdir/../.. == repo/.git

        wt = tmp_path / "home" / "wt"
        wt.mkdir(parents=True)
        (wt / ".git").write_text(f"gitdir: {gitdir}\n")

        assert _belongs_to_repo(wt.resolve(), repo.resolve(), common.resolve())

    def test_other_repos_worktree_rejected(self, tmp_path) -> None:
        repo = tmp_path / "main"
        gitdir = repo / ".git" / "worktrees" / "wt"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n")
        wt = tmp_path / "home" / "wt"
        wt.mkdir(parents=True)
        (wt / ".git").write_text(f"gitdir: {gitdir}\n")

        # A different repo's common dir must not match — fail closed.
        assert not _belongs_to_repo(wt.resolve(), repo.resolve(), (tmp_path / "other" / ".git").resolve())

    def test_dangling_pointer_fails_closed(self, tmp_path) -> None:
        wt = tmp_path / "home" / "wt"
        wt.mkdir(parents=True)  # no .git pointer at all
        assert not _belongs_to_repo(wt.resolve(), (tmp_path / "main").resolve(), (tmp_path / "main" / ".git").resolve())


class TestWorktreeRoots:
    @pytest.mark.parametrize(
        "override_base,branch,registered",
        [
            (True, "haacked/new-feature", False),
            (False, "haacked/new-feature", False),
            (False, "alice/feature/disk", True),
        ],
        ids=["posthog_worktree_base", "default_home_base", "registered_three_segment_branch"],
    )
    def test_phw_branch_worktree_is_discovered(
        self, tmp_path, monkeypatch, override_base: bool, branch: str, registered: bool
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        if override_base:
            base = tmp_path / "custom"
            monkeypatch.setenv("POSTHOG_WORKTREE_BASE", str(base))
        else:
            base = tmp_path / "home" / ".worktrees" / "posthog"
            monkeypatch.delenv("POSTHOG_WORKTREE_BASE", raising=False)
        wt = base / branch
        wt.mkdir(parents=True)
        (wt / ".git").write_text("gitdir: /nowhere\n")
        registry = {wt.resolve(): {"locked": False, "branch": branch}} if registered else {}

        roots = dict(_worktree_roots(tmp_path / "repo"))

        assert [p.resolve() for p in _discover_root_worktrees(roots["phw"], registry)] == [wt.resolve()]

    @pytest.mark.parametrize(
        ("selected_sources", "mode", "expected_other"),
        [(None, "deps,build", True), (None, "full", False), ({"other"}, "full", True), ({"claude"}, "deps", False)],
        ids=["artifacts_by_default", "full_skips_by_default", "full_when_named", "other_source_selected"],
    )
    def test_worktree_registered_outside_every_tool_root_is_other(
        self, tmp_path, monkeypatch, selected_sources: set[str] | None, mode: str, expected_other: bool
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        monkeypatch.setattr(worktrees, "_claude_scratchpad_root", lambda: tmp_path / "scratchpads")
        hand_made = tmp_path / "projects" / "repo-wt-feature"
        hand_made.mkdir(parents=True)
        registry = {hand_made.resolve(): {"locked": False, "branch": "feature"}}

        discovered = worktrees._discover_candidate_worktrees(tmp_path / "repo", registry, selected_sources, mode)

        assert discovered == ([("other", hand_made.resolve())] if expected_other else [])

    @pytest.mark.parametrize(
        ("layout", "trusted"),
        [("private_folder", True), ("others_can_write", False), ("symlink", False), ("missing", False)],
    )
    def test_scratchpad_root_is_trusted_only_as_a_private_folder(self, tmp_path, layout: str, trusted: bool) -> None:
        shared_tmp = tmp_path / "tmp"
        shared_tmp.mkdir()
        root = shared_tmp / f"claude-{os.getuid()}"
        if layout == "symlink":
            (tmp_path / "someone-elses-src").mkdir()
            root.symlink_to(tmp_path / "someone-elses-src", target_is_directory=True)
        elif layout != "missing":
            root.mkdir(mode=0o700)
            if layout == "others_can_write":
                root.chmod(0o777)

        assert worktrees._claude_scratchpad_root(shared_tmp) == (root if trusted else None)


def _git_worktree(path: Path, files: dict[str, str], tracked: tuple[str, ...] = ()) -> Path:
    for relative, content in files.items():
        (path / relative).parent.mkdir(parents=True, exist_ok=True)
        (path / relative).write_text(content)
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    if tracked:
        subprocess.run(["git", "add", "--", *tracked], cwd=path, check=True)
    return path


class TestCollectDepsItems:
    @pytest.mark.parametrize(
        ("mode", "orphaned", "expected_removed"),
        [
            ("build", False, {"web/dist", ".pytest_cache", "web/app.tsbuildinfo", ".flox/cache/go-build"}),
            ("deps", False, {"web/node_modules", "scratch/node_modules", "tools/.venv", ".flox/cache/venv"}),
            # Without its index, git cannot say what the branch tracks, so nothing goes.
            ("build", True, set()),
            ("deps", True, set()),
        ],
        ids=["build", "deps", "orphaned_build", "orphaned_deps"],
    )
    def test_removes_only_untracked_artifacts_and_build_output_that_git_ignores(
        self, tmp_path, mode: str, orphaned: bool, expected_removed: set[str]
    ) -> None:
        worktree = _git_worktree(
            tmp_path / "wt",
            {
                ".gitignore": "dist/\nnode_modules/\n.venv/\n*.tsbuildinfo\n.flox/cache/\n",
                "web/package.json": "{}",
                "web/dist/app.js": "",
                "web/app.tsbuildinfo": "",
                "web/node_modules/react/index.js": "",
                "web/build/notes.md": "",
                "action/package.json": "{}",
                "action/dist/index.js": "",
                ".pytest_cache/.gitignore": "*\n",
                ".pytest_cache/v/cache/lastfailed": "{}",
                "scratch/node_modules/left-pad/index.js": "",
                "vendored/node_modules/shim/index.js": "",
                "tools/.venv/pyvenv.cfg": "",
                "tools/target/release/notes.md": "",
                "libs/.venv/pyvenv.cfg": "",
                "libs/.venv/src/editable-pkg/.git/HEAD": "",
                ".flox/cache/venv/pyvenv.cfg": "",
                ".flox/cache/go-build/README": "",
                ".flox/cache/postgres/data/PG_VERSION": "16",
                "vendor/repo/.git/HEAD": "",
                "vendor/repo/package.json": "{}",
                "vendor/repo/dist/lib.js": "",
                "site/package.json": "{}",
                "site/dist/.git/HEAD": "",
                "site/dist/index.html": "",
            },
            tracked=(".gitignore", "web/package.json", "action/package.json"),
        )
        # Git adds a file under an ignored folder only by force, as a committed GitHub Action bundle or vendored package needs.
        subprocess.run(
            ["git", "add", "-f", "action/dist/index.js", "vendored/node_modules/shim/index.js"],
            cwd=worktree,
            check=True,
        )
        if orphaned:
            shutil.rmtree(worktree / ".git")
            (worktree / ".git").write_text(f"gitdir: {tmp_path / 'pruned-admin-dir'}\n")

        (worktree / "notes" / "draft.md").parent.mkdir()
        (worktree / "notes" / "draft.md").write_text("")
        (worktree / "linked").mkdir()
        (worktree / "linked" / "node_modules").symlink_to(worktree / "notes", target_is_directory=True)

        artifacts = _collect_artifacts(worktree, frozenset({mode}))
        removed = _git_approved_artifacts(worktree, artifacts)

        assert {path.relative_to(worktree.resolve()).as_posix() for path in removed} == expected_removed

    def test_never_escapes_worktree_via_symlinked_parent(self, tmp_path) -> None:
        worktree = tmp_path / "wt"
        (worktree / "node_modules").mkdir(parents=True)

        # `frontend` symlinked to shared external storage that has its own dist/.
        external = tmp_path / "external"
        (external / "dist").mkdir(parents=True)
        (external / "package.json").write_text("{}")
        (worktree / "frontend").symlink_to(external, target_is_directory=True)

        items = [artifact.path for artifact in _collect_artifacts(worktree, frozenset({"deps", "build"}))]
        worktree_resolved = worktree.resolve()

        # The real node_modules is collected; nothing resolves outside the worktree.
        assert (worktree / "node_modules").resolve() in items
        assert all(_is_under(item, worktree_resolved) for item in items)
        assert (external / "dist").resolve() not in items

    def test_deps_mode_keeps_a_cargo_target_built_after_the_cutoff(self, tmp_path) -> None:
        cutoff = time.time() - 7 * 86400
        worktree = tmp_path / "wt"
        _git_worktree(worktree, {"node_modules/left-pad/index.js": ""})
        stale_target = _write_cargo_target(worktree / "rust" / "target", cutoff - 86400)
        # Cargo rewrites fingerprint files in place, so a fresh build leaves the directory mtimes old.
        _write_cargo_target(worktree / "cli" / "target", time.time())
        _write_cargo_target(worktree / "plugin" / "target", time.time(), profile=Path("wasm32-wasip1") / "release")
        wt = _make_worktree(worktree)

        _populate_sizes([wt], "deps", cutoff)

        assert sorted(wt.artifact_items) == sorted([(worktree / "node_modules").resolve(), stale_target.resolve()])


def _write_cargo_target(target: Path, last_build_epoch: float, profile: Path = Path("debug")) -> Path:
    unit = target / profile / ".fingerprint" / "posthog-unit"
    unit.mkdir(parents=True)
    (unit / "lib-posthog").write_bytes(b"x" * 1024)
    os.utime(unit / "lib-posthog", (last_build_epoch, last_build_epoch))
    (target / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55\n")
    month_ago = time.time() - 30 * 86400
    directory = unit
    while directory != target.parent:
        os.utime(directory, (month_ago, month_ago))
        directory = directory.parent
    return target


def _write_cargo_unit(
    profile: Path, name: str, unit_hash: str, fingerprint: int, depends_on: list[int], built_epoch: float
) -> Path:
    unit = profile / ".fingerprint" / f"{name}-{unit_hash}"
    unit.mkdir(parents=True)
    (unit / f"lib-{name}").write_text(fingerprint.to_bytes(8, "little").hex())
    (unit / f"lib-{name}.json").write_text(json.dumps({"deps": [[0, "dep", False, dep] for dep in depends_on]}))
    for entry in unit.iterdir():
        os.utime(entry, (built_epoch, built_epoch))
    output = profile / "deps" / f"lib{name.replace('-', '_')}-{unit_hash}.rlib"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"rlib")
    return output


def _fake_cargo_processes(monkeypatch, cargo_cwd: Path | None, lsof_available: bool = True) -> None:
    def fake_run(args, **kwargs):
        if args[0] == "pgrep":
            return subprocess.CompletedProcess(
                args, 0 if cargo_cwd else 1, stdout=f"{os.getpid()}\n" if cargo_cwd else ""
            )
        if not lsof_available:
            raise FileNotFoundError("lsof")
        return subprocess.CompletedProcess(args, 0, stdout=f"p{os.getpid()}\nn{cargo_cwd}\n")

    monkeypatch.setattr("hogli_commands.cargo_targets.subprocess.run", fake_run)


class TestLeftoverWorktreeDirs:
    @pytest.mark.parametrize(
        ("relative", "extra_entry", "expected_leftover"),
        [
            (".claude/worktrees/gone", None, True),
            (".claude/worktrees/gone", ".git", False),
            (".claude/worktrees/gone", "docker/compose.yml", False),
            (".claude/worktrees/gone", ".flox/cache/postgres/PG_VERSION", False),
            ("home/.codex/worktrees/1a2b/repo", None, True),
            ("home/.codex/worktrees/1a2b/other-repo", None, False),
        ],
        ids=["only_go_cache", "still_a_worktree", "other_files", "flox_state", "home_root", "other_repos_name"],
    )
    def test_folder_counts_only_when_it_holds_nothing_but_flox_caches(
        self, tmp_path, monkeypatch, relative: str, extra_entry: str | None, expected_leftover: bool
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        repo = tmp_path / "repo"
        folder = tmp_path / relative if relative.startswith("home/") else repo / relative
        (folder / ".flox" / "cache" / "go" / "pkg" / "mod").mkdir(parents=True)
        if extra_entry is not None:
            (folder / extra_entry).parent.mkdir(parents=True, exist_ok=True)
            (folder / extra_entry).write_text("")

        leftovers = _leftover_worktree_dirs(repo, selected_sources=None, cutoff=time.time() + 60)

        assert leftovers == ([folder] if expected_leftover else [])


class TestCargoTargets:
    @pytest.mark.parametrize("lsof_available", [True, False], ids=["traced", "lsof_unavailable"])
    def test_worktree_with_cargo_running_below_its_root_is_busy(self, tmp_path, monkeypatch, lsof_available) -> None:
        idle, building = tmp_path / "idle", tmp_path / "building"
        cargo_cwd = building / "rust" / "capture"
        cargo_cwd.mkdir(parents=True)
        idle.mkdir()
        _fake_cargo_processes(monkeypatch, cargo_cwd, lsof_available)

        # A live cargo process that cannot be traced to a directory must block every worktree, not none.
        assert worktrees_running_cargo([idle, building]) == ({building} if lsof_available else None)

    @pytest.mark.parametrize(
        "cargo_target_dir_set,days_since_build,cargo_running,expected_offered",
        [(False, 10, False, True), (True, 10, False, True), (False, 1, False, False), (False, 10, True, False)],
        ids=["unused", "cargo_target_dir_set", "built_recently", "cargo_running_elsewhere"],
    )
    def test_legacy_cargo_target_is_offered_only_when_nothing_builds_there(
        self,
        tmp_path,
        monkeypatch,
        cargo_target_dir_set: bool,
        days_since_build: int,
        cargo_running: bool,
        expected_offered: bool,
    ) -> None:
        home = tmp_path / "home"
        target = _write_cargo_target(home / ".cargo" / "target", time.time() - days_since_build * 86400)
        monkeypatch.setattr(Path, "home", lambda: home)
        _fake_cargo_processes(monkeypatch, tmp_path if cargo_running else None)
        if cargo_target_dir_set:
            monkeypatch.setenv("CARGO_TARGET_DIR", str(target))
        else:
            monkeypatch.delenv("CARGO_TARGET_DIR", raising=False)

        cutoff = time.time() - 7 * 86400

        assert unused_legacy_cargo_target(cutoff) == (target if expected_offered and not cargo_target_dir_set else None)
        assert [shared.path for shared in shared_cargo_targets() if unused_cargo_target(shared.path, cutoff)] == (
            [target] if expected_offered else []
        )

    @pytest.mark.parametrize(
        "case", ["graph", "unreadable_fingerprint", "locked_without_compiling", "symlinked_target"]
    )
    def test_sweep_keeps_every_unit_a_recent_build_reaches(self, tmp_path, case: str) -> None:
        now = time.time()
        month_ago = now - 30 * 86400
        target = tmp_path / "target"
        profile = target / "debug"
        app_built = month_ago if case == "locked_without_compiling" else now
        _write_cargo_unit(profile, "app", "a" * 16, fingerprint=1, depends_on=[2], built_epoch=app_built)
        _write_cargo_unit(profile, "serde", "b" * 16, fingerprint=2, depends_on=[], built_epoch=month_ago)
        left_pad = _write_cargo_unit(profile, "left-pad", "c" * 16, fingerprint=3, depends_on=[], built_epoch=month_ago)
        stale_incremental = profile / "incremental" / "left_pad-0k1rn5ce8ga0p"
        recent_incremental = profile / "incremental" / "app-2k0klfowy1csk"
        for incremental, epoch in ((stale_incremental, month_ago), (recent_incremental, app_built)):
            (incremental / "s-session").mkdir(parents=True)
            os.utime(incremental / "s-session", (epoch, epoch))
        (profile / ".cargo-lock").write_text("")
        source_checkout = tmp_path / "src" / "old-module"
        (source_checkout / "lib.rs").parent.mkdir(parents=True)
        (source_checkout / "lib.rs").write_text("")
        os.utime(source_checkout / "lib.rs", (month_ago, month_ago))
        _write_cargo_unit(target / "release", "app", "d" * 16, fingerprint=4, depends_on=[], built_epoch=now)
        (target / "release" / "incremental").symlink_to(tmp_path / "src", target_is_directory=True)
        if case == "unreadable_fingerprint":
            (profile / ".fingerprint" / f"serde-{'b' * 16}" / "lib-serde.json").write_text("{not json")
        swept = target
        if case == "symlinked_target":
            swept = tmp_path / "linked-target"
            swept.symlink_to(target, target_is_directory=True)

        unused = unused_cargo_units(swept, now - 7 * 86400)

        resolved_profile = profile.resolve()
        expected = {
            "graph": {
                resolved_profile / ".fingerprint" / f"left-pad-{'c' * 16}",
                resolved_profile / "deps" / left_pad.name,
                resolved_profile / "incremental" / stale_incremental.name,
            },
            "unreadable_fingerprint": None,
            "locked_without_compiling": set(),
        }
        expected["symlinked_target"] = expected["graph"]
        assert (set(unused) if unused is not None else None) == expected[case]

    def test_target_lock_waits_for_a_build_and_blocks_one_while_held(self, tmp_path) -> None:
        target = _write_cargo_target(tmp_path / "target", time.time())
        cargo_lock = target / "debug" / ".cargo-lock"
        cargo_lock.write_text("")

        with cargo_lock.open("a") as build:
            fcntl.flock(build, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with cargo_target_locked(target) as locked:
                assert not locked

        with cargo_target_locked(target) as locked, cargo_lock.open("a") as build:
            assert locked
            with pytest.raises(BlockingIOError):
                fcntl.flock(build, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @pytest.mark.parametrize("broken_git_metadata", [False, True], ids=["checkout", "checkout_git_cannot_read"])
    def test_cargo_target_dir_inside_a_checkout_is_not_treated_as_shared(
        self, tmp_path, monkeypatch, broken_git_metadata: bool
    ) -> None:
        checkout = _git_worktree(tmp_path / "checkout", {})
        if broken_git_metadata:
            shutil.rmtree(checkout / ".git")
            (checkout / ".git").write_text(f"gitdir: {tmp_path / 'pruned-admin-dir'}\n")
        target = _write_cargo_target(checkout / "target", time.time() - 10 * 86400)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        monkeypatch.setenv("CARGO_TARGET_DIR", str(target))

        assert [shared.path for shared in shared_cargo_targets()] == []


class TestRegisteredWorktrees:
    def test_parses_branch_detached_and_locked(self, tmp_path, monkeypatch) -> None:
        porcelain = (
            "worktree /repo\n"
            "HEAD abc\n"
            "branch refs/heads/master\n"
            "\n"
            "worktree /repo/.claude/worktrees/a\n"
            "HEAD def\n"
            "detached\n"
            "\n"
            "worktree /repo/.claude/worktrees/b\n"
            "HEAD 123\n"
            "branch refs/heads/feature\n"
            "locked under review\n"
        )
        monkeypatch.setattr("hogli_commands.worktrees.subprocess.check_output", lambda *a, **k: porcelain)

        registry = _registered_worktrees(tmp_path)
        assert registry is not None
        by_name = {p.name: meta for p, meta in registry.items()}
        assert by_name["repo"]["branch"] == "master"
        assert by_name["a"]["branch"] == "(detached)" and not by_name["a"]["locked"]
        assert by_name["b"]["branch"] == "feature" and by_name["b"]["locked"]

    def test_git_error_returns_none(self, monkeypatch, tmp_path) -> None:
        def _boom(*a, **k):
            raise subprocess.CalledProcessError(1, "git")

        monkeypatch.setattr("hogli_commands.worktrees.subprocess.check_output", _boom)
        # None (not {}) so the caller can refuse rather than treat all as unlocked.
        assert _registered_worktrees(tmp_path) is None


class TestComputeGitState:
    def test_genuine_detached_head(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            "hogli_commands.worktrees._git",
            _git_stub({"status": (0, ""), "symbolic-ref": (1, ""), "rev-list": (0, "0\n")}),
        )
        wt = _make_worktree(tmp_path)
        _compute_git_state(wt, has_remotes=True)
        assert wt.detached and not wt.dirty and wt.unpushed == 0 and not wt.state_unknown and not wt.unsafe

    def test_orphaned_pruned_gitdir_is_safe(self, tmp_path, monkeypatch) -> None:
        # Orphaned worktree: .git points to a gitdir that no longer exists. git
        # can't read it (rc 128), but committed work survives in the branch ref,
        # so it's safe to remove by default — not flagged unsafe.
        (tmp_path / ".git").write_text(f"gitdir: {tmp_path / 'missing-gitdir'}\n")
        monkeypatch.setattr(
            "hogli_commands.worktrees._git",
            _git_stub({"status": (128, ""), "symbolic-ref": (128, ""), "rev-list": (128, "")}),
        )
        wt = _make_worktree(tmp_path)
        _compute_git_state(wt, has_remotes=True)
        assert not wt.state_unknown and not wt.unsafe and not wt.detached

    def test_present_gitdir_but_unreadable_fails_closed(self, tmp_path, monkeypatch) -> None:
        # gitdir still exists but git can't read status (corruption/lock/timeout)
        # — git should have been able to, so we can't confirm clean → fail closed.
        gitdir = tmp_path / "live-gitdir"
        gitdir.mkdir()
        (tmp_path / ".git").write_text(f"gitdir: {gitdir}\n")
        monkeypatch.setattr(
            "hogli_commands.worktrees._git",
            _git_stub({"status": (128, ""), "symbolic-ref": (128, ""), "rev-list": (128, "")}),
        )
        wt = _make_worktree(tmp_path)
        _compute_git_state(wt, has_remotes=True)
        assert wt.state_unknown and wt.unsafe

    def test_status_timeout_fails_closed(self, tmp_path, monkeypatch) -> None:
        # _git returns None on a status timeout, with the gitdir present → unsafe.
        gitdir = tmp_path / "live-gitdir"
        gitdir.mkdir()
        (tmp_path / ".git").write_text(f"gitdir: {gitdir}\n")
        monkeypatch.setattr("hogli_commands.worktrees._git", lambda cwd, args, timeout=30.0: None)
        wt = _make_worktree(tmp_path)
        _compute_git_state(wt, has_remotes=True)
        assert wt.state_unknown and wt.unsafe

    def test_dirty_and_unpushed_are_unsafe(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            "hogli_commands.worktrees._git",
            _git_stub({"status": (0, " M file.py\n"), "symbolic-ref": (0, "refs/heads/x"), "rev-list": (0, "3\n")}),
        )
        wt = _make_worktree(tmp_path)
        _compute_git_state(wt, has_remotes=True)
        assert wt.dirty and wt.unpushed == 3 and not wt.detached and wt.unsafe

    def test_untracked_file_is_dirty_when_git_config_hides_untracked_files(self, tmp_path) -> None:
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        subprocess.run(["git", "config", "status.showUntrackedFiles", "no"], cwd=tmp_path, check=True)
        (tmp_path / "new.py").write_text("never added\n")

        wt = _make_worktree(tmp_path)
        _compute_git_state(wt, has_remotes=False)
        assert wt.dirty and wt.unsafe

    def test_squash_merged_branch_is_safe_until_it_gets_a_new_commit(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(worktrees.shutil, "which", lambda name: None)

        def git(cwd: Path, *args: str) -> None:
            subprocess.run(
                ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                cwd=cwd,
                check=True,
                capture_output=True,
            )

        remote, repo, worktree = tmp_path / "remote.git", tmp_path / "repo", tmp_path / "topic"
        git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
        git(tmp_path, "clone", "-q", str(remote), str(repo))
        (repo / "a.txt").write_text("one\n")
        git(repo, "add", "a.txt")
        git(repo, "commit", "-q", "-m", "first")
        git(repo, "push", "-q", "origin", "main")
        git(repo, "worktree", "add", "-q", "-b", "topic", str(worktree), "origin/main")
        for name, text in (("b.txt", "two\n"), ("a.txt", "one\nmore\n")):
            (worktree / name).write_text(text)
            git(worktree, "add", name)
            git(worktree, "commit", "-q", "-m", f"change {name}")
        (repo / "c.txt").write_text("landed first\n")
        git(repo, "add", "c.txt")
        git(repo, "commit", "-q", "-m", "unrelated")
        git(repo, "merge", "--squash", "topic")
        git(repo, "commit", "-q", "-m", "topic (#1)")
        git(repo, "push", "-q", "origin", "main")
        git(worktree, "fetch", "-q", "origin")

        merged = _make_worktree(worktree)
        _compute_git_state(merged, has_remotes=True)
        assert merged.unpushed == 2 and merged.squash_merged is not None and not merged.unsafe

        (worktree / "d.txt").write_text("after the merge\n")
        git(worktree, "add", "d.txt")
        git(worktree, "commit", "-q", "-m", "after the merge")
        later = _make_worktree(worktree)
        _compute_git_state(later, has_remotes=True)
        assert later.unpushed == 3 and later.squash_merged is None and later.unsafe

    def test_no_remotes_skips_unpushed_check(self, tmp_path, monkeypatch) -> None:
        # Without remotes, rev-list HEAD --not --remotes would count every commit;
        # the check must be skipped so a clean local-only worktree isn't flagged.
        monkeypatch.setattr(
            "hogli_commands.worktrees._git",
            _git_stub({"status": (0, ""), "symbolic-ref": (0, "refs/heads/x"), "rev-list": (0, "999\n")}),
        )
        wt = _make_worktree(tmp_path)
        _compute_git_state(wt, has_remotes=False)
        assert wt.unpushed == 0 and not wt.unsafe


class TestOrphanPolicy:
    @pytest.mark.parametrize(
        ("explicit", "mode", "expected"),
        [
            (None, "full", "ask"),  # full defaults to prompting
            (None, "deps", "yes"),  # deps defaults to cleaning orphans
            ("no", "full", "no"),
            ("YES", "deps", "yes"),  # explicit wins, case-insensitive
        ],
        ids=["full-default", "deps-default", "explicit-no", "explicit-case"],
    )
    def test_default_varies_by_mode(self, explicit, mode, expected) -> None:
        assert _resolve_orphan_policy(explicit, mode) == expected

    def test_yes_includes_without_prompt(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("click.confirm", lambda *a, **k: pytest.fail("must not prompt"))
        orphans = [_make_worktree(tmp_path)]
        assert _include_orphans("yes", orphans, dry_run=False, yes=False) is True

    def test_no_skips(self, tmp_path) -> None:
        assert _include_orphans("no", [_make_worktree(tmp_path)], dry_run=False, yes=False) is False

    @pytest.mark.parametrize("answer", [True, False])
    def test_ask_interactive_uses_prompt(self, tmp_path, monkeypatch, answer) -> None:
        monkeypatch.setattr("click.confirm", lambda *a, **k: answer)
        assert _include_orphans("ask", [_make_worktree(tmp_path)], dry_run=False, yes=False) is answer

    @pytest.mark.parametrize(("dry_run", "yes"), [(True, False), (False, True)], ids=["dry-run", "yes-flag"])
    def test_ask_includes_when_cannot_prompt(self, tmp_path, monkeypatch, dry_run, yes) -> None:
        # --dry-run (preview) and --yes (non-interactive) can't prompt → include.
        monkeypatch.setattr("click.confirm", lambda *a, **k: pytest.fail("must not prompt"))
        assert _include_orphans("ask", [_make_worktree(tmp_path)], dry_run=dry_run, yes=yes) is True


class TestResolveBoxAction:
    @pytest.mark.parametrize(
        ("flags", "saved", "mode", "expected"),
        [
            ((False, False, False), None, "full", None),
            ((False, False, False), "delete", "full", "delete"),
            ((True, False, False), "delete", "full", "stop"),
            ((False, True, False), None, "full", "delete"),
            ((False, False, True), "stop", "full", None),
            ((False, False, False), "stop", "deps", None),
        ],
        ids=["default-off", "saved-config", "flag-beats-config", "delete-flag", "keep-beats-config", "deps-ignores"],
    )
    def test_flags_and_saved_config(self, monkeypatch, flags, saved, mode, expected) -> None:
        monkeypatch.setattr(worktrees, "saved_worktree_box_cleanup", lambda: saved)
        assert _resolve_box_action(*flags, mode) == expected

    @pytest.mark.parametrize(
        ("flags", "mode"),
        [((True, True, False), "full"), ((True, False, False), "deps")],
        ids=["two-flags", "deps-mode"],
    )
    def test_conflicting_flags_rejected(self, flags, mode) -> None:
        with pytest.raises(click.UsageError):
            _resolve_box_action(*flags, mode)


class TestWorktreeBoxes:
    @pytest.fixture
    def registry_path(self, tmp_path, monkeypatch) -> Path:
        path = tmp_path / "boxes.json"
        monkeypatch.setattr(devbox_config, "get_worktree_boxes_path", lambda: path)
        return path

    @pytest.mark.parametrize(
        ("case", "matched"),
        [("same-path", True), ("moved", True), ("recreated-at-same-path", False), ("no-worktree-id-recorded", False)],
    )
    def test_matches_a_worktree_only_by_the_id_in_its_admin_directory(self, tmp_path, case, matched) -> None:
        admin = tmp_path / "repo" / ".git" / "worktrees" / "feature"
        admin.mkdir(parents=True)
        registered_path = tmp_path / "old" / "feature"
        current = tmp_path / "moved" / "feature" if case == "moved" else registered_path
        current.mkdir(parents=True)
        (current / ".git").write_text(f"gitdir: {admin}\n")
        worktree_id = devbox_config.ensure_worktree_id(admin)
        if case == "recreated-at-same-path":
            (admin / "hogli-devbox-worktree-id").unlink()
        record = _box(
            "devbox-test-user-feature",
            git_dir=admin,
            worktree_id=None if case == "no-worktree-id-recorded" else worktree_id,
        )

        boxes = _match_worktree_boxes([_make_worktree(current)], {str(registered_path): record})

        expected = [WorktreeBox(worktree_path=registered_path, record=record, current_path=current)]
        assert boxes == (expected if matched else [])

    @pytest.mark.parametrize(
        ("case", "sources", "pending"),
        [
            ("removed", None, True),
            ("removed", {"claude"}, True),
            ("removed", {"phw"}, False),
            ("moved", None, False),
            ("folder-deleted", None, True),
            ("folder-deleted-locked", None, False),
            ("admin-dir-reused", None, True),
            ("other-repo", None, False),
        ],
        ids=[
            "removed",
            "removed-source-selected",
            "source-not-selected",
            "moved",
            "folder-deleted-admin-dir-left-behind",
            "locked-worktree-on-an-unmounted-drive",
            "admin-dir-reused-by-another-worktree",
            "other-repo",
        ],
    )
    def test_pending_boxes_need_a_removed_worktree_in_the_selected_scope(
        self, tmp_path, case, sources, pending
    ) -> None:
        repo = tmp_path / "repo"
        common = repo / ".git"
        other_common = tmp_path / "other" / ".git"
        (common / "worktrees").mkdir(parents=True)
        (other_common / "worktrees").mkdir(parents=True)
        admin = (other_common if case == "other-repo" else common) / "worktrees" / "feature"
        keeps_admin_dir = case in ("moved", "folder-deleted", "folder-deleted-locked")
        if keeps_admin_dir or case == "admin-dir-reused":
            admin.mkdir()
        if keeps_admin_dir:
            checkout = tmp_path / ("moved" if case == "moved" else "deleted") / "feature"
            if case == "moved":
                checkout.mkdir(parents=True)
                (checkout / ".git").write_text(f"gitdir: {admin}\n")
            (admin / "gitdir").write_text(f"{checkout / '.git'}\n")
        if case == "folder-deleted-locked":
            (admin / "locked").write_text("")
        worktree_id = devbox_config.ensure_worktree_id(admin) if keeps_admin_dir else "id-of-the-removed-worktree"
        record = _box("devbox-test-user-feature", git_dir=admin, worktree_id=worktree_id)
        registry = {str(repo / ".claude" / "worktrees" / "feature"): record}

        boxes = _boxes_of_removed_worktrees(registry, repo, common, sources)

        expected = [WorktreeBox(worktree_path=repo / ".claude" / "worktrees" / "feature", record=record)]
        assert boxes == (expected if pending else [])

    @pytest.mark.parametrize(
        ("path_arg", "expected_workspaces"),
        [
            (None, ["devbox-test-user-feature", "devbox-test-user-other"]),
            ("link/.herdr-wt/feature", ["devbox-test-user-feature"]),
        ],
        ids=["every-removed-worktree", "only-the-path-herdr-reports-through-a-symlink"],
    )
    def test_prune_acts_on_removed_worktrees_or_only_the_given_path(
        self, tmp_path, monkeypatch, path_arg: str | None, expected_workspaces: list[str]
    ) -> None:
        repo = tmp_path / "repo"
        common = repo / ".git"
        (common / "worktrees").mkdir(parents=True)
        (tmp_path / "link").symlink_to(repo, target_is_directory=True)
        monkeypatch.setattr(devbox_config, "get_worktree_boxes_path", lambda: tmp_path / "boxes.json")
        monkeypatch.setattr(worktrees, "_git_common_dir", lambda start: common)
        for name in ("feature", "other"):
            devbox_config.record_worktree_box(
                repo / ".herdr-wt" / name,
                _box(f"devbox-test-user-{name}", git_dir=common / "worktrees" / name, worktree_id=f"id-{name}"),
            )
        cleaned: list[tuple[list[str], str, bool]] = []
        monkeypatch.setattr(
            worktrees,
            "_clean_worktree_boxes",
            lambda boxes, action, require_removed=False: cleaned.append(
                ([b.workspace for b in boxes], action, require_removed)
            ),
        )

        worktrees.prune_boxes_of_removed_worktrees(
            repo, "stop", None if path_arg is None else tmp_path / path_arg, dry_run=False
        )

        assert cleaned == [(expected_workspaces, "stop", True)]

    @pytest.mark.parametrize(
        ("change", "pruned"),
        [
            ("none", False),
            ("worktree-removed", True),
            ("mirror-wrote-the-folder-back", True),
            ("git-dir-gone", True),
            ("recreated-at-the-path-to-take-over-the-box", False),
        ],
    )
    def test_prune_deletes_the_box_once_its_folder_no_longer_holds_the_worktree(
        self, tmp_path, monkeypatch, git, change: str, pruned: bool
    ) -> None:
        repo, worktree, admin, record, boundary = self._worktree_with_a_running_box(tmp_path, monkeypatch, git)

        if change != "none":
            git(repo, "worktree", "remove", "--force", str(worktree))
        if change == "mirror-wrote-the-folder-back":
            worktree.mkdir(parents=True)
            (worktree / "README.md").write_text("synced back from the box\n")
        if change == "git-dir-gone":
            git(repo, "worktree", "add", "-q", str(worktree), "feature")
            shutil.rmtree(admin)
        if change == "recreated-at-the-path-to-take-over-the-box":
            git(repo, "worktree", "add", "-q", str(worktree), "feature")
        monkeypatch.chdir(repo)

        result = CliRunner().invoke(cli, ["devbox:worktree:prune", "--delete"])

        assert result.exit_code == 0, result.output
        selector = worktrees.mutagen.workspace_label_selector("devbox-test-user-feature")
        if pruned:
            assert boundary.commands() == [
                ["mutagen", "sync", "terminate", "--label-selector", selector],
                ["coder", "delete", "devbox-test-user-feature", "--yes"],
            ]
            assert devbox_config.load_worktree_boxes() == {}
        else:
            assert boundary.commands() == []
            assert devbox_config.load_worktree_boxes() == {str(worktree): record}
        assert worktree.exists() is (change != "worktree-removed")

    @pytest.mark.parametrize("takes_over_the_box_before_clean_acts", [True, False])
    def test_clean_leaves_the_box_alone_when_its_worktree_comes_back_while_it_asks(
        self, tmp_path, monkeypatch, git, takes_over_the_box_before_clean_acts: bool
    ) -> None:
        repo, worktree, admin, record, boundary = self._worktree_with_a_running_box(tmp_path, monkeypatch, git)
        git(repo, "worktree", "remove", "--force", str(worktree))
        worktree.mkdir(parents=True)
        (worktree / "README.md").write_text("synced back from the box\n")
        taken_over = dataclasses.replace(record, worktree_id="id-of-the-recreated-worktree")
        expected_record = taken_over if takes_over_the_box_before_clean_acts else record

        def recreate_the_worktree_then_confirm(*args, **kwargs) -> bool:
            if not (worktree / ".git").exists():
                shutil.rmtree(worktree)
                git(repo, "worktree", "add", "-q", str(worktree), "feature")
                if takes_over_the_box_before_clean_acts:
                    devbox_config.record_worktree_box(worktree, taken_over)
            return True

        monkeypatch.setattr(worktrees.click, "confirm", recreate_the_worktree_then_confirm)

        result = CliRunner().invoke(
            cli, ["worktrees:clean", "--before", "all", "--mode", "full", "--delete-boxes", "--repo", str(repo)]
        )

        assert result.exit_code == 0, result.output
        assert boundary.commands() == []
        assert devbox_config.load_worktree_boxes() == {str(worktree): expected_record}

    def _worktree_with_a_running_box(self, tmp_path, monkeypatch, git):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "hogli.yaml").write_text("")
        git(repo, "init", "-q", "-b", "master")
        git(repo, "commit", "-q", "--allow-empty", "-m", "init")
        worktree = tmp_path / "worktrees" / "feature"
        git(repo, "worktree", "add", "-q", "-b", "feature", str(worktree))
        admin = repo / ".git" / "worktrees" / "feature"
        record = _box(
            "devbox-test-user-feature",
            git_dir=admin,
            workspace_id="ws-feature",
            worktree_id=devbox_config.ensure_worktree_id(admin),
        )
        monkeypatch.setattr(devbox_config, "get_worktree_boxes_path", lambda: tmp_path / "boxes.json")
        devbox_config.record_worktree_box(worktree, record)
        boundary = _FakeCoderAndMutagen(tmp_path, monkeypatch)
        boundary.add_running_box("devbox-test-user-feature", "ws-feature")
        return repo, worktree, admin, record, boundary

    @pytest.mark.parametrize(
        ("prune_already_running", "expected_prune_attempts", "box_still_tracked"),
        [(False, [False], False), (True, [], True)],
        ids=["prune-started-during-clean-is-skipped", "clean-gives-up-on-a-prune-that-outlasts-the-wait"],
    )
    def test_clean_and_a_prune_never_act_on_the_same_boxes(
        self,
        tmp_path,
        monkeypatch,
        registry_path,
        prune_already_running: bool,
        expected_prune_attempts: list[bool],
        box_still_tracked: bool,
    ) -> None:
        worktree = tmp_path / "wt"
        record = _box("devbox-test-user-wt", worktree_id="id-wt")
        devbox_config.record_worktree_box(worktree, record)
        registry_before = devbox_config.load_worktree_boxes()
        monkeypatch.setattr(worktrees, "_PRUNE_LOCK_TIMEOUT_SECONDS", 0)
        prune_attempts: list[bool] = []

        def execute(stale, mode, repo_root, before_remove):
            with devbox_config.worktree_prune_lock() as holds_lock:
                prune_attempts.append(holds_lock)
            return worktrees._ReapResult(reclaimed_bytes=0, removed=1, failed=0)

        monkeypatch.setattr(worktrees, "_execute", execute)

        def clean() -> None:
            worktrees._remove_worktrees_and_their_boxes(
                [_make_worktree(worktree)],
                "full",
                tmp_path,
                [WorktreeBox(worktree_path=worktree, record=record, current_path=worktree)],
                box_action=None,
            )

        if prune_already_running:
            with devbox_config.worktree_prune_lock():
                clean()
        else:
            clean()

        assert prune_attempts == expected_prune_attempts
        assert devbox_config.load_worktree_boxes() == (registry_before if box_still_tracked else {})

    @pytest.mark.parametrize(
        ("same_worktree", "background", "keep_record", "expected_calls"),
        [
            (True, False, False, ["mirror", "stop"]),
            (True, False, True, ["mirror", "stop:keeps-record"]),
            (True, True, False, ["mirror", "background:stop"]),
            (False, False, False, []),
        ],
        ids=[
            "own-box",
            "own-box-of-an-archived-worktree",
            "own-box-in-the-background",
            "box-of-an-earlier-worktree-at-the-path",
        ],
    )
    def test_teardown_stops_the_mirror_before_acting_on_its_own_box(
        self, tmp_path, monkeypatch, same_worktree: bool, background: bool, keep_record: bool, expected_calls: list[str]
    ) -> None:
        worktree = tmp_path / "wt"
        admin = tmp_path / "admin"
        admin.mkdir()
        worktree_id = devbox_config.ensure_worktree_id(admin)
        monkeypatch.setattr(devbox_config, "get_worktree_boxes_path", lambda: tmp_path / "boxes.json")
        devbox_config.record_worktree_box(
            worktree,
            _box(
                "devbox-test-user-wt",
                git_dir=admin,
                worktree_id=worktree_id if same_worktree else "id-of-an-earlier-worktree",
            ),
        )
        calls: list[str] = []
        monkeypatch.setattr(worktrees.mutagen, "sync_terminate", lambda selector: calls.append("mirror"))
        monkeypatch.setattr(
            worktrees,
            "_clean_worktree_boxes",
            lambda boxes, action, keep_stopped_records=False: calls.append(
                f"{action}:keeps-record" if keep_stopped_records else action
            ),
        )

        act_on_box = (lambda box, action: calls.append(f"background:{action}")) if background else None

        box = worktrees.teardown_worktree_box(
            worktree, admin, "stop", dry_run=False, keep_record=keep_record, act_on_box=act_on_box
        )

        assert (box is not None) is same_worktree
        assert calls == expected_calls

    @pytest.mark.parametrize(
        ("registered_worktree_id", "expected_cleaned"),
        [("id-checked-by-teardown", ["devbox-test-user-wt"]), ("id-of-a-worktree-recreated-since", [])],
        ids=["box-still-held", "box-taken-over-by-a-recreated-worktree"],
    )
    def test_background_box_action_skips_a_box_taken_over_since_the_teardown(
        self, tmp_path, monkeypatch, registered_worktree_id: str, expected_cleaned: list[str]
    ) -> None:
        worktree = tmp_path / "wt"
        monkeypatch.setattr(devbox_config, "get_worktree_boxes_path", lambda: tmp_path / "boxes.json")
        devbox_config.record_worktree_box(worktree, _box("devbox-test-user-wt", worktree_id=registered_worktree_id))
        cleaned: list[str] = []
        monkeypatch.setattr(
            worktrees,
            "_clean_worktree_boxes",
            lambda boxes, action, keep_stopped_records=False: cleaned.extend(box.workspace for box in boxes),
        )

        worktrees.clean_registered_box(worktree, "id-checked-by-teardown", "stop", keep_record=False)

        assert cleaned == expected_cleaned

    @pytest.mark.parametrize(
        ("action", "status", "live_id", "last_used_at", "keep_stopped", "expected_calls"),
        [
            ("delete", "running", "id-a", None, False, [("delete", "devbox-test-user-a")]),
            ("stop", "running", "id-a", None, False, [("stop", "devbox-test-user-a")]),
            ("stop", "stopped", "id-a", None, False, []),
            ("delete", "running", "id-recreated", None, False, []),
            ("delete", "running", "id-a", "2026-01-01T00:00:00.123456789Z", False, [("delete", "devbox-test-user-a")]),
            ("delete", "running", "id-a", "2026-03-01T00:00:00Z", False, []),
            ("delete", "running", "id-a", "", False, []),
            ("stop", "running", "id-a", None, True, [("stop", "devbox-test-user-a")]),
            ("delete", "running", "id-a", None, True, [("delete", "devbox-test-user-a")]),
        ],
        ids=[
            "delete",
            "stop-running",
            "stop-already-stopped",
            "recreated-box-left-alone",
            "idle-past-cutoff",
            "used-after-cutoff-kept",
            "unknown-last-use-kept",
            "stopped-box-keeps-its-record-for-a-recreated-worktree",
            "deleted-box-forgotten-even-when-keeping-stopped",
        ],
    )
    def test_acts_on_existing_box_and_forgets_it(
        self, tmp_path, monkeypatch, registry_path, action, status, live_id, last_used_at, keep_stopped, expected_calls
    ) -> None:
        calls: list[tuple[str, str]] = []
        terminated: list[str] = []
        monkeypatch.setattr(worktrees, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(
            worktrees,
            "fetch_user_workspaces",
            lambda: [{"name": "devbox-test-user-a", "id": live_id, "status": status, "last_used_at": last_used_at}],
        )
        monkeypatch.setattr(worktrees, "get_workspace_status", lambda ws: ws["status"])
        monkeypatch.setattr(worktrees, "delete_workspace", lambda name: calls.append(("delete", name)))
        monkeypatch.setattr(worktrees, "stop_workspace", lambda name: calls.append(("stop", name)))
        monkeypatch.setattr(worktrees.mutagen, "sync_terminate", terminated.append)
        forgotten_in_herdr: list[str] = []
        monkeypatch.setattr(worktrees.herdr, "forget_machine", forgotten_in_herdr.append)
        box_a, box_b = _box("devbox-test-user-a", workspace_id="id-a"), _box("devbox-test-user-b")
        devbox_config.record_worktree_box(tmp_path / "a", box_a)
        devbox_config.record_worktree_box(tmp_path / "b", box_b)

        _clean_worktree_boxes(
            [
                WorktreeBox(worktree_path=tmp_path / "a", record=box_a),
                WorktreeBox(worktree_path=tmp_path / "b", record=box_b),
            ],
            action,
            keep_stopped_records=keep_stopped,
            **({} if last_used_at is None else {"idle_before": datetime(2026, 2, 1, tzinfo=UTC).timestamp()}),
        )

        assert calls == expected_calls
        assert forgotten_in_herdr == [name for call, name in expected_calls if call == "delete"]
        acted = live_id == box_a.workspace_id and (last_used_at is None or bool(expected_calls))
        assert terminated == ([worktrees.mutagen.workspace_label_selector("devbox-test-user-a")] if acted else [])
        kept = live_id == box_a.workspace_id and (not acted or (keep_stopped and action == "stop"))
        assert devbox_config.load_worktree_boxes() == ({str(tmp_path / "a"): box_a} if kept else {})

    @pytest.mark.parametrize(
        ("action", "status", "expected_calls"),
        [
            ("delete", "running", [("hogland-delete", "wt-a"), ("coder-delete", "devbox-test-user-b")]),
            ("stop", "running", [("hogland-hibernate", "wt-a"), ("coder-stop", "devbox-test-user-b")]),
            ("stop", "hibernated", [("coder-stop", "devbox-test-user-b")]),
        ],
        ids=["delete", "stop-hibernates", "stop-already-hibernated"],
    )
    def test_routes_each_box_to_its_own_provider(
        self, tmp_path, monkeypatch, registry_path, action, status, expected_calls
    ) -> None:
        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(worktrees, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(
            worktrees,
            "fetch_user_workspaces",
            lambda: [{"name": "devbox-test-user-b", "id": "id-b", "status": "running"}],
        )
        monkeypatch.setattr(worktrees, "get_workspace_status", lambda ws: ws["status"])
        monkeypatch.setattr(worktrees, "delete_workspace", lambda name: calls.append(("coder-delete", name)))
        monkeypatch.setattr(worktrees, "stop_workspace", lambda name: calls.append(("coder-stop", name)))
        monkeypatch.setattr(worktrees.hogland, "ensure_cli", lambda: None)
        monkeypatch.setattr(
            worktrees.hogland, "fetch_devboxes", lambda: [{"name": "wt-a", "id": "created-a", "status": status}]
        )
        monkeypatch.setattr(worktrees.hogland, "delete", lambda name: calls.append(("hogland-delete", name)))
        monkeypatch.setattr(worktrees.hogland, "hibernate", lambda name: calls.append(("hogland-hibernate", name)))
        monkeypatch.setattr(worktrees.hogland, "forget_ssh_entry", lambda name: None)
        monkeypatch.setattr(worktrees.mutagen, "sync_terminate", lambda selector: None)
        devbox_config.record_worktree_box(
            tmp_path / "a",
            devbox_config.WorktreeBoxRecord(
                workspace="wt-a", git_dir="admin", workspace_id="created-a", provider="hogland"
            ),
        )
        devbox_config.record_worktree_box(tmp_path / "b", _box("devbox-test-user-b", workspace_id="id-b"))

        _clean_worktree_boxes(
            [
                WorktreeBox(worktree_path=Path(path), record=record)
                for path, record in devbox_config.load_worktree_boxes().items()
            ],
            action,
        )

        assert calls == expected_calls
        assert devbox_config.load_worktree_boxes() == {}

    @pytest.mark.parametrize(
        "listed",
        [[{"name": "devbox-test-user-a", "id": "id-a"}], None],
        ids=["delete-fails", "listing-fails"],
    )
    def test_failed_box_action_keeps_registry_entry(self, tmp_path, monkeypatch, registry_path, listed) -> None:
        def fail(name: str) -> None:
            raise SystemExit(1)

        monkeypatch.setattr(worktrees, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(worktrees, "fetch_user_workspaces", lambda: listed)
        monkeypatch.setattr(worktrees, "delete_workspace", fail)
        monkeypatch.setattr(worktrees, "extract_workspace_label", lambda name: "a")
        monkeypatch.setattr(worktrees.mutagen, "sync_terminate", lambda selector: None)
        record = _box("devbox-test-user-a", workspace_id="id-a")
        devbox_config.record_worktree_box(tmp_path / "a", record)

        _clean_worktree_boxes([WorktreeBox(worktree_path=tmp_path / "a", record=record)], "delete")

        assert devbox_config.load_worktree_boxes() == {str(tmp_path / "a"): record}

    def test_box_without_a_workspace_id_is_left_alone(self, tmp_path, monkeypatch, registry_path) -> None:
        deleted: list[str] = []
        monkeypatch.setattr(worktrees, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(
            worktrees, "fetch_user_workspaces", lambda: [{"name": "devbox-test-user-a", "id": "id-recreated"}]
        )
        monkeypatch.setattr(worktrees, "delete_workspace", deleted.append)
        monkeypatch.setattr(worktrees.mutagen, "sync_terminate", lambda selector: None)
        devbox_config.record_worktree_box(tmp_path / "a", _box("devbox-test-user-a"))

        _clean_worktree_boxes([WorktreeBox(worktree_path=tmp_path / "a", record=_box("devbox-test-user-a"))], "delete")

        assert deleted == []

    @pytest.mark.parametrize(
        ("require_removed", "expected_deleted"),
        [(True, []), (False, ["devbox-test-user-a"])],
        ids=["prune-leaves-the-adopted-box-alone", "the-new-record-survives-the-cleanup"],
    )
    def test_worktree_recreated_during_the_listing_keeps_its_record(
        self, tmp_path, monkeypatch, registry_path, require_removed, expected_deleted
    ) -> None:
        stale = _box("devbox-test-user-a", workspace_id="id-a", worktree_id="id-of-the-removed-worktree")
        adopted = _box("devbox-test-user-a", workspace_id="id-a", worktree_id="id-of-the-new-worktree")
        devbox_config.record_worktree_box(tmp_path / "a", stale)

        def list_while_a_worktree_reclaims_the_path() -> list[dict[str, str]]:
            (tmp_path / "a").mkdir()
            devbox_config.record_worktree_box(tmp_path / "a", adopted)
            return [{"name": "devbox-test-user-a", "id": "id-a", "status": "running"}]

        deleted: list[str] = []
        monkeypatch.setattr(worktrees, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(worktrees, "fetch_user_workspaces", list_while_a_worktree_reclaims_the_path)
        monkeypatch.setattr(worktrees, "delete_workspace", deleted.append)
        monkeypatch.setattr(worktrees.herdr, "forget_machine", lambda name: None)
        monkeypatch.setattr(worktrees.mutagen, "sync_terminate", lambda selector: None)

        _clean_worktree_boxes(
            [WorktreeBox(worktree_path=tmp_path / "a", record=stale)], "delete", require_removed=require_removed
        )

        assert deleted == expected_deleted
        assert devbox_config.load_worktree_boxes() == {str(tmp_path / "a"): adopted}


class TestReclaimedBytes:
    def test_sums_per_device_increase_and_clamps_negatives(self) -> None:
        before = {1: 1_000, 2: 5_000}
        after = {1: 3_000, 2: 4_000}  # device 1 freed 2000; device 2 went down (concurrent write)
        assert _reclaimed_bytes(before, after) == 2_000.0

    def test_unmeasurable_returns_negative(self) -> None:
        assert _reclaimed_bytes({}, {}) == -1.0


class TestExecute:
    @pytest.fixture(autouse=True)
    def no_busy_processes(self, monkeypatch) -> None:
        monkeypatch.setattr(worktrees, "_process_cwds", lambda: set())

    def test_worktree_entered_during_the_reap_is_kept(self, tmp_path, monkeypatch) -> None:
        first, second = tmp_path / "first", tmp_path / "second"
        (first / "src").mkdir(parents=True)
        (second / "src").mkdir(parents=True)
        snapshots = iter([set(), {(second / "src").resolve()}])
        monkeypatch.setattr(worktrees, "_process_cwds", lambda: next(snapshots))
        before_remove = Mock()

        reap = _execute(
            [
                Worktree(source="claude", path=path, registered=False, locked=False, branch="", last_activity=0.0)
                for path in (first, second)
            ],
            "full",
            tmp_path,
            before_remove=before_remove,
        )

        assert (reap.removed, reap.failed) == (1, 0)
        assert not first.exists()
        assert second.exists()
        assert [call.args[0].path for call in before_remove.call_args_list] == [first]

    @pytest.mark.parametrize(
        ("case", "expected_removed_failed"),
        [("removable", (1, 0)), ("repo_deep_inside", (0, 1)), ("tracked_during_prompt", (0, 0))],
    )
    def test_artifact_is_checked_again_just_before_removal(
        self, tmp_path, case: str, expected_removed_failed: tuple[int, int]
    ) -> None:
        worktree = _git_worktree(
            tmp_path / "wt", {".gitignore": "node_modules/\n", "node_modules/pkg/index.js": ""}, tracked=(".gitignore",)
        )
        node_modules = (worktree / "node_modules").resolve()
        if case == "repo_deep_inside":
            (node_modules / ".pnpm" / "pkg@1.0.0" / "node_modules" / "pkg" / "src" / ".git").mkdir(parents=True)
        wt = Worktree(source="claude", path=worktree, registered=True, locked=False, branch="", last_activity=0.0)
        wt.artifact_items = [node_modules]
        if case == "tracked_during_prompt":
            subprocess.run(["git", "add", "-f", "node_modules/pkg/index.js"], cwd=worktree, check=True)

        reap = _execute([wt], "deps", tmp_path)

        assert (reap.removed, reap.failed) == expected_removed_failed
        assert node_modules.exists() == (case != "removable")

    @pytest.mark.parametrize("read_only_go_module_cache", [True, False], ids=["read_only_tree", "already_removed"])
    def test_full_mode_counts_worktree_as_removed(self, tmp_path, read_only_go_module_cache) -> None:
        worktree = tmp_path / "wt"
        if read_only_go_module_cache:
            module = worktree / "mod" / "lib@v1.0.0"
            module.mkdir(parents=True)
            (module / "lib.go").write_text("package lib\n")
            module.chmod(0o555)
            module.parent.chmod(0o555)

        reap = _execute(
            [Worktree(source="claude", path=worktree, registered=False, locked=False, branch="", last_activity=0.0)],
            "full",
            tmp_path,
        )

        assert (reap.removed, reap.failed) == (1, 0)
        assert not worktree.exists()
