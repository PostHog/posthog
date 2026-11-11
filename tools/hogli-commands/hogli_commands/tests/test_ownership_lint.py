from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from hogli_commands import ownership_lint
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
    monkeypatch.setattr(ownership_lint, "BLOCKING_FROM", date.min)
    return tmp_path


def _check(*files: str, committed_only: bool = False) -> tuple[str, str]:
    return ownership_lint.check_test_owners(
        Scope(files=list(files), changed=list(files), merge_base="HEAD", committed_only=committed_only)
    )


class TestCheckTestOwners:
    @pytest.mark.parametrize(
        ("baseline", "blocking_from", "status", "named"),
        [
            pytest.param("nobody\nperson\n", date.min, "pass", None, id="baseline_matches"),
            pytest.param("nobody\n", date.min, "fail", "person holds tests", id="person_only_owner_is_a_new_gap"),
            pytest.param("nobody\n", date.max, "warning", "not blocking until", id="new_gap_warns_in_the_grace_period"),
            pytest.param(
                "nobody\nperson\nteam\n",
                date.max,
                "fail",
                "team has no unowned tests left",
                id="stale_entry_fails_in_the_grace_period",
            ),
        ],
    )
    def test_compares_unowned_test_directories_with_the_baseline(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        baseline: str,
        blocking_from: date,
        status: str,
        named: str | None,
    ) -> None:
        monkeypatch.setattr(ownership_lint, "BLOCKING_FROM", blocking_from)
        (repo / ownership_lint.BASELINE).write_text(baseline)

        result_status, detail = _check(str(ownership_lint.BASELINE))

        assert result_status == status
        assert named is None or named in detail

    @pytest.mark.parametrize(
        ("path", "committed_only", "status"),
        [
            pytest.param("helpers/test_fixtures/util.py", False, "pass", id="non_test_file_skips_the_scan"),
            pytest.param("elsewhere/test_new.py", False, "fail", id="untracked_test_is_scanned_locally"),
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
            pytest.param(False, "fail", id="local_reads_the_working_tree"),
        ],
    )
    def test_an_uncommitted_owners_yaml_counts_only_locally(
        self, repo: Path, committed_only: bool, status: str
    ) -> None:
        (repo / "owners.yaml").write_text(OWNERS_YAML + "  - match: '/nobody/'\n    owners: team-billing\n")

        result_status, detail = _check("owners.yaml", committed_only=committed_only)

        assert result_status == status
        assert status == "pass" or "nobody has no unowned tests left" in detail
