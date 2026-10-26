from __future__ import annotations

import subprocess
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
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "owners.yaml").write_text(OWNERS_YAML)
    for path in ("team/test_a.py", "person/test_b.py", "nobody/test_c.py", "by_design/test_d.py", "helpers/util.py"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("def test_x():\n    pass\n")
    (tmp_path / ownership_lint.BASELINE).parent.mkdir(parents=True)
    (tmp_path / ownership_lint.BASELINE).write_text("nobody\nperson\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init")
    monkeypatch.setattr(ownership_lint, "REPO_ROOT", tmp_path)
    return tmp_path


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)


def _check(*files: str) -> tuple[str, str]:
    return ownership_lint.check_test_owners(
        Scope(files=list(files), changed=list(files), merge_base="HEAD", committed_only=False)
    )


class TestCheckTestOwners:
    @pytest.mark.parametrize(
        ("baseline", "status", "named"),
        [
            pytest.param("nobody\nperson\n", "pass", None, id="baseline_matches"),
            pytest.param("nobody\n", "fail", "person holds tests", id="person_only_owner_is_a_new_gap"),
            pytest.param("nobody\nperson\nteam\n", "fail", "team has no unowned tests left", id="stale_entry"),
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
        ("path", "status"),
        [
            pytest.param("nobody/test_c.py", "pass", id="edit_to_existing_test_skips_the_scan"),
            pytest.param("elsewhere/test_new.py", "fail", id="added_test_runs_the_scan"),
        ],
    )
    def test_scans_only_when_a_test_file_is_added_or_removed(self, repo: Path, path: str, status: str) -> None:
        (repo / path).parent.mkdir(exist_ok=True)
        (repo / path).write_text("def test_y():\n    pass\n")
        _git(repo, "add", path)

        assert _check(path)[0] == status
