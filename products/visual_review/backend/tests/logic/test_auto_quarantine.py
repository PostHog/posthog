from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.contracts import AUTO_QUARANTINE_DAILY_LIMIT, AUTO_QUARANTINE_DAYS
from products.visual_review.backend.facade.enums import (
    ActorType,
    AutoQuarantineMode,
    RunPurpose,
    RunStatus,
    RunType,
    SnapshotResult,
)
from products.visual_review.backend.logic import auto_quarantine, repos, runs
from products.visual_review.backend.logic.auto_quarantine import (
    Observation,
    ProofAction,
    ProofCandidate,
    ProofKind,
    TrustedRun,
    ancestry_questions,
    batch_runs,
    first_proof,
    proof_action,
    proof_candidates,
)
from products.visual_review.backend.logic.github_api import MergeQueueBatch
from products.visual_review.backend.models import QuarantinedIdentifier, Repo, Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES

_T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
_BASE = "base"


def _trusted(sha: str, hour: int, on_default_branch: bool) -> TrustedRun:
    return TrustedRun(
        id=uuid4(), commit_sha=sha, created_at=_T0 + timedelta(hours=hour), on_default_branch=on_default_branch
    )


# m1 and m2 are default-branch commits, m2 holds m1. Each queue run is a test branch on m1 unless named.
_M1 = _trusted("m1", 0, True)
_M2 = _trusted("m2", 2, True)
_M1_RERUN = _trusted("m1", 1, True)
_Q1 = _trusted("q1", 1, False)
_Q2 = _trusted("q2", 3, False)
_Q2_OFF_OTHER_BASE = _trusted("q2-other-base", 3, False)
_Q3 = _trusted("q3", 4, False)
_Q4 = _trusted("q4", 5, False)
_Q_EARLY = _trusted("q-early", -1, False)
_Q_UNKNOWN = _trusted("q-unknown", 3, False)

_ANCESTRY = {("m1", "m2"), ("m1", "q1"), ("m1", "q2"), ("m1", "q3"), ("m1", "q4"), ("m1", "q-early")}
_BATCHES = {
    "q1": MergeQueueBatch(base_sha="m1", pull_request_heads=frozenset({"p1"})),
    "q2": MergeQueueBatch(base_sha="m1", pull_request_heads=frozenset({"p1", "p2"})),
    "q2-other-base": MergeQueueBatch(base_sha="m0", pull_request_heads=frozenset({"p1", "p2"})),
    "q3": MergeQueueBatch(base_sha="m1", pull_request_heads=frozenset({"p3"})),
    "q4": MergeQueueBatch(base_sha="m1", pull_request_heads=frozenset({"p4"})),
    "q-early": MergeQueueBatch(base_sha="m1", pull_request_heads=frozenset({"p5"})),
}


def _failing(run: TrustedRun, **overrides) -> Observation:
    fields = {"result": SnapshotResult.CHANGED, "review_state": "", "baseline_hash": _BASE, "is_quarantined": False}
    return Observation(run=run, **{**fields, **overrides})


def _clean(run: TrustedRun, **overrides) -> Observation:
    fields = {"result": SnapshotResult.UNCHANGED, "review_state": "", "baseline_hash": _BASE, "is_quarantined": False}
    return Observation(run=run, **{**fields, **overrides})


def _prove(observations: list[Observation], finishing: TrustedRun) -> ProofCandidate | None:
    candidates = proof_candidates(observations, _BASE, finishing)
    batches = {run.id: _BATCHES.get(run.commit_sha) for run in batch_runs(candidates)}
    ancestry = {question: question in _ANCESTRY for question in ancestry_questions(candidates, batches)}
    return first_proof(candidates, batches, ancestry)


