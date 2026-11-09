from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from click.testing import CliRunner
from hogli_commands import ownership_lint, size_lint
from hogli_commands.preflight_checks import Scope

OWNERS_YAML = """\
version: 1
owners: []
rules:
  - match: '/team/'
    owners: team-billing
  - match: '/person/'
    owners: '@alice'
  - match: '/by_design/'
    owners: null
"""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git: Callable[..., str]) -> Path:
    (tmp_path / "owners.yaml").write_text(OWNERS_YAML)
    for path in ("team/test_a.py", "person/test_b.py", "nobody/test_c.py", "by_design/test_d.py", "helpers/util.py"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("def test_x():\n    pass\n")
    (tmp_path / ownership_lint.BASELINE).parent.mkdir(parents=True)
    (tmp_path / ownership_lint.BASELINE).write_text("nobody\nperson\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.setattr(ownership_lint, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(size_lint, "REPO_ROOT", tmp_path)
    return tmp_path


def _check(*files: str, committed_only: bool = False) -> tuple[str, str]:
    return ownership_lint.check_test_owners(
        Scope(files=list(files), changed=list(files), merge_base="HEAD", committed_only=committed_only)
    )


class TestCheckTestOwners:
    @pytest.mark.parametrize(
        ("baseline", "status", "named"),
        [
            pytest.param("nobody\nperson\n", "pass", None, id="baseline_matches"),
            pytest.param("nobody\n", "warning", "person holds tests", id="person_only_owner_is_a_new_gap"),
            pytest.param("nobody\nperson\nteam\n", "warning", "team has no unowned tests left", id="stale_entry"),
        ],
    )
    def test_compares_unowned_test_directories_with_the_baseline(
        self, repo: Path, baseline: str, status: str, named: str | None
    ) -> None:
        (repo / ownership_lint.BASELINE).write_text(baseline)

        result_status, detail = _check(str(ownership_lint.BASELINE))

        assert result_status == status
        assert named is None or named in detail

    @pytest.mark.parametrize(
        ("path", "committed_only", "status"),
        [
            pytest.param("helpers/test_fixtures/util.py", False, "pass", id="non_test_file_skips_the_scan"),
            pytest.param("elsewhere/test_new.py", False, "warning", id="untracked_test_is_scanned_locally"),
            pytest.param("elsewhere/test_new.py", True, "pass", id="untracked_test_is_not_in_the_push"),
        ],
    )
    def test_scans_the_tree_the_scope_names(self, repo: Path, path: str, committed_only: bool, status: str) -> None:
        (repo / ownership_lint.BASELINE).write_text("nobody\n")
        (repo / path).parent.mkdir(exist_ok=True)
        (repo / path).write_text("def test_y():\n    pass\n")

        assert _check(path, committed_only=committed_only)[0] == status

    @pytest.mark.parametrize(
        ("committed_only", "status"),
        [
            pytest.param(True, "pass", id="strict_reads_head"),
            pytest.param(False, "warning", id="local_reads_the_working_tree"),
        ],
    )
    def test_an_uncommitted_owners_yaml_counts_only_locally(
        self, repo: Path, committed_only: bool, status: str
    ) -> None:
        (repo / "owners.yaml").write_text(OWNERS_YAML + "  - match: '/nobody/'\n    owners: team-billing\n")

        result_status, detail = _check("owners.yaml", committed_only=committed_only)

        assert result_status == status
        assert status == "pass" or "nobody has no unowned tests left" in detail


class TestLintTestOwners:
    @pytest.mark.parametrize(
        ("path", "moved_from", "owners_yaml", "exit_code"),
        [
            pytest.param("nobody/test_new.py", None, OWNERS_YAML, 1, id="new_test_in_a_baseline_directory_fails"),
            pytest.param("team/test_new.py", None, OWNERS_YAML, 0, id="new_test_with_a_team_owner_passes"),
            pytest.param("nobody/test_renamed.py", "nobody/test_c.py", OWNERS_YAML, 0, id="moved_unowned_test_passes"),
            pytest.param(
                "nobody/test_moved.py", "team/test_a.py", OWNERS_YAML, 1, id="test_moved_out_of_a_team_path_fails"
            ),
            pytest.param(
                "nobody/test_moved.py",
                "team/test_a.py",
                "version: 1\nowners: []\nrules: []\n",
                1,
                id="dropping_the_team_rule_with_the_move_still_fails",
            ),
        ],
    )
    def test_checks_each_test_file_the_branch_adds(
        self,
        repo: Path,
        git: Callable[..., str],
        path: str,
        moved_from: str | None,
        owners_yaml: str,
        exit_code: int,
    ) -> None:
        if moved_from:
            git(repo, "mv", moved_from, path)
        else:
            (repo / path).write_text("def test_y():\n    pass\n")
        (repo / "owners.yaml").write_text(owners_yaml)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "add a test")

        summary = repo / "step_summary.md"

        result = CliRunner().invoke(
            ownership_lint.cmd_lint_test_owners,
            ["--against", "HEAD~1", "--committed"],
            env={"GITHUB_ACTIONS": None, "GITHUB_STEP_SUMMARY": str(summary)},
        )

        assert result.exit_code == exit_code
        assert exit_code == 0 or f"{path} is a new test that no team owns" in result.output
        assert exit_code == 0 or f"\n{path}\n" in summary.read_text()

    def test_a_path_cannot_forge_a_workflow_command(self, repo: Path, git: Callable[..., str]) -> None:
        (repo / "nobody/test_x\n::error::forged.py").write_text("def test_y():\n    pass\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "add a test")
        summary = repo / "step_summary.md"

        result = CliRunner().invoke(
            ownership_lint.cmd_lint_test_owners,
            ["--against", "HEAD~1", "--committed"],
            env={"GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": str(summary)},
        )

        assert result.exit_code == 1
        assert not any(line.startswith("::error") for line in (result.output + summary.read_text()).splitlines())
