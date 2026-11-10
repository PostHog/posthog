from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from click.testing import CliRunner
from hogli_commands import ownership_lint
from hogli_commands.preflight_checks import Scope

OWNERS_YAML = """\
version: 1
owners: []
rules:
  - match: '/owned/'
    owners: team-a
"""

Add = Callable[[str], None]


@pytest.fixture
def add(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git: Callable[..., str]) -> Add:
    (tmp_path / "owners.yaml").write_text(OWNERS_YAML)
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.setattr(ownership_lint, "REPO_ROOT", tmp_path)

    def add_file(path: str) -> None:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("")
        git(tmp_path, "add", "-A")

    return add_file


class TestLintTestOwners:
    @pytest.mark.parametrize(
        ("path", "exit_code"),
        [
            pytest.param("gap/test_new.py", 1, id="pytest_file_with_no_owner"),
            pytest.param("gap/New.test.tsx", 1, id="jest_file_with_no_owner"),
            pytest.param("owned/test_new.py", 0, id="test_with_an_owner"),
            pytest.param("gap/new.py", 0, id="file_that_is_not_a_test"),
        ],
    )
    def test_fails_only_on_a_new_test_with_no_owner(
        self, add: Add, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str, exit_code: int
    ) -> None:
        summary = tmp_path.parent / f"{tmp_path.name}-summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        add(path)

        result = CliRunner().invoke(ownership_lint.cmd_lint_test_owners, ["--against", "HEAD"])

        assert result.exit_code == exit_code
        assert (path in result.output) == bool(exit_code)
        assert summary.exists() == bool(exit_code)
        assert not exit_code or path in summary.read_text()

    def test_committed_reads_head_and_not_the_working_tree(self, add: Add) -> None:
        add("gap/test_new.py")

        result = CliRunner().invoke(ownership_lint.cmd_lint_test_owners, ["--against", "HEAD", "--committed"])

        assert result.exit_code == 0

    @pytest.mark.parametrize(
        "path",
        [
            pytest.param("gap/test_x\n::error::forged.py", id="after_a_newline"),
            pytest.param("::error::forged/test_x.py", id="at_the_start_of_the_path"),
        ],
    )
    def test_a_path_cannot_forge_a_workflow_command(
        self, add: Add, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
    ) -> None:
        summary = tmp_path.parent / f"{tmp_path.name}-summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        add(path)

        result = CliRunner().invoke(ownership_lint.cmd_lint_test_owners, ["--against", "HEAD"])

        assert result.exit_code == 1
        assert not any(line.startswith("::") for line in result.output.splitlines())
        assert not any(line.startswith("::") for line in summary.read_text().splitlines())


class TestCheckUnownedPaths:
    @pytest.mark.parametrize(
        ("path", "status", "named"),
        [
            pytest.param(
                "gap/test_new.py", "warning", "CI fails on a new test with no owner: gap/test_new.py", id="test"
            ),
            pytest.param("gap/new.py", "warning", "no owner for gap/new.py", id="file_that_is_not_a_test"),
            pytest.param("owned/test_new.py", "pass", "every new file has an owner", id="owned"),
        ],
    )
    def test_warns_and_never_blocks(self, add: Add, path: str, status: str, named: str) -> None:
        add(path)

        outcome = ownership_lint.check_unowned_paths(
            Scope(files=[path], changed=[path], merge_base="HEAD", committed_only=False)
        )

        assert outcome[0] == status
        assert named in outcome[1]