class TestFlakeProof:
    @pytest.mark.parametrize(
        "_name,observations,finishing,expected",
        [
            ("superset_master_in_master", [_failing(_M1), _clean(_M2)], _M2, ProofKind.SUPERSET),
            ("superset_rerun_of_the_same_commit", [_failing(_M1), _clean(_M1_RERUN)], _M1_RERUN, ProofKind.SUPERSET),
            # A clean render of the same commit holds the finishing run's tree, even when it came first.
            ("superset_same_commit_clean_earlier", [_clean(_M1), _failing(_M1_RERUN)], _M1_RERUN, ProofKind.SUPERSET),
            ("superset_master_in_queue", [_failing(_M1), _clean(_Q2)], _Q2, ProofKind.SUPERSET),
            ("superset_queue_in_queue", [_failing(_Q1), _clean(_Q2)], _Q2, ProofKind.SUPERSET),
            ("superset_failing_finish_held_later", [_failing(_Q1), _clean(_Q2)], _Q1, ProofKind.SUPERSET),
            ("disjoint_queue_runs", [_failing(_Q1), _failing(_Q3), _clean(_Q4)], _Q4, ProofKind.DISJOINT),
            ("disjoint_failing_finish", [_failing(_Q1), _clean(_Q2), _failing(_Q3)], _Q3, ProofKind.DISJOINT),
            ("disjoint_master_and_queue", [_failing(_Q1), _failing(_M2), _clean(_Q4)], _Q4, ProofKind.DISJOINT),
            # Earlier runs prove it, but that proof was there when its last run finished.
            (
                "refuses_a_proof_without_the_finishing_run",
                [_failing(_M1), _clean(_M2), _clean(_Q2_OFF_OTHER_BASE)],
                _Q2_OFF_OTHER_BASE,
                None,
            ),
            ("refuses_a_finishing_run_without_the_story", [_failing(_M1), _clean(_M2)], _Q4, None),
            # A pull request in the batch broke the story, and the queue was right to fail.
            ("refuses_a_queue_run_in_master", [_failing(_Q1), _clean(_M2)], _M2, None),
            ("refuses_a_master_commit_not_held", [_failing(_Q1), _clean(_Q2_OFF_OTHER_BASE)], _Q2_OFF_OTHER_BASE, None),
            ("refuses_an_unknown_batch", [_failing(_Q1), _clean(_Q_UNKNOWN)], _Q_UNKNOWN, None),
            ("refuses_a_clean_run_before_both", [_failing(_Q3), _failing(_Q4), _clean(_Q_EARLY)], _Q4, None),
            ("refuses_failures_sharing_a_pr", [_failing(_Q1), _failing(_Q2), _clean(_Q4)], _Q4, None),
            ("refuses_disjoint_with_unknown_batch", [_failing(_Q1), _failing(_Q_UNKNOWN), _clean(_Q4)], _Q4, None),
            ("refuses_new", [_failing(_M1, result=SnapshotResult.NEW), _clean(_M2)], _M2, None),
            ("refuses_removed", [_failing(_M1, result=SnapshotResult.REMOVED), _clean(_M2)], _M2, None),
            # The batch carried its own baseline for the story.
            ("refuses_another_baseline", [_failing(_Q1, baseline_hash="pr-edit"), _clean(_Q2)], _Q2, None),
            ("refuses_a_clean_run_on_another_baseline", [_failing(_M1), _clean(_M2, baseline_hash="old")], _M2, None),
            ("refuses_a_quarantined_failure", [_failing(_M1, is_quarantined=True), _clean(_M2)], _M2, None),
            ("refuses_a_quarantined_clean_run", [_failing(_M1), _clean(_M2, is_quarantined=True)], _M2, None),
            ("refuses_an_approved_change", [_failing(_M1, review_state="approved"), _clean(_M2)], _M2, None),
        ],
    )
    def test_proof(
        self, _name: str, observations: list[Observation], finishing: TrustedRun, expected: ProofKind | None
    ) -> None:
        proof = _prove(observations, finishing)

        assert (proof.kind if proof else None) == expected

    def test_candidates_are_capped_per_story(self) -> None:
        finishing = _trusted("m9", 9, True)
        failing = [_failing(_trusted(f"m{hour}", hour, True)) for hour in range(8)]

        candidates = proof_candidates([*failing, _clean(finishing)], _BASE, finishing)

        assert [candidate.failing_runs[0].commit_sha for candidate in candidates] == ["m7", "m6", "m5", "m4", "m3"]

    @pytest.mark.parametrize(
        "mode,automatic_today,expected",
        [
            (AutoQuarantineMode.ON, 9, ProofAction.APPLY),
            (AutoQuarantineMode.ON, 10, ProofAction.REPORT_CAPPED),
            (AutoQuarantineMode.PREVIEW, 0, ProofAction.REPORT),
            (AutoQuarantineMode.PREVIEW, 10, ProofAction.REPORT),
        ],
    )
    def test_proof_action(self, mode: AutoQuarantineMode, automatic_today: int, expected: ProofAction) -> None:
        assert proof_action(mode, automatic_today, limit=10) == expected

    def test_the_reason_names_both_runs_of_a_superset_proof(self) -> None:
        proof = ProofCandidate(
            kind=ProofKind.SUPERSET,
            failing_runs=(_trusted("a" * 40, 0, True),),
            clean_run=_trusted("b" * 40, 1, False),
        )

        assert (
            auto_quarantine.proof_reason(proof)
            == "Flake proven: changed in aaaaaaa and unchanged in bbbbbbb, which contains it"
        )


