from datetime import UTC, datetime
from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from products.reaper_hog.backend.facade.enums import ClusterRank, ClusterStatus, Confidence, RootKind, ScoutName
from products.reaper_hog.backend.logic.artefacts import Hit, SearchRun, Verdict, VerdictRecord
from products.reaper_hog.backend.logic.constants import MAX_FILES_PER_PR
from products.reaper_hog.backend.logic.converge import converge
from products.reaper_hog.backend.logic.github import PullRequestState, parse_pr_number
from products.reaper_hog.backend.logic.harvest import (
    HarvestCandidate,
    HarvestRequest,
    dispatch_harvest,
    render_pr_body,
    select_harvest,
    sync_harvest,
)
from products.reaper_hog.backend.logic.inventory import record_scan, upsert_inventory
from products.reaper_hog.backend.logic.verification import ClusterView
from products.reaper_hog.backend.models import ReaperArtefact, ReaperCluster
from products.reaper_hog.backend.tests.conftest import PRODUCT_DATABASES

_MODULE = "products.reaper_hog.backend.logic.harvest"
NOW = datetime(2026, 8, 30, tzinfo=UTC)


def _hit(root: str) -> Hit:
    return Hit(
        scout=ScoutName.EXPERIMENTS,
        root_kind=RootKind.FLAG,
        root=root,
        files=["a.py"],
        decisive=True,
        summary="Experiment lost",
        evidence={"conclusion": "lost", "end_date": "2026-04-13"},
    )


def _verdict(*, files: int = 2) -> Verdict:
    return Verdict(
        is_dead=True,
        confidence=Confidence.HIGH,
        files_to_delete=[f"f{i}.py" for i in range(files)],
        deletion_plan="Delete the flag check in a.py",
        searches=[SearchRun(purpose="key", command="rg -F 'k'", hits=0)],
        argumentation="- **Checked:** a.py:1",
        could_not_prove=["whether docs mention it"],
    )


def _candidate(root: str, *, rank: ClusterRank = ClusterRank.STRONG, files: int = 2) -> HarvestCandidate:
    view = ClusterView(
        id=uuid4(), hash="h", root_kind=RootKind.FLAG, root=root, rank=rank, files=("a.py",), hits=(_hit(root),)
    )
    return HarvestCandidate(view=view, verdict=_verdict(files=files), verified_sha="abc123def456")


@pytest.mark.parametrize(
    "open_count,max_prs,expected_roots,skipped_budget,skipped_size",
    [
        (0, 3, ["strong", "weak"], 0, 1),
        (2, 3, ["strong"], 1, 1),
        (3, 3, [], 2, 1),
    ],
)
def test_select_harvest_honors_budget_and_size(open_count, max_prs, expected_roots, skipped_budget, skipped_size):
    candidates = [
        _candidate("weak", rank=ClusterRank.WEAK),
        _candidate("strong"),
        _candidate("big", files=MAX_FILES_PER_PR + 1),
    ]

    selection = select_harvest(candidates, open_count=open_count, max_prs=max_prs)

    assert [c.view.root for c in selection.selected] == expected_roots
    assert (selection.skipped_budget, selection.skipped_size) == (skipped_budget, skipped_size)


def test_pr_body_carries_the_evidence_and_the_archive_checklist():
    body = render_pr_body(_candidate("hero-copy"))

    assert "- **experiments**: Experiment lost" in body
    assert "| key | `rg -F 'k'` | 0 |" in body
    assert "- whether docs mention it" in body
    assert "Archive the flag `hero-copy`" in body
    assert "never merged automatically" in body


@pytest.mark.parametrize("url,expected", [("https://github.com/o/r/pull/42", 42), ("https://github.com/o/r", None)])
def test_parse_pr_number(url, expected):
    assert parse_pr_number(url) == expected


