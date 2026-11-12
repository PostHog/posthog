"""Unit tests for logic/approvals.py — Approving snapshots and finalizing a run."""

from contextlib import ExitStack

import pytest
from unittest.mock import MagicMock

from django.db import connections, transaction
from django.test.utils import CaptureQueriesContext

from products.visual_review.backend.facade import api
from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import BaselineMode, ReviewState, RunStatus, RunType, SnapshotResult
from products.visual_review.backend.logic import (
    approvals,
    artifact_store,
    baselines,
    ci_status,
    errors,
    github_api,
    repos,
    run_queries,
    runs,
    toleration,
)
from products.visual_review.backend.logic.github_api import PullRequestState
from products.visual_review.backend.models import BaselineApproval, QuarantinedIdentifier, Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES
from products.visual_review.backend.tests.logic.ledger_fakes import SEED, FakeGit, LedgerFlow, button_flow


def _fake_github_job_api(method, repo, path, **kwargs):
    if method == "GET":
        return MagicMock(status_code=200, json=lambda: {"head_sha": "abc", "run_id": 777})
    return MagicMock(status_code=201)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestApproveRun:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test")

    def test_approve_run(self, repo, user, mocker):
        current_artifact, _ = artifact_store.get_or_create_artifact(
            repo_id=repo.id, content_hash="new_hash", storage_path="p/new"
        )
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="new_hash")],
                baseline_hashes={"Button": "old_hash"},
            ),
            team_id=repo.team_id,
        )

        # Classification happens at complete_run time
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"Button": "old_hash"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)

        updated = approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True)

        assert updated.approved is True
        assert updated.review_decision == "human_approved"
        assert updated.approved_at is not None
        assert updated.approved_by_id == user.id

        # Result should NOT be mutated - approval is recorded separately
        snapshot = updated.snapshots.first()
        assert snapshot is not None
        assert snapshot.result == SnapshotResult.CHANGED  # Result preserved
        assert snapshot.approved_hash == "new_hash"  # Approval recorded
        assert snapshot.reviewed_at is not None
        assert snapshot.reviewed_by_id == user.id

    def _completed_change_run(self, repo, mocker, identifiers=("A", "B")):
        for identifier in identifiers:
            artifact_store.get_or_create_artifact(
                repo_id=repo.id, content_hash=f"h{identifier.lower()}", storage_path=f"p/{identifier.lower()}"
            )
        baseline_hashes = {identifier: f"old{identifier.lower()}" for identifier in identifiers}
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[
                    SnapshotManifestItem(identifier=identifier, content_hash=f"h{identifier.lower()}")
                    for identifier in identifiers
                ],
                baseline_hashes=baseline_hashes,
            ),
            team_id=repo.team_id,
        )
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=(baseline_hashes, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)
        return run

    def test_finalize_requires_full_resolution(self, repo, user, mocker):
        # Finalize is all-or-nothing: it refuses while any changed/new snapshot is unreviewed.
        run = self._completed_change_run(repo, mocker)

        approvals.approve_snapshots(
            run_id=run.id, user_id=user.id, approved_snapshots=[{"identifier": "A", "new_hash": "ha"}]
        )
        with pytest.raises(errors.RunNotFullyResolvedError, match="B"):
            approvals.finalize_run(run_id=run.id, user_id=user.id, commit_to_github=False)

        # Resolving the rest lets it finalize.
        approvals.approve_snapshots(
            run_id=run.id, user_id=user.id, approved_snapshots=[{"identifier": "B", "new_hash": "hb"}]
        )
        updated = approvals.finalize_run(run_id=run.id, user_id=user.id, commit_to_github=False)
        assert updated.approved is True

    def test_finalize_leaves_tolerated_snapshot_alone(self, repo, user, mocker):
        # A tolerated snapshot resolves the run without being approved or committed.
        run = self._completed_change_run(repo, mocker)
        snap_b = run.snapshots.get(identifier="B")
        toleration.mark_snapshot_as_tolerated(run.id, snap_b.id, user.id, repo.team_id)

        updated = approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)

        assert updated.approved is True
        snapshots = {s.identifier: s for s in updated.snapshots.all()}
        assert snapshots["A"].review_state == ReviewState.APPROVED
        assert snapshots["B"].review_state == ReviewState.TOLERATED  # approve_all did not clobber it

    def test_finalize_is_idempotent_on_approved_run(self, repo, user, mocker):
        # Re-finalizing an already-finalized run is a no-op — no second commit/status/comment.
        run = self._completed_change_run(repo, mocker)
        approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)
        approved_at = run_queries.get_run_with_snapshots(run.id).approved_at

        again = approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)

        assert again.approved is True
        assert again.approved_at == approved_at  # unchanged — the second call did no work

    def test_approve_all_query_count_does_not_grow_with_the_snapshots(self, repo, user, mocker):
        query_counts = []
        for identifiers in (("A", "B"), ("C", "D", "E", "F", "G", "H")):
            run = self._completed_change_run(repo, mocker, identifiers)
            contexts = [CaptureQueriesContext(connections[alias]) for alias in sorted(PRODUCT_DATABASES)]
            with ExitStack() as stack:
                for context in contexts:
                    stack.enter_context(context)
                approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)
            query_counts.append(sum(len(context.captured_queries) for context in contexts))

        assert query_counts[0] == query_counts[1]

    @pytest.mark.parametrize(
        ("approve", "tolerate", "expected"),
        [
            ([], [], 2),
            (["A"], ["B"], 1),
            ([], ["A", "B"], 0),
        ],
    )
    def test_completing_again_reports_what_still_fails_the_gate(self, repo, user, mocker, approve, tolerate, expected):
        # A re-run of the completing CI job calls complete on a finished run and gates on this
        # count, so an untouched or approved-but-uncommitted change must still count.
        run = self._completed_change_run(repo, mocker)
        for identifier in tolerate:
            toleration.mark_snapshot_as_tolerated(
                run.id, run.snapshots.get(identifier=identifier).id, user.id, repo.team_id
            )
        approvals.approve_snapshots(
            run_id=run.id,
            user_id=user.id,
            approved_snapshots=[{"identifier": i, "new_hash": f"h{i.lower()}"} for i in approve],
        )

        assert api.complete_run(run.id, team_id=repo.team_id).summary.unresolved == expected

    @pytest.mark.parametrize("add_images", [True, False])
    def test_finalize_always_comments_and_forwards_add_images(self, repo, user, mocker, add_images):
        # The PR comment is always dispatched on finalize; add_images_to_comment_on_pr only
        # controls whether the snapshot images are embedded — forwarded to the task.
        run = self._completed_change_run(repo, mocker)
        mocker.patch.object(ci_status, "_post_commit_status")
        mocker.patch.object(transaction, "on_commit", side_effect=lambda fn, *args, **kwargs: fn())
        delay = mocker.patch("products.visual_review.backend.tasks.tasks.post_approval_comment.delay")

        approvals.finalize_run(
            run_id=run.id,
            user_id=user.id,
            approve_all=True,
            commit_to_github=True,
            add_images_to_comment_on_pr=add_images,
        )

        assert delay.called is True
        assert delay.call_args.args[2] is add_images

    @pytest.mark.parametrize(
        ("result", "approve_all", "expect_committed"),
        [
            ("new", False, True),
            ("changed", False, True),
            ("new", True, False),
            ("changed", True, False),
        ],
    )
    def test_finalize_commits_quarantined_only_when_approved_by_identifier(
        self, repo, user, mocker, result, approve_all, expect_committed
    ):
        # An explicit approval commits a quarantined snapshot, so its baseline can follow the story.
        # approve_all never touches quarantine, so a flapping hash cannot land in bulk.
        run = self._completed_quarantined_run(repo, mocker, result)
        if not approve_all:
            approvals.approve_snapshots(
                run_id=run.id, user_id=user.id, approved_snapshots=[{"identifier": "Q", "new_hash": "hq"}]
            )
        commit = mocker.patch.object(baselines, "_commit_baseline_to_github")
        mocker.patch.object(ci_status, "_post_commit_status")
        github = mocker.patch.object(github_api, "_github_api_request", side_effect=_fake_github_job_api)
        mocker.patch.object(transaction, "on_commit", side_effect=lambda fn, *args, **kwargs: fn())
        mocker.patch("products.visual_review.backend.tasks.tasks.post_approval_comment.delay")

        updated = approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=approve_all)

        assert updated.approved is True
        if expect_committed:
            assert commit.call_args.args[2] == [{"identifier": "Q", "new_hash": "hq"}]
        else:
            assert commit.called is False
        reruns = [c.args[2] for c in github.call_args_list if c.args[0] == "POST"]
        assert reruns == ([] if expect_committed else ["actions/jobs/42/rerun"])

    def _completed_quarantined_run(self, repo, mocker, result):
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="hq", storage_path="p/q")
        baseline = {} if result == "new" else {"Q": "oldq"}
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=7,
                snapshots=[SnapshotManifestItem(identifier="Q", content_hash="hq")],
                baseline_hashes=baseline,
                metadata={"github_check_run_id": "42", "github_run_id": "777"},
            ),
            team_id=repo.team_id,
        )
        QuarantinedIdentifier.objects.create(
            repo=repo, team_id=repo.team_id, identifier="Q", run_type=RunType.STORYBOOK, reason="test"
        )
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=(baseline, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)
        return run


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestApproveSnapshots:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=99998, repo_full_name="org/test-snap")

    def test_approve_single_snapshot_db_only(self, repo, user, mocker):
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="new_hash", storage_path="p/new")
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="new_hash")],
                baseline_hashes={"Button": "old_hash"},
            ),
            team_id=repo.team_id,
        )
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"Button": "old_hash"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)

        updated = approvals.approve_snapshots(
            run_id=run.id,
            user_id=user.id,
            approved_snapshots=[{"identifier": "Button", "new_hash": "new_hash"}],
        )

        snapshot = updated.snapshots.first()
        assert snapshot is not None
        assert snapshot.review_state == "approved"
        assert snapshot.approved_hash == "new_hash"

        # Run-level state should NOT change
        assert updated.approved is False
        assert updated.review_decision == "pending"