_IDENTIFIER = "scenes-app-button--primary--light"
_FAILING_SHA = "a" * 40
_CLEAN_SHA = "b" * 40
_GITHUB = "products.visual_review.backend.logic.github_api"


def _master_run(
    repo: Repo, sha: str, status: RunStatus, hours_ago: int, result: SnapshotResult, branch: str = "master"
) -> Run:
    run = Run.objects.create(
        team_id=repo.team_id,
        repo=repo,
        run_type=RunType.STORYBOOK,
        branch=branch,
        commit_sha=sha,
        status=status,
        purpose=RunPurpose.OBSERVE,
        completed_at=timezone.now() if status == RunStatus.COMPLETED else None,
    )
    # A completed run points at itself as superseded, so the next run on the branch has its slot.
    superseded_by = run if status == RunStatus.COMPLETED else None
    Run.objects.filter(id=run.id).update(
        created_at=timezone.now() - timedelta(hours=hours_ago), superseded_by=superseded_by
    )
    RunSnapshot.objects.create(
        team_id=repo.team_id, run=run, identifier=_IDENTIFIER, result=result, baseline_hash=_BASE
    )
    return Run.objects.get(id=run.id)


@pytest.fixture
def repo(team) -> Repo:
    repo = repos.create_repo(team_id=team.id, repo_external_id=88001, repo_full_name="org/auto-quarantine")
    repo.auto_quarantine_mode = AutoQuarantineMode.ON
    repo.save()
    return repo


