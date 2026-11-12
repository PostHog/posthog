from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from unittest.mock import patch

import owners_yaml
from click.testing import CliRunner
from hogli_commands import ci_preflight, ownership_lint
from hogli_commands.preflight_checks import Scope

OWNERS_YAML = """\
version: 1
owners: []
rules:
  - match: '/owned/'
    owners: team-a
  - match: '/person/'
    owners: '@alice'
  - match: '/exempt/'
    owners: null
"""

Add = Callable[..., None]


@pytest.fixture
def add(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git: Callable[..., str]) -> Add:
    def add_file(path: str, text: str = "") -> None:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
        git(tmp_path, "add", "-A")

    git(tmp_path, "init", "-q")
    add_file("owners.yaml", OWNERS_YAML)
    add_file("owned/test_old.py")
    git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.setattr(ownership_lint, "REPO_ROOT", tmp_path)
    return add_file


class TestLintTestOwners:
    @pytest.mark.parametrize(
        ("path", "text", "left_with_no_team"),
        [
            pytest.param("gap/test_new.py", "", "gap/test_new.py", id="pytest_file_with_no_owner"),
            pytest.param("gap/New.test.tsx", "", "gap/New.test.tsx", id="jest_file_with_no_owner"),
            pytest.param("person/test_new.py", "", "person/test_new.py", id="test_that_only_a_person_owns"),
            pytest.param("owners.yaml", "version: 1\nowners: []\n", "owned/test_old.py", id="rule_removed"),
            pytest.param("exempt/test_new.py", "", None, id="test_under_owners_null"),
            pytest.param("owned/test_new.py", "", None, id="test_with_an_owner"),
            pytest.param("gap/new.py", "", None, id="file_that_is_not_a_test"),
        ],
    )
    def test_ci_and_preflight_fail_on_a_test_left_with_no_team_owner(
        self, add: Add, path: str, text: str, left_with_no_team: str | None
    ) -> None:
        add(path, text)

        result = CliRunner().invoke(ownership_lint.cmd_lint_test_owners, ["--against", "HEAD"])
        outcome = ownership_lint.check_test_owners(
            Scope(files=[path], changed=[path], merge_base="HEAD", committed_only=False)
        )

        assert result.exit_code == (1 if left_with_no_team else 0)
        assert outcome[0] == ("fail" if left_with_no_team else "pass")
        assert left_with_no_team is None or (left_with_no_team in result.output and left_with_no_team in outcome[1])

    def test_committed_reads_head_and_not_the_working_tree(self, add: Add) -> None:
        add("gap/test_new.py")

        result = CliRunner().invoke(ownership_lint.cmd_lint_test_owners, ["--against", "HEAD", "--committed"])

        assert result.exit_code == 0

    @pytest.mark.parametrize(
        ("installed_package_has_the_check", "exit_code", "shown"),
        [
            pytest.param(True, 1, "gap/test_new.py", id="blocks_a_committed_test_with_no_team_owner"),
            pytest.param(False, 0, "check could not run (ImportError", id="skips_when_the_installed_package_is_older"),
        ],
    )
    def test_the_pre_push_hook(
        self,
        add: Add,
        git: Callable[..., str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        installed_package_has_the_check: bool,
        exit_code: int,
        shown: str,
    ) -> None:
        add("gap/test_new.py")
        git(tmp_path, "commit", "-q", "-m", "change")
        (tmp_path / "gap/test_new.py").unlink()
        if not installed_package_has_the_check:
            monkeypatch.delattr(owners_yaml, "newly_unowned")
        registered = [check for check in ci_preflight.DIFF_CHECKS if check.key == "test-owners"]

        with patch.multiple(
            ci_preflight,
            DIFF_CHECKS=registered,
            changed_files=lambda *args, **kwargs: ["gap/test_new.py"],
            _merge_base=lambda against: "HEAD~1",
            _fetch_master=lambda: None,
            _staleness=lambda files: ("pass", "", {}),
            check_stack_depth=lambda: ("skipped", ""),
            _emit_telemetry=lambda summary: None,
        ):
            result = CliRunner().invoke(ci_preflight.ci_preflight, ["--strict"])

        assert result.exit_code == exit_code
        assert shown in result.output

    @pytest.mark.parametrize(
        "path",
        [
            pytest.param("gap/test_x\n::error::forged.py", id="after_a_newline"),
            pytest.param("::error::forged/test_x.py", id="at_the_start_of_the_path"),
            pytest.param("gap/##[error]forged/test_x.py", id="in_the_form_that_counts_anywhere_in_a_line"),
        ],
    )
    def test_a_path_cannot_forge_a_workflow_command(self, add: Add, path: str) -> None:
        add(path)

        result = CliRunner().invoke(ownership_lint.cmd_lint_test_owners, ["--against", "HEAD"])

        assert result.exit_code == 1
        assert not any(line.startswith("::") or "##[" in line for line in result.output.splitlines())
