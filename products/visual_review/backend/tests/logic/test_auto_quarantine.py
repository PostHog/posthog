from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from django.db import connections
from django.test.utils import CaptureQueriesContext
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
    AncestryQuestion,
    Observation,
    ProofAction,
    ProofCandidate,
    ProofKind,
    TrustedRun,
    ancestry_questions,
    is_proven,
    proof_action,
    proof_candidates,
)
from products.visual_review.backend.models import QuarantinedIdentifier, Repo, Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES

_T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
_BASE = "base"
_FLAKY = "flaky-picture"


def _trusted(sha: str, hour: int, on_default_branch: bool = True) -> TrustedRun:
    return TrustedRun(
        id=uuid4(),
        commit_sha=sha,
        branch="master" if on_default_branch else f"trunk-merge/pr-1/{sha}",
        created_at=_T0 + timedelta(hours=hour),
        on_default_branch=on_default_branch,
    )


# Each commit descends from the one before it: a, b, c on the default branch and qa, qb, qc in the queue.
_A = _trusted("a", 0)
_B = _trusted("b", 1)
_C = _trusted("c", 2)
_C_EARLIER_RUN = _trusted("c", 1)
_QA = _trusted("qa", 0, on_default_branch=False)
_QB = _trusted("qb", 1, on_default_branch=False)
_QC = _trusted("qc", 2, on_default_branch=False)
_DESCENDS = {("a", "b"), ("b", "c"), ("qa", "qb"), ("qb", "qc")}


def _failing(run: TrustedRun, **overrides) -> Observation:
    fields = {
        "result": SnapshotResult.CHANGED,
        "review_state": "",
        "baseline_hash": _BASE,
        "current_hash": _FLAKY,
        "is_quarantined": False,
    }
    return Observation(run=run, **{**fields, **overrides})


def _clean(run: TrustedRun, **overrides) -> Observation:
    fields = {
        "result": SnapshotResult.UNCHANGED,
        "review_state": "",
        "baseline_hash": _BASE,
        "current_hash": _BASE,
        "is_quarantined": False,
    }
    return Observation(run=run, **{**fields, **overrides})


def _prove(observations: list[Observation], finishing: TrustedRun, descends=_DESCENDS) -> ProofCandidate | None:
    for candidate in proof_candidates(observations, _BASE, finishing):
        answers = {
            question: (question.ancestor_sha, question.head_sha) in descends
            for question in ancestry_questions(candidate)
        }
        if is_proven(candidate, answers):
            return candidate
    return None


