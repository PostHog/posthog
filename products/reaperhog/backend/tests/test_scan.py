import subprocess
from pathlib import Path

import pytest

from products.reaperhog.backend.facade.enums import ClusterStatus, RootKind, ScoutName
from products.reaperhog.backend.logic.artefacts import Hit, Note
from products.reaperhog.backend.logic.scan import ScanRequest, run_scan
from products.reaperhog.backend.logic.scouts.base import ScoutContext, ScoutIncomplete
from products.reaperhog.backend.models import ReaperArtefact, ReaperCluster, ReaperInventory
from products.reaperhog.backend.tests.conftest import PRODUCT_DATABASES


class StubScout:
    name = ScoutName.FLAGS

    def __init__(self, roots: tuple[str, ...] = ("k",)) -> None:
        self.roots = roots

    def applies_to(self, scope: str) -> bool:
        return True

    def run(self, context: ScoutContext) -> list[Hit]:
        return [
            Hit(scout=self.name, root_kind=RootKind.FLAG, root=root, files=["a.py"], decisive=True, summary="dead")
            for root in self.roots
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
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/o/r.git"], cwd=tmp_path, check=True, env=env)
    return tmp_path


class BrokenScout(StubScout):
    name = ScoutName.ARCHAEOLOGY

    def run(self, context: ScoutContext) -> list[Hit]:
        raise RuntimeError("personhog client not configured")


class SkippingScout(StubScout):
    name = ScoutName.STATIC

    def run(self, context: ScoutContext) -> list[Hit]:
        raise ScoutIncomplete("knip produced no report", [])


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
    assert result.incomplete_scouts == ("archaeology",)
    assert "Scouts that did not finish this run (their roots are missing above): archaeology." in result.note


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
@pytest.mark.parametrize("second_scout", [BrokenScout, SkippingScout])
def test_run_scan_with_a_scout_that_did_not_finish_keeps_a_root_it_did_not_see(
    team, repo_path: Path, second_scout
) -> None:
    request = ScanRequest(team_id=team.id, repository="o/r", scope="flags", repo_path=repo_path)
    run_scan(request, scouts=(StubScout(),))

    run_scan(request, scouts=(StubScout(roots=()), second_scout()))

    assert ReaperCluster.objects.get(root="k").status == ClusterStatus.CANDIDATE


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_run_scan_fails_when_every_scout_fails(team, repo_path: Path) -> None:
    request = ScanRequest(team_id=team.id, repository="o/r", scope="flags", repo_path=repo_path)

    with pytest.raises(RuntimeError, match="No scout finished"):
        run_scan(request, scouts=(BrokenScout(),))

    assert ReaperInventory.objects.get(repository="o/r", scope="flags").status == "idle"


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_run_scan_refuses_a_checkout_it_cannot_match_to_the_repository(team, repo_path: Path, tmp_path: Path) -> None:
    subprocess.run(["git", "remote", "remove", "origin"], cwd=repo_path, check=True)
    request = ScanRequest(team_id=team.id, repository="o/r", scope="flags", repo_path=repo_path)

    with pytest.raises(RuntimeError, match="no GitHub origin"):
        run_scan(request, scouts=(StubScout(),))
