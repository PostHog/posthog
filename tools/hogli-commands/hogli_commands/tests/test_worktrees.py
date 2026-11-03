from __future__ import annotations

import math
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

import click
from hogli_commands import worktrees
from hogli_commands.devbox import config as devbox_config
from hogli_commands.worktrees import (
    Worktree,
    WorktreeBox,
    _belongs_to_repo,
    _boxes_of_removed_worktrees,
    _clean_worktree_boxes,
    _collect_deps_items,
    _compute_git_state,
    _discover_root_worktrees,
    _du_sizes,
    _execute,
    _include_orphans,
    _is_under,
    _match_worktree_boxes,
    _parse_cutoff,
    _reclaimed_bytes,
    _registered_worktrees,
    _resolve_box_action,
    _resolve_orphan_policy,
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


# Frozen reference clock (2023-11-14T22:13:20Z) for deterministic cutoff math.
_NOW = 1_700_000_000.0


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


class TestCollectDepsItems:
    def test_never_escapes_worktree_via_symlinked_parent(self, tmp_path) -> None:
        worktree = tmp_path / "wt"
        (worktree / "node_modules").mkdir(parents=True)

        # `frontend` symlinked to shared external storage that has its own dist/.
        external = tmp_path / "external"
        (external / "dist").mkdir(parents=True)
        (worktree / "frontend").symlink_to(external, target_is_directory=True)

        items = _collect_deps_items(worktree)
        worktree_resolved = worktree.resolve()

        # The real node_modules is collected; nothing resolves outside the worktree.
        assert (worktree / "node_modules").resolve() in items
        assert all(_is_under(item, worktree_resolved) for item in items)
        assert (external / "dist").resolve() not in items


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
            ("admin-dir-reused", None, True),
            ("other-repo", None, False),
        ],
        ids=[
            "removed",
            "removed-source-selected",
            "source-not-selected",
            "moved-or-unmounted",
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
        if case in ("moved", "admin-dir-reused"):
            admin.mkdir()
        worktree_id = devbox_config.ensure_worktree_id(admin) if case == "moved" else "id-of-the-removed-worktree"
        record = _box("devbox-test-user-feature", git_dir=admin, worktree_id=worktree_id)
        registry = {str(repo / ".claude" / "worktrees" / "feature"): record}

        boxes = _boxes_of_removed_worktrees(registry, repo, common, sources)

        expected = [WorktreeBox(worktree_path=repo / ".claude" / "worktrees" / "feature", record=record)]
        assert boxes == (expected if pending else [])

    @pytest.mark.parametrize(
        ("action", "status", "live_id", "last_used_at", "expected_calls"),
        [
            ("delete", "running", "id-a", None, [("delete", "devbox-test-user-a")]),
            ("stop", "running", "id-a", None, [("stop", "devbox-test-user-a")]),
            ("stop", "stopped", "id-a", None, []),
            ("delete", "running", "id-recreated", None, []),
            ("delete", "running", "id-a", "2026-01-01T00:00:00.123456789Z", [("delete", "devbox-test-user-a")]),
            ("delete", "running", "id-a", "2026-03-01T00:00:00Z", []),
            ("delete", "running", "id-a", "", []),
        ],
        ids=[
            "delete",
            "stop-running",
            "stop-already-stopped",
            "recreated-box-left-alone",
            "idle-past-cutoff",
            "used-after-cutoff-kept",
            "unknown-last-use-kept",
        ],
    )
    def test_acts_on_existing_box_and_forgets_it(
        self, tmp_path, monkeypatch, registry_path, action, status, live_id, last_used_at, expected_calls
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
        box_a, box_b = _box("devbox-test-user-a", workspace_id="id-a"), _box("devbox-test-user-b")
        devbox_config.record_worktree_box(tmp_path / "a", box_a)
        devbox_config.record_worktree_box(tmp_path / "b", box_b)

        _clean_worktree_boxes(
            [
                WorktreeBox(worktree_path=tmp_path / "a", record=box_a),
                WorktreeBox(worktree_path=tmp_path / "b", record=box_b),
            ],
            action,
            **({} if last_used_at is None else {"idle_before": datetime(2026, 2, 1, tzinfo=UTC).timestamp()}),
        )

        assert calls == expected_calls
        acted = live_id == box_a.workspace_id and (last_used_at is None or bool(expected_calls))
        assert terminated == ([worktrees.mutagen.workspace_label_selector("devbox-test-user-a")] if acted else [])
        kept = live_id == box_a.workspace_id and not acted
        assert devbox_config.load_worktree_boxes() == ({str(tmp_path / "a"): box_a} if kept else {})

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


class TestReclaimedBytes:
    def test_sums_per_device_increase_and_clamps_negatives(self) -> None:
        before = {1: 1_000, 2: 5_000}
        after = {1: 3_000, 2: 4_000}  # device 1 freed 2000; device 2 went down (concurrent write)
        assert _reclaimed_bytes(before, after) == 2_000.0

    def test_unmeasurable_returns_negative(self) -> None:
        assert _reclaimed_bytes({}, {}) == -1.0


class TestExecute:
    @pytest.mark.parametrize("read_only_go_module_cache", [True, False], ids=["read_only_tree", "already_removed"])
    def test_full_mode_counts_worktree_as_removed(self, tmp_path, read_only_go_module_cache) -> None:
        worktree = tmp_path / "wt"
        if read_only_go_module_cache:
            module = worktree / "mod" / "lib@v1.0.0"
            module.mkdir(parents=True)
            (module / "lib.go").write_text("package lib\n")
            module.chmod(0o555)
            module.parent.chmod(0o555)

        _, removed, failed = _execute(
            [Worktree(source="claude", path=worktree, registered=False, locked=False, branch="", last_activity=0.0)],
            "full",
            tmp_path,
        )

        assert (removed, failed) == (1, 0)
        assert not worktree.exists()


class TestDuSizes:
    def test_parses_per_path_and_skips_garbage(self, tmp_path, monkeypatch) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()

        stdout = f"4\t{a}\n\nnot-a-number\t/whatever\n8\t{b}\n"
        monkeypatch.setattr(
            "hogli_commands.worktrees.subprocess.run",
            lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=1, stdout=stdout, stderr=""),
        )

        sizes = _du_sizes([a, b])
        assert sizes == {str(a): 4 * 1024.0, str(b): 8 * 1024.0}

    def test_no_existing_paths_returns_empty(self, tmp_path) -> None:
        assert _du_sizes([tmp_path / "missing"]) == {}
