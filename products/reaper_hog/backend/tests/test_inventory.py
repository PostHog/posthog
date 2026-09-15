from datetime import UTC, datetime

import pytest

from products.reaper_hog.backend.facade.enums import ClusterStatus, RootKind, ScoutName
from products.reaper_hog.backend.logic.artefacts import Hit
from products.reaper_hog.backend.logic.converge import converge
from products.reaper_hog.backend.logic.inventory import record_scan, upsert_inventory
from products.reaper_hog.backend.models import ReaperArtefact, ReaperCluster
from products.reaper_hog.backend.tests.conftest import PRODUCT_DATABASES

NOW = datetime(2026, 8, 30, tzinfo=UTC)


def _drafts(*roots: str, files: list[str] | None = None):
    return converge(
        Hit(scout=ScoutName.FLAGS, root_kind=RootKind.FLAG, root=root, files=files or ["a.py"], summary="s")
        for root in roots
    )


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRecordScan:
    def test_first_scan_creates_candidates_with_hit_artefacts(self, team):
        inventory = upsert_inventory(team_id=team.id, repository="o/r", scope="flags")

        outcome = record_scan(inventory, _drafts("a", "b"), head_sha="abc", now=NOW)

        assert (outcome.created, outcome.refreshed, outcome.vanished) == (2, 0, 0)
        clusters = {c.root: c for c in ReaperCluster.objects.filter(inventory=inventory)}
        assert {c.status for c in clusters.values()} == {ClusterStatus.CANDIDATE}
        assert ReaperArtefact.objects.filter(cluster=clusters["a"], type="hit").count() == 1
        inventory.refresh_from_db()
        assert (inventory.run_count, inventory.last_scan_sha) == (1, "abc")

    @pytest.mark.parametrize(
        "status,files_changed,expected",
        [
            (ClusterStatus.CANDIDATE, False, ClusterStatus.CANDIDATE),
            (ClusterStatus.DECLINED, False, ClusterStatus.DECLINED),
            (ClusterStatus.DECLINED, True, ClusterStatus.CANDIDATE),
            (ClusterStatus.VANISHED, False, ClusterStatus.CANDIDATE),
            (ClusterStatus.REAPED, True, ClusterStatus.REAPED),
        ],
    )
    def test_rescan_of_a_present_root(self, team, status, files_changed, expected):
        inventory = upsert_inventory(team_id=team.id, repository="o/r", scope="flags")
        record_scan(inventory, _drafts("a"), head_sha="abc", now=NOW)
        ReaperCluster.objects.filter(inventory=inventory).update(status=status)

        record_scan(inventory, _drafts("a", files=["b.py"] if files_changed else None), head_sha="def", now=NOW)

        assert ReaperCluster.objects.get(inventory=inventory, root="a").status == expected

    @pytest.mark.parametrize(
        "status,expected",
        [
            (ClusterStatus.CANDIDATE, ClusterStatus.VANISHED),
            (ClusterStatus.DEAD, ClusterStatus.VANISHED),
            (ClusterStatus.DECLINED, ClusterStatus.VANISHED),
            (ClusterStatus.REAPED, ClusterStatus.REAPED),
            (ClusterStatus.BURIED, ClusterStatus.BURIED),
        ],
    )
    def test_rescan_of_an_absent_root(self, team, status, expected):
        inventory = upsert_inventory(team_id=team.id, repository="o/r", scope="flags")
        record_scan(inventory, _drafts("a"), head_sha="abc", now=NOW)
        ReaperCluster.objects.filter(inventory=inventory).update(status=status)

        outcome = record_scan(inventory, [], head_sha="def", now=NOW)

        assert ReaperCluster.objects.get(inventory=inventory, root="a").status == expected
        assert outcome.vanished == (1 if expected == ClusterStatus.VANISHED else 0)
