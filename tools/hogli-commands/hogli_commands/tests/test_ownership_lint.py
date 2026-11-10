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
        ("path", "exit_code", "status"),
        [
            pytest.param("gap/test_new.py", 1, "warning", id="pytest_file_with_no_owner"),
            pytest.param("gap/New.test.tsx", 1, "warning", id="jest_file_with_no_owner"),
            pytest.param("owned/test_new.py", 0, "pass", id="test_with_an_owner"),
            pytest.param("gap/new.py", 0, "pass", id="file_that_is_not_a_test"),
        ],
    )
    def test_ci_fails_and_preflight_warns_on_a_new_test_with_no_owner(
        self, add: Add, path: str, exit_code: int, status: str
    ) -> None:
        add(path)

        result = CliRunner().invoke(ownership_lint.cmd_lint_test_owners, ["--against", "HEAD"])
        outcome = ownership_lint.check_test_owners(
            Scope(files=[path], changed=[path], merge_base="HEAD", committed_only=False)
        )

        assert result.exit_code == exit_code
        assert (path in result.output) == bool(exit_code)
        assert outcome[0] == status
        assert (path in outcome[1]) == bool(exit_code)

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
    def test_a_path_cannot_forge_a_workflow_command(self, add: Add, path: str) -> None:
        add(path)

        result = CliRunner().invoke(ownership_lint.cmd_lint_test_owners, ["--against", "HEAD"])

        assert result.exit_code == 1
        assert not any(line.startswith("::") for line in result.output.splitlines())