class TestFlakeProof:
    @pytest.mark.parametrize(
        "_name,observations,finishing,descends,expected",
        [
            ("chain_on_the_default_branch", [_failing(_A), _clean(_B), _failing(_C)], _C, _DESCENDS, ProofKind.CHAIN),
            ("chain_in_the_queue", [_failing(_QA), _clean(_QB), _failing(_QC)], _QC, _DESCENDS, ProofKind.CHAIN),
            ("same_commit", [_clean(_C_EARLIER_RUN), _failing(_C)], _C, _DESCENDS, ProofKind.SAME_COMMIT),
            # One failure then a clean run is a break and a fix as much as a flake.
            ("refuses_one_fail_then_clean", [_failing(_A), _clean(_B)], _B, _DESCENDS, None),
            ("refuses_a_finishing_run_that_is_clean", [_failing(_A), _clean(_B), _clean(_C)], _C, _DESCENDS, None),
            (
                "refuses_a_clean_run_not_holding_the_first_failure",
                [_failing(_A), _clean(_B), _failing(_C)],
                _C,
                {("b", "c")},
                None,
            ),
            (
                "refuses_a_closing_run_not_holding_the_clean_run",
                [_failing(_A), _clean(_B), _failing(_C)],
                _C,
                {("a", "b")},
                None,
            ),
            # A tolerated match of the failing picture is the same render, not a clean one.
            (
                "refuses_the_same_picture_in_a_chain",
                [_failing(_A), _clean(_B, current_hash=_FLAKY), _failing(_C)],
                _C,
                _DESCENDS,
                None,
            ),
            (
                "refuses_the_same_picture_on_one_commit",
                [_clean(_C_EARLIER_RUN, current_hash=_FLAKY), _failing(_C)],
                _C,
                _DESCENDS,
                None,
            ),
            (
                "refuses_a_queue_run_as_ancestor_of_the_default_branch",
                [_failing(_A), _clean(_QB), _failing(_C)],
                _C,
                {("a", "qb"), ("qb", "c")},
                None,
            ),
            (
                "refuses_another_baseline",
                [_failing(_A), _clean(_B), _failing(_C, baseline_hash="pr-edit")],
                _C,
                _DESCENDS,
                None,
            ),
            ("refuses_new", [_failing(_A), _clean(_B), _failing(_C, result=SnapshotResult.NEW)], _C, _DESCENDS, None),
            (
                "refuses_removed",
                [_failing(_A), _clean(_B), _failing(_C, result=SnapshotResult.REMOVED)],
                _C,
                _DESCENDS,
                None,
            ),
            (
                "refuses_a_quarantined_failure",
                [_failing(_A, is_quarantined=True), _clean(_B), _failing(_C)],
                _C,
                _DESCENDS,
                None,
            ),
            (
                "refuses_an_approved_failure",
                [_failing(_A, review_state="approved"), _clean(_B), _failing(_C)],
                _C,
                _DESCENDS,
                None,
            ),
            (
                "refuses_a_quarantined_clean_run",
                [_failing(_A), _clean(_B, is_quarantined=True), _failing(_C)],
                _C,
                _DESCENDS,
                None,
            ),
        ],
    )
    def test_proof(self, _name, observations, finishing, descends, expected) -> None:
        proof = _prove(observations, finishing, descends)

        assert (proof.kind if proof else None) == expected

    def test_a_missing_answer_proves_nothing(self) -> None:
        candidate = ProofCandidate(kind=ProofKind.CHAIN, failing_runs=(_A, _C), clean_run=_B)

        assert not is_proven(candidate, {AncestryQuestion(ancestor_sha="a", head_sha="b"): True})

    def test_candidates_stop_at_the_cap_without_building_every_pair(self) -> None:
        finishing = _trusted("z", 100)
        observations = [_failing(finishing)]
        for hour in range(50):
            observations += [_failing(_trusted(f"f{hour}", hour)), _clean(_trusted(f"c{hour}", hour))]

        with patch.object(auto_quarantine, "ProofCandidate", wraps=ProofCandidate) as built:
            candidates = list(proof_candidates(observations, _BASE, finishing))

        assert len(candidates) == built.call_count == 5

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

    def test_the_reason_names_the_three_commits_of_a_chain(self) -> None:
        proof = ProofCandidate(
            kind=ProofKind.CHAIN,
            failing_runs=(_trusted("a" * 40, 0), _trusted("c" * 40, 2)),
            clean_run=_trusted("b" * 40, 1),
        )

        assert auto_quarantine.proof_reason(proof) == (
            "Flake proven: changed in aaaaaaa, unchanged in bbbbbbb which contains it, "
            "changed again in ccccccc which contains that"
        )


_IDENTIFIER = "scenes-app-button--primary--light"
_GITHUB = "products.visual_review.backend.logic.github_api"


def _run(repo: Repo, sha: str, hours_ago: int, result: SnapshotResult, *, finishing: bool = False) -> Run:
    run = Run.objects.create(
        team_id=repo.team_id,
        repo=repo,
        run_type=RunType.STORYBOOK,
        branch="master",
        commit_sha=sha,
        status=RunStatus.PROCESSING if finishing else RunStatus.COMPLETED,
        purpose=RunPurpose.OBSERVE,
        completed_at=None if finishing else timezone.now(),
    )
    # A completed run points at itself as superseded, so the next run on the branch has its slot.
    Run.objects.filter(id=run.id).update(
        created_at=timezone.now() - timedelta(hours=hours_ago), superseded_by=None if finishing else run
    )
    RunSnapshot.objects.create(
        team_id=repo.team_id,
        run=run,
        identifier=_IDENTIFIER,
        result=result,
        baseline_hash=_BASE,
        current_hash=_FLAKY if result == SnapshotResult.CHANGED else _BASE,
    )
    return Run.objects.get(id=run.id)


def _chain(repo: Repo) -> Run:
    _run(repo, "a" * 40, 3, SnapshotResult.CHANGED)
    _run(repo, "b" * 40, 2, SnapshotResult.UNCHANGED)
    return _run(repo, "c" * 40, 0, SnapshotResult.CHANGED, finishing=True)


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


@pytest.fixture
def github():
    with (
        patch(f"{_GITHUB}.default_branch_name", return_value="master") as default_branch_name,
        patch(f"{_GITHUB}.commit_contains", return_value=True) as commit_contains,
        patch(f"{_GITHUB}.default_branch_head_sha", return_value="h" * 40) as head,
    ):
        default_branch_name.commit_contains = commit_contains
        default_branch_name.head = head
        yield default_branch_name


