from datetime import timedelta

import pytest

from django.utils import timezone

from products.visual_review.backend.facade.enums import (
    QuarantineLiftState,
    ReviewState,
    RunPurpose,
    RunStatus,
    RunType,
    SnapshotResult,
)
from products.visual_review.backend.logic import errors, github_api, quarantine_lifts, repos, runs
from products.visual_review.backend.models import QuarantinedIdentifier, QuarantineLiftRequest, Repo, Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES

IDENTIFIER = "button--flaky--light"
PR_NUMBER = 42
MERGE_SHA = "merge-sha"
MASTER_SHA = "master-sha"


def _merged(base_ref: str = "master") -> github_api.PullRequestState:
    return github_api.PullRequestState(state="closed", merged=True, merge_commit_sha=MERGE_SHA, base_ref=base_ref)


def _run(repo: Repo, *, branch: str, pr_number: int | None, commit_sha: str, **overrides) -> Run:
    fields = {
        "team_id": repo.team_id,
        "repo": repo,
        "run_type": RunType.STORYBOOK,
        "branch": branch,
        "pr_number": pr_number,
        "commit_sha": commit_sha,
        "status": RunStatus.COMPLETED,
        "purpose": RunPurpose.REVIEW if pr_number is not None else RunPurpose.OBSERVE,
        "completed_at": timezone.now(),
        **overrides,
    }
    return Run.objects.create(**fields)


def _snapshot(run: Run, **fields) -> RunSnapshot:
    return RunSnapshot.objects.create(team_id=run.team_id, run=run, identifier=IDENTIFIER, **fields)


@pytest.fixture
def repo(team):
    return repos.create_repo(team_id=team.id, repo_external_id=77001, repo_full_name="org/lift-on-merge")


