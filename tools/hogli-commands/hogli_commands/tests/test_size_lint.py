from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from hogli.cli import cli
from hogli_commands import change_detection, ci_preflight, size_lint
from hogli_commands.size_lint import CROSSED_AT, NOTE_AT, _findings, _merge_base

runner = CliRunner()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _write(repo: Path, path: str, lines: int) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x = 1\n" * lines)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _git(tmp_path, "init", "-q", "-b", "master")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    _write(tmp_path, "posthog/seed.py", 1)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    monkeypatch.setattr(size_lint, "REPO_ROOT", tmp_path)
    # File discovery reads the repo through its own module-level root.
    monkeypatch.setattr(change_detection, "REPO_ROOT", tmp_path)
    return tmp_path


def _commit_on_branch(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")


class TestSizeLint:
    @pytest.mark.parametrize(
        ("before", "after", "expected"),
        [
            pytest.param(CROSSED_AT - 100, CROSSED_AT + 100, [("posthog/big.py", True)], id="crossing_warns"),
            # The whole point of the crossed framing: touching a file that was already
            # over the line is not this change's doing, so it stays quiet.
            pytest.param(CROSSED_AT + 200, CROSSED_AT + 300, [], id="already_over_stays_quiet"),
            pytest.param(CROSSED_AT - 100, CROSSED_AT - 50, [], id="staying_under_is_quiet"),
            pytest.param(None, CROSSED_AT + 100, [("posthog/big.py", True)], id="new_file_over_the_line_warns"),
            pytest.param(NOTE_AT + 100, NOTE_AT + 200, [("posthog/big.py", False)], id="already_huge_gets_a_note"),
        ],
    )
    def test_only_this_change_s_crossings_warn(
        self, repo: Path, before: int | None, after: int, expected: list[tuple[str, bool]]
    ) -> None:
        if before is not None:
            _write(repo, "posthog/big.py", before)
            _commit_on_branch(repo)
        _git(repo, "checkout", "-qb", "feature")
        _write(repo, "posthog/big.py", after)
        _commit_on_branch(repo)

        findings = _findings(["posthog/big.py"], _merge_base(None))

        assert [(finding.file, finding.crossed) for finding in findings] == expected

    @pytest.mark.parametrize("commit_the_move", [True, False], ids=["committed", "staged"])
    def test_a_moved_file_is_not_a_new_one(self, repo: Path, commit_the_move: bool) -> None:
        # Nearly half of all crossings are moves. Reading the destination path at the
        # base gives nothing, so without rename detection a relocated file reads as
        # newly created and every product migration gets nudged. The staged case needs
        # the index as a second rename source, because there is no committed rename yet.
        _write(repo, "posthog/big.py", CROSSED_AT + 100)
        _commit_on_branch(repo)
        _git(repo, "checkout", "-qb", "feature")
        _git(repo, "mv", "posthog/big.py", "posthog/moved.py")
        if commit_the_move:
            _commit_on_branch(repo)

        findings = _findings(["posthog/moved.py"], _merge_base(None))

        assert findings == []

    def test_a_named_base_measures_committed_content(self, repo: Path) -> None:
        # Strict preflight scopes to the committed diff because a push carries only
        # commits, so an uncommitted edit must not move the reported size away from
        # what is about to be pushed.
        _git(repo, "checkout", "-qb", "feature")
        _write(repo, "posthog/big.py", CROSSED_AT + 100)
        _commit_on_branch(repo)
        _write(repo, "posthog/big.py", 10)

        from_worktree = _findings(["posthog/big.py"], _merge_base(None))
        from_head = _findings(["posthog/big.py"], _merge_base(None), rev="HEAD")

        assert from_worktree == []
        assert [finding.crossed for finding in from_head] == [True]

    def test_a_file_moved_twice_is_still_not_a_new_one(self, repo: Path) -> None:
        # A commit rename and a staged rename come back as two separate records, so one
        # lookup lands on the intermediate name, which does not exist at the base. That
        # reads as a new file and blames the move for a crossing it did not cause.
        _write(repo, "posthog/big.py", CROSSED_AT + 100)
        _commit_on_branch(repo)
        _git(repo, "checkout", "-qb", "feature")
        _git(repo, "mv", "posthog/big.py", "posthog/middle.py")
        _commit_on_branch(repo)
        _git(repo, "mv", "posthog/middle.py", "posthog/final.py")

        findings = _findings(["posthog/final.py"], _merge_base(None))

        assert findings == []

    def test_a_reused_pathname_does_not_join_two_files(self, repo: Path) -> None:
        # One rename frees a pathname and another takes it. The two records describe
        # different files, so resolving through the shared name would compare the large
        # file against the small one's baseline and invent a crossing.
        _write(repo, "posthog/big.py", CROSSED_AT + 100)
        _write(repo, "posthog/small.py", 1)
        _commit_on_branch(repo)
        _git(repo, "checkout", "-qb", "feature")
        _git(repo, "mv", "posthog/big.py", "posthog/final.py")
        _commit_on_branch(repo)
        _git(repo, "mv", "posthog/small.py", "posthog/big.py")

        findings = _findings(["posthog/final.py"], _merge_base(None))

        assert findings == []

    def test_at_most_one_note_for_files_that_were_already_huge(self, repo: Path) -> None:
        # Reporting every oversized file fires on most commits. One note keeps the
        # reading cost visible without burning context on a list.
        for name, lines in (("posthog/huge.py", NOTE_AT + 500), ("posthog/bigger.py", NOTE_AT + 900)):
            _write(repo, name, lines)
        _commit_on_branch(repo)
        _git(repo, "checkout", "-qb", "feature")
        _write(repo, "posthog/huge.py", NOTE_AT + 501)
        _write(repo, "posthog/bigger.py", NOTE_AT + 901)
        _commit_on_branch(repo)

        findings = _findings(["posthog/huge.py", "posthog/bigger.py"], _merge_base(None))

        assert [finding.file for finding in findings] == ["posthog/bigger.py"]

    def test_uncommitted_growth_is_reported_unless_the_run_is_scoped_to_commits(self, repo: Path) -> None:
        # Advisory preflight keeps the working tree in scope, so reading HEAD there would
        # hide a crossing the author just created. The pre-push run wants the opposite,
        # because only commits get pushed. The base is the same in both.
        _git(repo, "checkout", "-qb", "feature")
        _write(repo, "posthog/big.py", CROSSED_AT - 100)
        _commit_on_branch(repo)
        _write(repo, "posthog/big.py", CROSSED_AT + 100)

        worktree = runner.invoke(cli, ["lint:size", "--against", "master", "posthog/big.py"])
        commits = runner.invoke(cli, ["lint:size", "--against", "master", "--committed", "posthog/big.py"])

        assert "warning" in worktree.output
        assert "warning" not in commits.output

    def test_an_unresolvable_base_is_rejected_rather_than_disabling_the_check(self, repo: Path) -> None:
        # Explicit files bypass change detection, which is the code that normally rejects
        # a bad ref. Without its own check a typo would read as "no base" and silently
        # turn crossing detection off.
        _git(repo, "checkout", "-qb", "feature")
        _write(repo, "posthog/big.py", CROSSED_AT + 100)
        _commit_on_branch(repo)

        unresolvable = runner.invoke(cli, ["lint:size", "--against", "no-such-ref", "posthog/big.py"])
        assert unresolvable.exit_code != 0
        assert "no-such-ref" in unresolvable.output

        # A ref that resolves but shares no history fails the same way, because it also
        # leaves nothing to compare against.
        _git(repo, "checkout", "-q", "--orphan", "unrelated")
        _write(repo, "posthog/other.py", 1)
        _commit_on_branch(repo)
        _git(repo, "checkout", "-q", "feature")

        unrelated = runner.invoke(cli, ["lint:size", "--against", "unrelated", "posthog/big.py"])
        assert unrelated.exit_code != 0
        assert "unrelated" in unrelated.output

    def test_committed_mode_does_not_discover_uncommitted_work(self, repo: Path) -> None:
        # Discovery has to match the promise of the flag. Selecting a staged file and then
        # measuring it at HEAD, where it does not exist, would read as a silent skip.
        _git(repo, "checkout", "-qb", "feature")
        _write(repo, "posthog/staged.py", CROSSED_AT + 100)
        _git(repo, "add", "posthog/staged.py")

        result = runner.invoke(cli, ["lint:size", "--against", "master", "--committed"])

        # The count is the assertion: measuring the file at HEAD would also produce no
        # finding, so only the number of files selected separates the two behaviors.
        assert result.exit_code == 0
        assert "0 file(s) checked" in result.output

    def test_cli_reports_findings_without_failing(self, repo: Path, tmp_path: Path) -> None:
        # The check is advisory, and preflight reads a soft check as a warning only when
        # it exits 0 with output on stdout.
        _git(repo, "checkout", "-qb", "feature")
        _write(repo, "posthog/big.py", CROSSED_AT + 100)
        _commit_on_branch(repo)
        report_path = tmp_path / "findings.json"

        result = runner.invoke(cli, ["lint:size", "posthog/big.py", "--report", str(report_path)])

        assert result.exit_code == 0
        assert "warning" in result.output
        assert "posthog/big.py" in report_path.read_text()

    def test_out_of_scope_and_generated_files_are_skipped(self, repo: Path) -> None:
        _git(repo, "checkout", "-qb", "feature")
        for name in ("posthog/schema.py", "products/desktop/huge.ts", "tools/thing.py"):
            _write(repo, name, NOTE_AT + 900)
        _commit_on_branch(repo)

        result = runner.invoke(cli, ["lint:size", "posthog/schema.py", "products/desktop/huge.ts", "tools/thing.py"])

        assert result.exit_code == 0
        assert "0 file(s) checked" in result.output


class TestPreflightForwardsDiffScope:
    @pytest.mark.parametrize(
        ("against", "strict", "expected"),
        [
            # No explicit base: the child repeats change detection's own origin/master
            # then master fallback. Forwarding a default would pin it to a ref a clone
            # may not have, and the check would silently find nothing.
            pytest.param(None, False, [], id="default_base_stays_with_the_child"),
            pytest.param(None, True, ["--committed"], id="strict_measures_commits"),
            pytest.param("abc123", True, ["--against", "abc123", "--committed"], id="explicit_base_forwarded"),
        ],
    )
    def test_only_an_explicit_base_is_forwarded(self, against: str | None, strict: bool, expected: list[str]) -> None:
        check = ci_preflight.DiffCheck(
            key="size",
            label="file size",
            triggers=["posthog/*.py"],
            verify=["hogli", "lint:size"],
            takes_files=True,
            takes_diff_scope=True,
            soft=True,
        )
        check.matched = ["posthog/api/team.py"]

        with (
            patch.object(ci_preflight.shutil, "which", return_value="/usr/bin/hogli"),
            patch.object(
                ci_preflight.subprocess, "run", return_value=MagicMock(returncode=0, stdout="", stderr="")
            ) as run,
        ):
            ci_preflight._run_diff_check(check, False, against, strict)

        command = run.call_args[0][0]
        assert command[:2] == ["hogli", "lint:size"]
        assert command[2:-1] == expected
        assert command[-1] == "posthog/api/team.py"

    def test_the_registered_size_check_opts_into_diff_scope(self) -> None:
        registered = next(check for check in ci_preflight.DIFF_CHECKS if check.key == "size")
        assert registered.takes_diff_scope