@pytest.fixture
def capture():
    with patch("products.visual_review.backend.logic.auto_quarantine.ph_scoped_capture") as scoped:
        capture = MagicMock()
        scoped.return_value.__enter__.return_value = capture
        yield capture


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestQuarantineProvenFlakes:
    @pytest.fixture
    def github(self):
        with (
            patch(f"{_GITHUB}.default_branch_name", return_value="master") as default_branch_name,
            # Every later commit holds the failing one.
            patch(f"{_GITHUB}.commit_contains", side_effect=lambda repo, a, b: a == _FAILING_SHA) as commit_contains,
            patch(f"{_GITHUB}.merge_queue_batch", return_value=None) as merge_queue_batch,
        ):
            default_branch_name.commit_contains = commit_contains
            default_branch_name.merge_queue_batch = merge_queue_batch
            yield default_branch_name

    def _superset_proof(self, repo: Repo) -> tuple[Run, Run]:
        failing = _master_run(repo, _FAILING_SHA, RunStatus.COMPLETED, 2, SnapshotResult.CHANGED)
        finishing = _master_run(repo, _CLEAN_SHA, RunStatus.PROCESSING, 0, SnapshotResult.UNCHANGED)
        return failing, finishing

    def _auto_rows(self, repo: Repo):
        return QuarantinedIdentifier.objects.using(WRITER_DB).filter(repo=repo, source=ActorType.AUTO)

    @pytest.mark.parametrize(
        "mode,expected_rows,expected_applied",
        [
            (AutoQuarantineMode.OFF, 0, None),
            (AutoQuarantineMode.PREVIEW, 0, False),
            (AutoQuarantineMode.ON, 1, True),
        ],
    )
    def test_the_mode_decides_what_a_proof_does(self, repo, github, capture, mode, expected_rows, expected_applied):
        repo.auto_quarantine_mode = mode
        repo.save()
        failing, finishing = self._superset_proof(repo)

        auto_quarantine.quarantine_proven_flakes(finishing)

        rows = list(self._auto_rows(repo))
        assert len(rows) == expected_rows
        if mode == AutoQuarantineMode.OFF:
            assert github.call_count == 0
            assert capture.call_count == 0
            return
        properties = capture.call_args.kwargs["properties"]
        assert (properties["applied"], properties["proof_kind"], properties["capped"]) == (
            expected_applied,
            "superset",
            False,
        )
        if rows:
            assert (rows[0].source_run_id, rows[0].created_by_id) == (failing.id, None)
            expected_expiry = timezone.now() + timedelta(days=AUTO_QUARANTINE_DAYS)
            assert abs(rows[0].expires_at - expected_expiry) < timedelta(minutes=1)

    def test_a_proof_left_in_place_is_reported_once(self, repo, github, capture):
        repo.auto_quarantine_mode = AutoQuarantineMode.PREVIEW
        repo.save()
        _failing, first = self._superset_proof(repo)
        auto_quarantine.quarantine_proven_flakes(first)
        Run.objects.filter(id=first.id).update(status=RunStatus.COMPLETED, superseded_by=first)
        second = _master_run(repo, "c" * 40, RunStatus.PROCESSING, 0, SnapshotResult.UNCHANGED)

        auto_quarantine.quarantine_proven_flakes(second)

        assert capture.call_count == 1

    def test_the_daily_limit_stops_more_automatic_quarantines(self, repo, github, capture):
        for index in range(AUTO_QUARANTINE_DAILY_LIMIT):
            QuarantinedIdentifier.objects.create(
                team_id=repo.team_id,
                repo=repo,
                identifier=f"other--{index}",
                run_type=RunType.STORYBOOK,
                reason="earlier proof",
                source=ActorType.AUTO,
                expires_at=timezone.now() + timedelta(days=1),
            )
        _failing, finishing = self._superset_proof(repo)

        with patch("products.visual_review.backend.tasks.tasks.notify_auto_quarantine_limit.apply_async") as notice:
            auto_quarantine.quarantine_proven_flakes(finishing)

        assert not self._auto_rows(repo).filter(identifier=_IDENTIFIER).exists()
        assert capture.call_args.kwargs["properties"]["capped"] is True
        assert notice.call_args.kwargs["args"] == (repo.team_id, str(repo.id), AUTO_QUARANTINE_DAILY_LIMIT)

    def test_two_runs_finishing_together_quarantine_once(self, repo, github, capture):
        _failing, first = self._superset_proof(repo)
        Run.objects.filter(id=first.id).update(superseded_by=first)
        second = _master_run(repo, "c" * 40, RunStatus.PROCESSING, 0, SnapshotResult.UNCHANGED)

        # Both runs read the quarantines before either wrote one.
        with patch.object(auto_quarantine, "_active_quarantines", return_value=set()):
            auto_quarantine.quarantine_proven_flakes(first)
            auto_quarantine.quarantine_proven_flakes(second)

        assert self._auto_rows(repo).filter(identifier=_IDENTIFIER).count() == 1

    def test_a_story_without_a_candidate_asks_github_nothing(self, repo, github, capture):
        _master_run(repo, _FAILING_SHA, RunStatus.COMPLETED, 3, SnapshotResult.CHANGED)
        # The finishing queue run renders the story neither changed nor unchanged.
        finishing = _master_run(
            repo, _CLEAN_SHA, RunStatus.PROCESSING, 0, SnapshotResult.REMOVED, branch="trunk-merge/pr-7/abc"
        )

        auto_quarantine.quarantine_proven_flakes(finishing)

        assert (github.commit_contains.call_count, github.merge_queue_batch.call_count) == (0, 0)
        assert capture.call_count == 0

    def test_an_identifier_already_quarantined_is_left_alone(self, repo, github, capture):
        QuarantinedIdentifier.objects.create(
            team_id=repo.team_id, repo=repo, identifier=_IDENTIFIER, run_type=RunType.STORYBOOK, reason="by hand"
        )
        _failing, finishing = self._superset_proof(repo)

        auto_quarantine.quarantine_proven_flakes(finishing)

        assert not self._auto_rows(repo).exists()
        assert capture.call_count == 0


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestFinishProcessingQuarantinesProvenFlakes:
    @pytest.mark.parametrize("hook_fails,expected_changed_count", [(False, 0), (True, 1)])
    def test_a_proof_the_finishing_run_completes_passes_that_run(
        self, repo, capture, hook_fails, expected_changed_count
    ):
        # Two default-branch failures with a clean run between them: a disjoint proof that the
        # finishing run completes with its own failure.
        _master_run(repo, "c" * 40, RunStatus.COMPLETED, 3, SnapshotResult.CHANGED)
        _master_run(repo, "d" * 40, RunStatus.COMPLETED, 2, SnapshotResult.UNCHANGED)
        finishing = _master_run(repo, "e" * 40, RunStatus.PROCESSING, 0, SnapshotResult.CHANGED)
        hook = patch(
            "products.visual_review.backend.logic.auto_quarantine.quarantine_proven_flakes",
            side_effect=RuntimeError("GitHub down"),
        )
        with (
            patch(f"{_GITHUB}.default_branch_name", return_value="master"),
            patch(f"{_GITHUB}.commit_contains", return_value=False),
        ):
            if hook_fails:
                with hook:
                    updated = runs.finish_processing(finishing.id)
            else:
                updated = runs.finish_processing(finishing.id)

        assert (updated.status, updated.changed_count) == (RunStatus.COMPLETED, expected_changed_count)