def _seed_dead(team, *roots: str):
    inventory = upsert_inventory(team_id=team.id, repository="o/r", scope="flags")
    record_scan(inventory, converge(_hit(root) for root in roots), head_sha="abc", now=NOW)
    for cluster in ReaperCluster.objects.filter(inventory=inventory):
        ReaperArtefact.append(
            team_id=team.id,
            inventory_id=inventory.id,
            cluster_id=cluster.id,
            content=VerdictRecord(head_sha="abc", verdict=_verdict()),
        )
    ReaperCluster.objects.filter(inventory=inventory).update(status=ClusterStatus.DEAD)
    return inventory


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestDispatchHarvest:
    def test_dispatches_a_task_per_dead_cluster_and_marks_it_harvesting(self, team, user):
        inventory = _seed_dead(team, "a")
        task_id = uuid4()
        create = MagicMock(return_value=MagicMock(task_id=task_id))

        with patch(f"{_MODULE}.tasks_facade.create_and_run_task", create):
            result = dispatch_harvest(HarvestRequest(team_id=team.id, user_id=user.id, repository="o/r", scope="flags"))

        assert result.dispatched == 1
        cluster = ReaperCluster.objects.get(inventory=inventory, root="a")
        assert (cluster.status, cluster.task_id) == (ClusterStatus.HARVESTING, task_id)
        kwargs = create.call_args.kwargs
        assert kwargs["title"] == "chore(reaper): remove flag a"
        assert kwargs["create_pr"] is True
        assert kwargs["repository"] == "o/r"
        assert "Delete the flag check in a.py" in kwargs["description"]
        assert 'label "reaper-hog"' in kwargs["description"]
        assert "reaper/a" in kwargs["description"]

    def test_open_pull_requests_count_against_the_budget(self, team, user):
        inventory = _seed_dead(team, "a", "b")
        ReaperCluster.objects.filter(inventory=inventory, root="b").update(status=ClusterStatus.REAPED)
        create = MagicMock(return_value=MagicMock(task_id=uuid4()))

        with patch(f"{_MODULE}.tasks_facade.create_and_run_task", create):
            result = dispatch_harvest(
                HarvestRequest(team_id=team.id, user_id=user.id, repository="o/r", scope="flags", max_prs=1)
            )

        assert (result.dispatched, result.skipped_budget, result.open_before) == (0, 1, 1)
        create.assert_not_called()


def _run(*, pr_url: str | None, terminal: bool):
    return MagicMock(pr_url=pr_url, is_terminal=terminal, status="completed" if terminal else "in_progress")


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestSyncHarvest:
    @pytest.mark.parametrize(
        "run,expected_status,expected_number",
        [
            (_run(pr_url="https://github.com/o/r/pull/7", terminal=False), ClusterStatus.REAPED, 7),
            (_run(pr_url=None, terminal=True), ClusterStatus.UNDECIDED, None),
            (_run(pr_url=None, terminal=False), ClusterStatus.HARVESTING, None),
        ],
    )
    def test_harvesting_clusters_follow_their_task_run(self, team, run, expected_status, expected_number):
        inventory = _seed_dead(team, "a")
        task_id = uuid4()
        ReaperCluster.objects.filter(inventory=inventory).update(status=ClusterStatus.HARVESTING, task_id=task_id)

        with (
            patch(f"{_MODULE}.tasks_facade.get_latest_run_by_task", return_value={str(task_id): run}),
            patch(f"{_MODULE}.pull_request_state") as state,
        ):
            state.return_value = PullRequestState(number=7, state="open")
            sync_harvest(team_id=team.id, repository="o/r", scope="flags")

        cluster = ReaperCluster.objects.get(inventory=inventory, root="a")
        assert (cluster.status, cluster.pr_number) == (expected_status, expected_number)

    @pytest.mark.parametrize(
        "state,expected",
        [("merged", ClusterStatus.BURIED), ("closed", ClusterStatus.DECLINED), ("open", ClusterStatus.REAPED)],
    )
    def test_reaped_clusters_follow_their_pull_request(self, team, state, expected):
        inventory = _seed_dead(team, "a")
        ReaperCluster.objects.filter(inventory=inventory).update(
            status=ClusterStatus.REAPED, pr_number=7, pr_url="https://github.com/o/r/pull/7"
        )

        with (
            patch(f"{_MODULE}.tasks_facade.get_latest_run_by_task", return_value={}),
            patch(f"{_MODULE}.pull_request_state", return_value=PullRequestState(number=7, state=state)),
        ):
            sync_harvest(team_id=team.id, repository="o/r", scope="flags")

        assert ReaperCluster.objects.get(inventory=inventory, root="a").status == expected