@pytest.fixture
def quarantine_row(repo):
    return QuarantinedIdentifier.objects.create(
        team_id=repo.team_id, repo=repo, identifier=IDENTIFIER, run_type=RunType.STORYBOOK, reason="flaky"
    )


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRequestLiftOnMerge:
    @pytest.mark.parametrize(
        ("name", "result", "review_state", "approved_hash", "is_quarantined", "expected_hash"),
        [
            ("unchanged_uses_the_baseline", SnapshotResult.UNCHANGED, "", "", True, "base"),
            (
                "approved_change_uses_the_approved_hash",
                SnapshotResult.CHANGED,
                ReviewState.APPROVED,
                "new",
                True,
                "new",
            ),
            ("quarantined_after_the_run_finished", SnapshotResult.UNCHANGED, "", "", False, "base"),
        ],
    )
    def test_records_one_pending_request_with_the_expected_picture(
        self, repo, quarantine_row, user, name, result, review_state, approved_hash, is_quarantined, expected_hash
    ):
        run = _run(repo, branch="fix-flake", pr_number=PR_NUMBER, commit_sha="pr-head")
        snapshot = _snapshot(
            run,
            current_hash=approved_hash or "base",
            baseline_hash="base",
            result=result,
            review_state=review_state,
            approved_hash=approved_hash,
            is_quarantined=is_quarantined,
        )

        first = quarantine_lifts.request_lift_on_merge(run.id, IDENTIFIER, repo.team_id, user.id)
        QuarantineLiftRequest.objects.filter(id=first.id).update(detail=quarantine_lifts.DETAIL_DIFFERENT_PICTURE)
        request = quarantine_lifts.request_lift_on_merge(run.id, IDENTIFIER, repo.team_id, user.id)

        pending = QuarantineLiftRequest.objects.filter(state=QuarantineLiftState.PENDING)
        assert [r.id for r in pending] == [request.id]
        assert request.expected_hash == expected_hash
        assert request.quarantine_id == quarantine_row.id
        assert request.pr_number == PR_NUMBER
        assert QuarantineLiftRequest.objects.get(id=request.id).detail == quarantine_lifts.DETAIL_WAITING_FOR_MERGE
        assert RunSnapshot.objects.get(id=snapshot.id).review_state == review_state

    @pytest.mark.parametrize(
        (
            "name",
            "pr_number",
            "stale",
            "has_quarantine",
            "result",
            "baseline_hash",
            "requested_identifier",
            "expected_error",
        ),
        [
            ("no_active_quarantine", PR_NUMBER, False, False, SnapshotResult.UNCHANGED, "new", IDENTIFIER, ValueError),
            ("no_pull_request", None, False, True, SnapshotResult.UNCHANGED, "new", IDENTIFIER, ValueError),
            ("stale_run", PR_NUMBER, True, True, SnapshotResult.UNCHANGED, "new", IDENTIFIER, errors.StaleRunError),
            ("changed_not_approved", PR_NUMBER, False, True, SnapshotResult.CHANGED, "base", IDENTIFIER, ValueError),
            (
                "unchanged_tolerated_variant",
                PR_NUMBER,
                False,
                True,
                SnapshotResult.UNCHANGED,
                "base",
                IDENTIFIER,
                ValueError,
            ),
            (
                "identifier_not_in_run",
                PR_NUMBER,
                False,
                True,
                SnapshotResult.UNCHANGED,
                "new",
                "other--story",
                errors.RunNotFoundError,
            ),
        ],
    )
    def test_refuses_a_request_it_cannot_verify(
        self,
        repo,
        quarantine_row,
        user,
        name,
        pr_number,
        stale,
        has_quarantine,
        result,
        baseline_hash,
        requested_identifier,
        expected_error,
    ):
        if not has_quarantine:
            quarantine_row.expires_at = timezone.now() - timedelta(minutes=1)
            quarantine_row.save(update_fields=["expires_at"])
        run = _run(repo, branch="fix-flake", pr_number=pr_number, commit_sha="pr-head")
        if stale:
            run.superseded_by = _run(repo, branch="other", pr_number=PR_NUMBER, commit_sha="newer")
            run.save(update_fields=["superseded_by"])
        _snapshot(
            run,
            current_hash="new",
            baseline_hash=baseline_hash,
            result=result,
            review_state=ReviewState.PENDING if result == SnapshotResult.CHANGED else "",
            is_quarantined=True,
        )

        with pytest.raises(expected_error):
            quarantine_lifts.request_lift_on_merge(run.id, requested_identifier, repo.team_id, user.id)

        assert not QuarantineLiftRequest.objects.exists()


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestCancelLiftRequest:
    @pytest.mark.parametrize(
        ("name", "request_pr_number", "state", "cancels"),
        [
            ("pending_request_of_this_pull_request", PR_NUMBER, QuarantineLiftState.PENDING, True),
            ("already_applied", PR_NUMBER, QuarantineLiftState.APPLIED, False),
            ("request_of_another_pull_request", PR_NUMBER + 1, QuarantineLiftState.PENDING, False),
        ],
    )
    def test_cancels_only_a_pending_request_of_the_runs_pull_request(
        self, repo, quarantine_row, name, request_pr_number, state, cancels
    ):
        run = _run(repo, branch="fix-flake", pr_number=PR_NUMBER, commit_sha="pr-head")
        request = QuarantineLiftRequest.objects.create(
            team_id=repo.team_id,
            repo=repo,
            quarantine=quarantine_row,
            identifier=IDENTIFIER,
            run_type=RunType.STORYBOOK,
            pr_number=request_pr_number,
            expected_hash="base",
            state=state,
        )

        if cancels:
            quarantine_lifts.cancel_lift_request(request.id, repo.team_id, run.id)
        else:
            with pytest.raises(errors.QuarantineLiftRequestNotFoundError):
                quarantine_lifts.cancel_lift_request(request.id, repo.team_id, run.id)

        request.refresh_from_db()
        assert request.state == (QuarantineLiftState.CANCELLED if cancels else state)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestReconcileLiftRequests:
    @pytest.fixture
    def pending_request(self, repo, quarantine_row):
        return QuarantineLiftRequest.objects.create(
            team_id=repo.team_id,
            repo=repo,
            quarantine=quarantine_row,
            identifier=IDENTIFIER,
            run_type=RunType.STORYBOOK,
            pr_number=PR_NUMBER,
            expected_hash="fixed",
            detail=quarantine_lifts.DETAIL_WAITING_FOR_MERGE,
        )

    @pytest.fixture
    def github(self, mocker):
        return {
            "default_branch_name": mocker.patch.object(github_api, "default_branch_name", return_value="master"),
            "pull_request_state": mocker.patch.object(github_api, "pull_request_state", return_value=_merged()),
            "commit_contains": mocker.patch.object(github_api, "commit_contains", return_value=True),
        }

    def test_lifts_the_quarantine_and_supersedes_sibling_requests(self, repo, quarantine_row, pending_request, github):
        sibling = QuarantineLiftRequest.objects.create(
            team_id=repo.team_id,
            repo=repo,
            quarantine=quarantine_row,
            identifier=IDENTIFIER,
            run_type=RunType.STORYBOOK,
            pr_number=PR_NUMBER + 1,
            expected_hash="fixed",
        )
        run = _run(repo, branch="master", pr_number=None, commit_sha=MASTER_SHA)
        _snapshot(run, current_hash="fixed", baseline_hash="fixed")

        quarantine_lifts.reconcile_lift_requests(run.id)

        quarantine_row.refresh_from_db()
        assert quarantine_row.expires_at is not None and quarantine_row.expires_at <= timezone.now()
        assert quarantine_row.lifted_at_sha == MASTER_SHA
        pending_request.refresh_from_db()
        assert pending_request.state == QuarantineLiftState.APPLIED
        assert pending_request.merge_commit_sha == MERGE_SHA
        assert pending_request.applied_run_id == run.id
        assert pending_request.lifted_at_sha == MASTER_SHA
        assert pending_request.resolved_at is not None
        sibling.refresh_from_db()
        assert sibling.state == QuarantineLiftState.SUPERSEDED

    def test_keeps_the_quarantine_when_the_requested_picture_changes_during_the_check(
        self, repo, quarantine_row, pending_request, github
    ):
        def reviewer_changes_the_picture(*args, **kwargs):
            QuarantineLiftRequest.objects.filter(id=pending_request.id).update(expected_hash="newer")
            return True

        github["commit_contains"].side_effect = reviewer_changes_the_picture
        run = _run(repo, branch="master", pr_number=None, commit_sha=MASTER_SHA)
        _snapshot(run, current_hash="fixed", baseline_hash="fixed")

        quarantine_lifts.reconcile_lift_requests(run.id)

        quarantine_row.refresh_from_db()
        assert quarantine_row.expires_at is None
        pending_request.refresh_from_db()
        assert pending_request.state == QuarantineLiftState.PENDING

    @pytest.mark.parametrize(
        ("name", "pull_request", "contains_merge", "current_hash", "baseline_hash", "state", "detail"),
        [
            (
                "different_picture",
                _merged(),
                True,
                "flaky",
                "fixed",
                QuarantineLiftState.PENDING,
                quarantine_lifts.DETAIL_DIFFERENT_PICTURE,
            ),
            (
                "stale_baseline",
                _merged(),
                True,
                "fixed",
                "old",
                QuarantineLiftState.PENDING,
                quarantine_lifts.DETAIL_BASELINE_MISMATCH,
            ),
            (
                "run_predates_the_merge",
                _merged(),
                False,
                "fixed",
                "fixed",
                QuarantineLiftState.PENDING,
                quarantine_lifts.DETAIL_WAITING_FOR_RUN,
            ),
            (
                "still_open",
                github_api.PullRequestState(state="open", merged=False, merge_commit_sha=None, base_ref="master"),
                True,
                "fixed",
                "fixed",
                QuarantineLiftState.PENDING,
                quarantine_lifts.DETAIL_WAITING_FOR_MERGE,
            ),
            (
                "closed_without_merging",
                github_api.PullRequestState(state="closed", merged=False, merge_commit_sha=None, base_ref="master"),
                True,
                "fixed",
                "fixed",
                QuarantineLiftState.CANCELLED,
                quarantine_lifts.DETAIL_CLOSED_WITHOUT_MERGE,
            ),
            (
                "merged_elsewhere",
                _merged(base_ref="release"),
                True,
                "fixed",
                "fixed",
                QuarantineLiftState.CANCELLED,
                "The pull request merged into release, not master",
            ),
            (
                "unreadable_pull_request",
                None,
                True,
                "fixed",
                "fixed",
                QuarantineLiftState.PENDING,
                quarantine_lifts.DETAIL_PULL_REQUEST_UNREADABLE,
            ),
        ],
    )
    def test_keeps_the_quarantine_unless_the_run_proves_the_fix(
        self,
        repo,
        quarantine_row,
        pending_request,
        github,
        name,
        pull_request,
        contains_merge,
        current_hash,
        baseline_hash,
        state,
        detail,
    ):
        github["pull_request_state"].return_value = pull_request
        github["commit_contains"].return_value = contains_merge
        run = _run(repo, branch="master", pr_number=None, commit_sha=MASTER_SHA)
        _snapshot(run, current_hash=current_hash, baseline_hash=baseline_hash)

        quarantine_lifts.reconcile_lift_requests(run.id)

        pending_request.refresh_from_db()
        assert (pending_request.state, pending_request.detail) == (state, detail)
        quarantine_row.refresh_from_db()
        assert quarantine_row.expires_at is None

    def test_supersedes_a_request_whose_quarantine_already_ended(self, repo, quarantine_row, pending_request, github):
        quarantine_row.expires_at = timezone.now() - timedelta(minutes=1)
        quarantine_row.save(update_fields=["expires_at"])
        run = _run(repo, branch="master", pr_number=None, commit_sha=MASTER_SHA)
        _snapshot(run, current_hash="fixed", baseline_hash="fixed")

        quarantine_lifts.reconcile_lift_requests(run.id)

        pending_request.refresh_from_db()
        assert pending_request.state == QuarantineLiftState.SUPERSEDED
        github["pull_request_state"].assert_not_called()

    @pytest.mark.parametrize(
        ("name", "branch", "pr_number", "is_partial", "default_branch"),
        [
            ("partial_default_branch_run", "master", None, True, "master"),
            ("pull_request_run", "fix-flake", PR_NUMBER, False, "master"),
            ("other_branch_without_pull_request", "release", None, False, "master"),
            ("default_branch_unknown", "master", None, False, None),
        ],
    )
    def test_ignores_a_run_that_cannot_prove_a_merge(
        self, repo, quarantine_row, pending_request, github, name, branch, pr_number, is_partial, default_branch
    ):
        github["default_branch_name"].return_value = default_branch
        run = _run(repo, branch=branch, pr_number=pr_number, commit_sha=MASTER_SHA, is_partial=is_partial)
        _snapshot(run, current_hash="fixed", baseline_hash="fixed")

        quarantine_lifts.reconcile_lift_requests(run.id)

        pending_request.refresh_from_db()
        assert pending_request.state == QuarantineLiftState.PENDING
        quarantine_row.refresh_from_db()
        assert quarantine_row.expires_at is None
        github["pull_request_state"].assert_not_called()

    @pytest.mark.parametrize(
        ("name", "pr_number", "has_pending", "enqueued"),
        [
            ("default_branch_run_with_pending_request", None, True, True),
            ("default_branch_run_without_pending_request", None, False, False),
            ("pull_request_run", PR_NUMBER, True, False),
        ],
    )
    def test_finish_processing_hands_a_full_run_to_the_lift_check(
        self, repo, quarantine_row, mocker, name, pr_number, has_pending, enqueued
    ):
        if has_pending:
            QuarantineLiftRequest.objects.create(
                team_id=repo.team_id,
                repo=repo,
                quarantine=quarantine_row,
                identifier=IDENTIFIER,
                run_type=RunType.STORYBOOK,
                pr_number=PR_NUMBER,
                expected_hash="fixed",
            )
        delay = mocker.patch("products.visual_review.backend.tasks.tasks.reconcile_quarantine_lifts.delay")
        run = _run(repo, branch="master", pr_number=pr_number, commit_sha=MASTER_SHA, status=RunStatus.PROCESSING)

        runs.finish_processing(run.id)

        assert delay.called is enqueued
