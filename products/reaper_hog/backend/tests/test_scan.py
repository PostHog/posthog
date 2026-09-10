import subprocess
from pathlib import Path

import pytest

from products.reaper_hog.backend.facade.enums import RootKind, ScoutName
from products.reaper_hog.backend.logic.artefacts import Hit, Note
from products.reaper_hog.backend.logic.scan import ScanRequest, run_scan
from products.reaper_hog.backend.logic.scouts.base import ScoutContext
from products.reaper_hog.backend.models import ReaperArtefact, ReaperInventory
from products.reaper_hog.backend.tests.conftest import PRODUCT_DATABASES


class StubScout:
    name = ScoutName.FLAGS

    def applies_to(self, scope: str) -> bool:
        return True

    def run(self, context: ScoutContext) -> list[Hit]:
        return [
            Hit(scout=self.name, root_kind=RootKind.FLAG, root="k", files=["a.py"], decisive=True, summary="dead"),
        ]


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    }
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env=env)
    (tmp_path / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "Init"], cwd=tmp_path, check=True, env=env)
    return tmp_path


class BrokenScout(StubScout):
    name = ScoutName.ARCHAEOLOGY

    def run(self, context: ScoutContext) -> list[Hit]:
        raise RuntimeError("personhog client not configured")


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_run_scan_records_clusters_and_a_summary_note(team, repo_path: Path) -> None:
    request = ScanRequest(team_id=team.id, repository="o/r", scope="flags", repo_path=repo_path)

    result = run_scan(request, scouts=(StubScout(), BrokenScout()))

    inventory = ReaperInventory.objects.get(id=result.inventory_id)
    assert inventory.status == "idle"
    assert inventory.last_scan_sha == result.head_sha
    assert result.hit_count == 1
    assert [draft.strong for draft in result.drafts] == [True]
    note = ReaperArtefact.objects.get(inventory=inventory, type="note")
    assert Note.model_validate_json(note.content).body == result.note
    assert "Strong candidates (harvestable): 1" in result.note
    assert "- `k` (flag, 1 files, scouts: flags)" in result.note
    assert result.failed_scouts == ("archaeology",)
    assert "Scouts that failed this run (their roots are missing above): archaeology." in result.note


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_run_scan_fails_when_every_scout_fails(team, repo_path: Path) -> None:
    request = ScanRequest(team_id=team.id, repository="o/r", scope="flags", repo_path=repo_path)

    with pytest.raises(RuntimeError, match="Every scout failed"):
        run_scan(request, scouts=(BrokenScout(),))

    assert ReaperInventory.objects.get(repository="o/r", scope="flags").status == "idle"