def _auto_rows(repo: Repo):
    return QuarantinedIdentifier.objects.using(WRITER_DB).filter(repo=repo, source=ActorType.AUTO)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestQuarantineProvenFlakes:
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
        finishing = _chain(repo)

        auto_quarantine.quarantine_proven_flakes(finishing)

        rows = list(_auto_rows(repo))
        assert len(rows) == expected_rows
        if mode == AutoQuarantineMode.OFF:
            assert (github.call_count, capture.call_count) == (0, 0)
            return
        properties = capture.call_args.kwargs["properties"]
        assert (properties["applied"], properties["proof_kind"]) == (expected_applied, "chain")
        if rows:
            assert (rows[0].source_run_id, rows[0].created_by_id) == (finishing.id, None)
            expected_expiry = timezone.now() + timedelta(days=AUTO_QUARANTINE_DAYS)
            assert abs(rows[0].expires_at - expected_expiry) < timedelta(minutes=1)

    def test_a_run_that_fails_no_story_leaves_after_one_query(self, repo, github, capture):
        finishing = _run(repo, "c" * 40, 0, SnapshotResult.UNCHANGED, finishing=True)

        with CaptureQueriesContext(connections[WRITER_DB]) as queries:
            auto_quarantine.quarantine_proven_flakes(finishing)

        assert (len(queries.captured_queries), github.call_count) == (1, 0)

    def test_a_proof_left_in_place_is_reported_once(self, repo, github, capture):
        repo.auto_quarantine_mode = AutoQuarantineMode.PREVIEW
        repo.save()
        first = _chain(repo)
        auto_quarantine.quarantine_proven_flakes(first)
        Run.objects.filter(id=first.id).update(status=RunStatus.COMPLETED, superseded_by=first)
        second = _run(repo, "d" * 40, 0, SnapshotResult.CHANGED, finishing=True)

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
        finishing = _chain(repo)

        with patch("products.visual_review.backend.tasks.tasks.notify_auto_quarantine_limit.apply_async") as notice:
            auto_quarantine.quarantine_proven_flakes(finishing)

        assert not _auto_rows(repo).filter(identifier=_IDENTIFIER).exists()
        assert capture.call_args.kwargs["properties"]["capped"] is True
        assert notice.call_args.kwargs["args"] == (repo.team_id, str(repo.id), AUTO_QUARANTINE_DAILY_LIMIT)

    def test_the_limit_is_counted_again_under_the_repo_lock(self, repo, github, capture):
        finishing = _chain(repo)

        # Another run reached the limit between this run's first count and its write.
        with (
            patch.object(
                auto_quarantine, "_recent_automatic_quarantines", side_effect=[0, AUTO_QUARANTINE_DAILY_LIMIT]
            ),
            patch("products.visual_review.backend.tasks.tasks.notify_auto_quarantine_limit.apply_async"),
        ):
            auto_quarantine.quarantine_proven_flakes(finishing)

        assert not _auto_rows(repo).exists()
        assert capture.call_args.kwargs["properties"]["capped"] is True

    @pytest.mark.parametrize("lifted", [False, True])
    def test_an_identifier_already_quarantined_is_left_alone(self, repo, github, capture, lifted):
        # A lift at a commit the finishing run does not contain still quarantines the story for that run.
        lift_sha = "l" * 40
        QuarantinedIdentifier.objects.create(
            team_id=repo.team_id,
            repo=repo,
            identifier=_IDENTIFIER,
            run_type=RunType.STORYBOOK,
            reason="by hand",
            lifted_at_sha=lift_sha if lifted else None,
            expires_at=timezone.now() - timedelta(hours=1) if lifted else None,
        )
        github.commit_contains.side_effect = lambda _repo, ancestor, _head: ancestor != lift_sha
        finishing = _chain(repo)

        auto_quarantine.quarantine_proven_flakes(finishing)

        assert not _auto_rows(repo).exists()
        assert capture.call_count == 0

    @pytest.mark.parametrize("head_sha,budget_seconds", [(None, 20), ("h" * 40, 0)])
    def test_no_proof_without_provenance_or_time(self, repo, github, capture, head_sha, budget_seconds):
        github.head.return_value = head_sha
        finishing = _chain(repo)

        auto_quarantine.quarantine_proven_flakes(finishing, budget_seconds=budget_seconds)

        assert not _auto_rows(repo).exists()
        assert capture.call_count == 0
        if budget_seconds == 0:
            assert github.commit_contains.call_count == 0


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestFinishProcessingQuarantinesProvenFlakes:
    @pytest.mark.parametrize("hook_fails,expected_changed_count", [(False, 0), (True, 1)])
    def test_a_proof_the_finishing_run_closes_passes_that_run(
        self, repo, github, capture, hook_fails, expected_changed_count
    ):
        finishing = _chain(repo)
        hook = patch(
            "products.visual_review.backend.logic.auto_quarantine.quarantine_proven_flakes",
            side_effect=RuntimeError("GitHub down"),
        )
        if hook_fails:
            with hook:
                updated = runs.finish_processing(finishing.id)
        else:
            updated = runs.finish_processing(finishing.id)

        assert (updated.status, updated.changed_count) == (RunStatus.COMPLETED, expected_changed_count)
