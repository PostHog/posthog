from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from click.testing import CliRunner
from hogli.cli import cli
from hogli_commands import size_lint
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

    def test_a_moved_file_is_not_a_new_one(self, repo: Path) -> None:
        # Nearly half of all crossings are moves. Reading the destination path at the
        # base gives nothing, so without rename detection a relocated file reads as
        # newly created and every product migration gets nudged.
        _write(repo, "posthog/big.py", CROSSED_AT + 100)
        _commit_on_branch(repo)
        _git(repo, "checkout", "-qb", "feature")
        _git(repo, "mv", "posthog/big.py", "posthog/moved.py")
        _commit_on_branch(repo)

        findings = _findings(["posthog/moved.py"], _merge_base(None))

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
