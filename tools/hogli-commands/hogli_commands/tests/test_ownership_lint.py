from __future__ import annotations

from pathlib import Path

import pytest

from click.testing import CliRunner
from hogli_commands import ownership_lint

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
    for path in ("team/test_a.py", "person/test_b.py", "nobody/test_c.py", "by_design/test_d.py", "nobody/helper.py"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("def test_x():\n    pass\n")
    monkeypatch.setattr(ownership_lint, "REPO_ROOT", tmp_path)
    return tmp_path


class TestOwnershipLint:
    @pytest.mark.parametrize(
        ("path", "warned"),
        [
            pytest.param("team/test_a.py", False, id="team_owner_is_quiet"),
            pytest.param("person/test_b.py", True, id="person_only_warns"),
            pytest.param("nobody/test_c.py", True, id="no_owner_warns"),
            pytest.param("by_design/test_d.py", False, id="unowned_by_design_is_quiet"),
            pytest.param("nobody/helper.py", False, id="non_test_file_is_skipped"),
        ],
    )
    def test_warns_only_for_tests_without_a_team(self, repo: Path, path: str, warned: bool) -> None:
        result = CliRunner().invoke(ownership_lint.cmd_lint_test_owners, [path])

        assert result.exit_code == 0
        assert (f"{path}:1:1: warning:" in result.stdout) is warned