def _changed_run(git: FakeGit, flow: LedgerFlow) -> Run:
    git.open_pull_request(1, git.commit("p1a", SEED))
    return flow.run("p1a", {"Button": "b1"}, branch="feat", pr_number=1)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestFinalizeByBaselineMode:
    def test_shadow_finalize_makes_no_github_request_of_its_own(self, team, user, mocker):
        _repo, git, flow = button_flow(team.id, BaselineMode.SHADOW, mocker, external_id=99997)
        run = _changed_run(git, flow)
        pull_request_state = mocker.patch.object(github_api, "pull_request_state")

        approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True)

        assert pull_request_state.called is False

    @pytest.mark.parametrize(
        ("pull_request", "run_fields", "error"),
        [
            (
                PullRequestState(state="closed", merged=True, merge_commit_sha="m1", base_ref="master", head_sha="p1a"),
                {},
                errors.PullRequestClosedError,
            ),
            (
                PullRequestState(state="open", merged=False, merge_commit_sha=None, base_ref="master", head_sha="p1b"),
                {},
                errors.PRSHAMismatchError,
            ),
            (None, {"metadata": {}}, errors.RunWithoutBaselineRecordError),
            (None, {"pr_number": None}, errors.RunWithoutPullRequestError),
        ],
    )
    def test_ledger_finalize_refuses_before_any_write(self, team, user, mocker, pull_request, run_fields, error):
        repo, git, flow = button_flow(team.id, BaselineMode.LEDGER, mocker, external_id=99997)
        run = _changed_run(git, flow)
        if pull_request is not None:
            git.pull_requests[1] = pull_request
        if run_fields:
            Run.objects.filter(id=run.id).update(**run_fields)

        with pytest.raises(error):
            approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True)

        run.refresh_from_db()
        assert run.approved is False
        assert not run.snapshots.filter(review_state=ReviewState.APPROVED).exists()
        assert not BaselineApproval.objects.filter(repo=repo).exists()

    def test_yaml_finalize_refuses_a_closed_pull_request(self, team, user, mocker):
        repo = repos.create_repo(team_id=team.id, repo_external_id=99997, repo_full_name="org/test-modes")
        run = Run.objects.create(
            repo=repo,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="p1a",
            branch="feat",
            pr_number=1,
            status=RunStatus.COMPLETED,
        )
        RunSnapshot.objects.create(
            run=run,
            team_id=repo.team_id,
            identifier="Button",
            result=SnapshotResult.CHANGED,
            current_hash="b1",
            baseline_hash="b0",
            approved_hash="b1",
            review_state=ReviewState.APPROVED,
        )
        integration = MagicMock()
        integration.api_request.return_value = MagicMock(
            status_code=200, json=lambda: {"head": {"ref": "feat", "sha": "p1a"}, "state": "closed", "merged": True}
        )
        mocker.patch.object(github_api, "get_github_integration_for_repo", return_value=integration)

        with pytest.raises(errors.PullRequestClosedError):
            approvals.finalize_run(run_id=run.id, user_id=user.id)

        run.refresh_from_db()
        assert run.approved is False
