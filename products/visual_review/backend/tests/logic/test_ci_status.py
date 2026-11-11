"""Unit tests for logic/ci_status.py — Commit statuses and CI job reruns."""

from datetime import timedelta

import pytest
from unittest.mock import MagicMock

from django.utils import timezone

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade import api
from products.visual_review.backend.facade.contracts import CreateRunInput, NoRunNeededInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import (
    BaselineMode,
    NoRunNeededOutcome,
    ReviewState,
    RunGate,
    RunPurpose,
    RunStatus,
    RunType,
    SnapshotResult,
)
from products.visual_review.backend.logic import (
    approvals,
    artifact_store,
    ci_status,
    commit_status,
    errors,
    ledger,
    quarantine,
    repos,
    runs,
    toleration,
)
from products.visual_review.backend.logic.baseline_record import METADATA_KEY
from products.visual_review.backend.models import BaselineApproval, QuarantinedIdentifier, Repo, Run, RunSnapshot
from products.visual_review.backend.tasks import tasks
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES
from products.visual_review.backend.tests.logic.ledger_fakes import (
    SEED,
    FakeGit,
    approve,
    make_record,
    move_ledger,
    set_baseline_mode,
)


@pytest.mark.parametrize(
    ("commit_sha", "lookup_error", "expected", "expected_path"),
    [
        pytest.param("a" * 40, None, ci_status.StatusPost.POSTED, f"/repos/org/repo/statuses/{'a' * 40}", id="posted"),
        pytest.param(
            "../../pulls/1#x",
            None,
            ci_status.StatusPost.POSTED,
            "/repos/org/repo/statuses/..%2F..%2Fpulls%2F1%23x",
            id="sha_is_one_path_segment",
        ),
        pytest.param(
            "a" * 40,
            errors.GitHubIntegrationNotFoundError("no integration"),
            ci_status.StatusPost.SKIPPED,
            None,
            id="no_integration",
        ),
        pytest.param("a" * 40, RuntimeError("lookup failed"), ci_status.StatusPost.REFUSED, None, id="lookup_failed"),
    ],
)
def test_send_commit_status(mocker, commit_sha, lookup_error, expected, expected_path) -> None:
    github = MagicMock()
    github.api_request.return_value = MagicMock(status_code=201)
    mocker.patch.object(
        ci_status.github_api, "get_github_integration_for_repo", return_value=github, side_effect=lookup_error
    )

    posted = ci_status._send_commit_status(
        Repo(repo_full_name="org/repo"), commit_sha, context="ctx", state="success", description="ok", target_url=None
    )

    assert posted == expected
    paths = [call.args[1] for call in github.api_request.call_args_list]
    assert paths == ([expected_path] if expected_path else [])


@pytest.mark.django_db(transaction=True, databases=PRODUCT_DATABASES)
class TestCommitStatusChecks:
    """Test that GitHub commit status checks are posted at state transitions."""

    @pytest.fixture
    def github_repo(self, team, mock_github_integration):
        return Repo.objects.create(
            team_id=team.id,
            repo_external_id=55555,
            repo_full_name="test-org/test-repo",
            baseline_file_paths={"storybook": ".snapshots.yml"},
        )

    def test_create_run_posts_pending_status(self, github_repo, mock_github_api):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=github_repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                pr_number=1,
                snapshots=[SnapshotManifestItem(identifier="snap", content_hash="h1")],
                baseline_hashes={},
            ),
            team_id=github_repo.team_id,
        )

        assert len(mock_github_api.status_checks) == 1
        check = mock_github_api.status_checks[0]
        assert check["state"] == "pending"
        assert check["context"] == "PostHog Visual Review / storybook"
        assert f"/visual-review/runs/{run.id}" in check["target_url"]

    @pytest.mark.parametrize(
        ("quarantined_difference", "description"),
        [
            (None, "No visual changes"),
            ("changed", "No gating changes; 1 quarantined snapshot differs"),
            ("removed", "No gating changes; 1 quarantined snapshot differs"),
        ],
    )
    def test_complete_run_posts_success_when_no_changes(
        self, github_repo, mock_github_api, mocker, quarantined_difference, description
    ):
        snapshots = [SnapshotManifestItem(identifier="snap", content_hash="same")]
        baseline = {"snap": "same"}
        if quarantined_difference:
            if quarantined_difference == "changed":
                snapshots.append(SnapshotManifestItem(identifier="flaky", content_hash="drifted"))
            baseline["flaky"] = "base"
            QuarantinedIdentifier.objects.create(
                team_id=github_repo.team_id,
                repo=github_repo,
                identifier="flaky",
                run_type=RunType.STORYBOOK,
                reason="flaky",
            )
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=github_repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                pr_number=1,
                snapshots=snapshots,
                baseline_hashes={},
            ),
            team_id=github_repo.team_id,
        )

        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=(baseline, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        if quarantined_difference:
            runs.finish_processing(run.id)

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "success"
        assert statuses[-1]["description"] == description
        # A full run posts to the gating context that branch protection evaluates.
        assert statuses[-1]["context"] == "PostHog Visual Review / storybook"

    def test_complete_run_partial_annotates_posted_status(self, github_repo, mock_github_api, mocker):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=github_repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="feature-x",
                pr_number=7,
                snapshots=[SnapshotManifestItem(identifier="snap", content_hash="same")],
                baseline_hashes={"snap": "same"},
                is_partial=True,
            ),
            team_id=github_repo.team_id,
        )

        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"snap": "same", "deleted": "h2"}, 0),
        )
        mocker.patch("products.visual_review.backend.logic.baselines._run_is_on_default_branch", return_value=False)
        runs.complete_run(run.id)

        # A partial run suppresses removal detection, so it must never satisfy
        # the gating status context branch protection evaluates. It posts to a
        # separate "(partial)" context instead, and the description discloses it.
        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "success"
        assert statuses[-1]["description"] == "No visual changes (partial run)"
        assert statuses[-1]["context"] == "PostHog Visual Review / storybook (partial)"
        # The gating context is never posted green by a partial run.
        gating_context = "PostHog Visual Review / storybook"
        assert all(s["context"] != gating_context for s in statuses)

    def test_complete_run_posts_comment_when_changes_detected(self, github_repo, mock_github_api, mocker):
        github_repo.enable_pr_comments = True
        github_repo.save(update_fields=["enable_pr_comments"])

        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=github_repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                pr_number=1,
                snapshots=[
                    SnapshotManifestItem(identifier="changed", content_hash="new_h"),
                    SnapshotManifestItem(identifier="added", content_hash="brand_new"),
                ],
                baseline_hashes={"changed": "old_h"},
            ),
            team_id=github_repo.team_id,
        )

        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"changed": "old_h"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)

        statuses = mock_github_api.status_checks
        # VR is the gate — unapproved changes post failure
        assert statuses[-1]["state"] == "failure"
        assert "1 changed" in statuses[-1]["description"]
        assert "1 new" in statuses[-1]["description"]
        assert len(mock_github_api.issue_comments) == 1
        assert mock_github_api.issue_comments[0]["action"] == "created"
        comment = mock_github_api.issue_comments[0]["body"]
        assert "Review and approve in PostHog Visual Review" in comment
        assert f"/visual-review/runs/{run.id}" in comment
        # Verify comment ID stored for future updates
        run.refresh_from_db()
        assert run.metadata["github_comment_id"] is not None

    def test_subsequent_run_posts_a_new_comment(self, github_repo, mock_github_api):
        github_repo.enable_pr_comments = True
        github_repo.save(update_fields=["enable_pr_comments"])

        run1, _ = runs.create_run(
            CreateRunInput(
                repo_id=github_repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc111",
                branch="main",
                pr_number=1,
                snapshots=[SnapshotManifestItem(identifier="changed", content_hash="new_h")],
                baseline_hashes={"changed": "old_h"},
            ),
            team_id=github_repo.team_id,
        )
        runs.finish_processing(run1.id)

        run2, _ = runs.create_run(
            CreateRunInput(
                repo_id=github_repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc222",
                branch="main",
                pr_number=1,
                snapshots=[SnapshotManifestItem(identifier="changed", content_hash="newer_h")],
                baseline_hashes={"changed": "old_h"},
            ),
            team_id=github_repo.team_id,
        )
        runs.finish_processing(run2.id)

        # A silent edit of the first comment gives reviewers no cue that new changes
        # arrived, so the second run deletes it and posts its prompt at the bottom.
        created = [c for c in mock_github_api.issue_comments if c["action"] == "created"]
        deleted = [c for c in mock_github_api.issue_comments if c["action"] == "deleted"]
        assert len(created) == 2
        assert [c["id"] for c in deleted] == [created[0]["id"]]
        assert f"/visual-review/runs/{run2.id}" in created[1]["body"]

    def test_complete_run_does_not_comment_twice_on_retry(self, github_repo, mock_github_api):
        github_repo.enable_pr_comments = True
        github_repo.save(update_fields=["enable_pr_comments"])

        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=github_repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                pr_number=1,
                snapshots=[SnapshotManifestItem(identifier="changed", content_hash="new_h")],
                baseline_hashes={"changed": "old_h"},
            ),
            team_id=github_repo.team_id,
        )

        runs.finish_processing(run.id)
        runs.finish_processing(run.id)

        assert len(mock_github_api.issue_comments) == 1

    @pytest.mark.parametrize(
        "enable_pr_comments, pr_number, snapshots, baseline_hashes, purpose",
        [
            (
                False,
                1,
                [SnapshotManifestItem(identifier="changed", content_hash="new_h")],
                {"changed": "old_h"},
                "review",
            ),
            (
                True,
                None,
                [SnapshotManifestItem(identifier="changed", content_hash="new_h")],
                {"changed": "old_h"},
                "review",
            ),
            (True, 1, [SnapshotManifestItem(identifier="snap", content_hash="same")], {"snap": "same"}, "review"),
            (
                True,
                1,
                [SnapshotManifestItem(identifier="changed", content_hash="new_h")],
                {"changed": "old_h"},
                "observe",
            ),
        ],
        ids=["toggle_off", "no_pr", "no_changes", "observe_purpose"],
    )
    def test_complete_run_does_not_comment(
        self, enable_pr_comments, pr_number, snapshots, baseline_hashes, purpose, github_repo, mock_github_api, mocker
    ):
        if enable_pr_comments:
            github_repo.enable_pr_comments = True
            github_repo.save(update_fields=["enable_pr_comments"])

        # Mock baseline for classification at complete time
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=(dict(baseline_hashes), 0),
        )

        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=github_repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                pr_number=pr_number,
                snapshots=snapshots,
                baseline_hashes=baseline_hashes,
                purpose=purpose,
            ),
            team_id=github_repo.team_id,
        )

        runs.complete_run(run.id)

        assert len(mock_github_api.issue_comments) == 0

    def test_complete_run_posts_error_on_failure(self, github_repo, mock_github_api):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=github_repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                pr_number=1,
                snapshots=[],
                baseline_hashes={},
            ),
            team_id=github_repo.team_id,
        )

        runs.finish_processing(run.id, error_message="Diff processing failed")

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "error"
        assert "failed" in statuses[-1]["description"].lower()
        assert len(mock_github_api.issue_comments) == 0

    def test_observe_run_with_changes_posts_green_tracking_status(self, github_repo, mock_github_api, mocker):
        # Default-branch (observe) runs are tracking-only: a visual change posts a green,
        # informational status — never a blocking failure — and no review-prompt comment.
        github_repo.enable_pr_comments = True
        github_repo.save(update_fields=["enable_pr_comments"])

        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=github_repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="master",
                pr_number=None,
                snapshots=[
                    SnapshotManifestItem(identifier="changed", content_hash="new_h"),
                    SnapshotManifestItem(identifier="added", content_hash="brand_new"),
                ],
                baseline_hashes={"changed": "old_h"},
                purpose="observe",
            ),
            team_id=github_repo.team_id,
        )

        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"changed": "old_h"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "success"
        assert statuses[-1]["description"] == "Tracking only: 1 changed, 1 new recorded"
        # Observe runs post to a separate, non-gating context. purpose is client-supplied,
        # so greening the gating context would let an observe run bypass branch protection
        # on a PR head SHA — the gating context must never be touched by an observe run.
        assert statuses[-1]["context"] == "PostHog Visual Review / storybook (tracking)"
        assert all(s["context"] != "PostHog Visual Review / storybook" for s in statuses)
        assert len(mock_github_api.issue_comments) == 0

    def test_observe_run_without_changes_posts_green_tracking_status(self, github_repo, mock_github_api, mocker):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=github_repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="master",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="snap", content_hash="same")],
                baseline_hashes={"snap": "same"},
                purpose="observe",
            ),
            team_id=github_repo.team_id,
        )

        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"snap": "same"}, 0),
        )
        runs.complete_run(run.id)

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "success"
        assert statuses[-1]["description"] == "Tracking only: no visual changes"
        assert statuses[-1]["context"] == "PostHog Visual Review / storybook (tracking)"

    def test_approve_run_posts_success(self, github_repo, mock_github_api, user):
        artifact_store.get_or_create_artifact(repo_id=github_repo.id, content_hash="new_h", storage_path="p/new")
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=github_repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="snap", content_hash="new_h")],
                baseline_hashes={"snap": "old_h"},
            ),
            team_id=github_repo.team_id,
        )
        runs.finish_processing(run.id)

        approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True)

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "success"
        assert "approved" in statuses[-1]["description"].lower()

    def test_recompute_does_not_green_approved_but_uncommitted(self, github_repo, mock_github_api, user, mocker):
        # Approving in the DB does not commit the baseline, so recompute must keep the gate red —
        # otherwise re-running CI would re-detect the change. Only finalize (which commits) greens it.
        artifact_store.get_or_create_artifact(repo_id=github_repo.id, content_hash="new_h", storage_path="p/new")
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=github_repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="snap", content_hash="new_h")],
                baseline_hashes={"snap": "old_h"},
            ),
            team_id=github_repo.team_id,
        )
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"snap": "old_h"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)

        approvals.approve_snapshots(
            run_id=run.id, user_id=user.id, approved_snapshots=[{"identifier": "snap", "new_hash": "new_h"}]
        )
        runs.recompute_run(run.id, team_id=github_repo.team_id)

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "failure"
        assert "awaiting commit" in statuses[-1]["description"].lower()

    def test_no_status_without_github_integration(self, team):
        """Status checks are silently skipped when no GitHub integration exists."""
        repo = repos.create_repo(team_id=team.id, repo_external_id=77777, repo_full_name="org/no-github")

        # No mock_github_api/mock_github_integration — should not raise
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                pr_number=1,
                snapshots=[SnapshotManifestItem(identifier="snap", content_hash="h1")],
                baseline_hashes={},
            ),
            team_id=repo.team_id,
        )

        runs.finish_processing(run.id)

    def test_no_status_without_repo_full_name(self, team, mock_github_integration, mock_github_api):
        """Status checks are silently skipped when repo has no repo_full_name."""
        repo = Repo.objects.create(
            team_id=team.id,
            repo_external_id=88888,
            repo_full_name="",
        )

        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                pr_number=1,
                snapshots=[SnapshotManifestItem(identifier="snap", content_hash="h1")],
                baseline_hashes={},
            ),
            team_id=repo.team_id,
        )

        runs.finish_processing(run.id)

        assert len(mock_github_api.status_checks) == 0


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRerunGithubJob:
    """Tests for _rerun_github_job SHA validation."""

    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=55555, repo_full_name="org/test-repo")

    def _make_run(self, repo: "Repo", commit_sha: str = "abc123def456", workflow_run_id: str | None = "98765") -> "Run":
        metadata: dict = {"github_check_run_id": "72855643533"}
        if workflow_run_id is not None:
            metadata["github_run_id"] = workflow_run_id
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha=commit_sha,
                branch="feature",
                pr_number=1,
                snapshots=[],
                metadata=metadata,
            ),
            team_id=repo.team_id,
        )
        return run

    def test_rejects_non_digit_check_run_id(self, repo):
        run = self._make_run(repo)
        success, error = ci_status._rerun_github_job(run, "not-a-number")
        assert success is False
        assert error == "Invalid check run ID"

    def test_rejects_when_workflow_run_id_missing(self, repo):
        run = self._make_run(repo, workflow_run_id=None)
        success, error = ci_status._rerun_github_job(run, "72855643533")
        assert success is False
        assert error == "Workflow run ID not recorded for this run"

    def test_rejects_when_sha_does_not_match(self, repo, mocker):
        run = self._make_run(repo, commit_sha="abc123")
        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"head_sha": "different_sha_entirely", "run_id": 98765}
        mocker.patch("products.visual_review.backend.logic.github_api._github_api_request", return_value=mock_response)

        success, error = ci_status._rerun_github_job(run, "72855643533")

        assert success is False
        assert error == "Check run does not belong to this commit"

    def test_rejects_when_workflow_run_does_not_match(self, repo, mocker):
        commit_sha = "abc123def456"
        run = self._make_run(repo, commit_sha=commit_sha, workflow_run_id="98765")
        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"head_sha": commit_sha, "run_id": 11111}
        mocker.patch("products.visual_review.backend.logic.github_api._github_api_request", return_value=mock_response)

        success, error = ci_status._rerun_github_job(run, "72855643533")

        assert success is False
        assert error == "CI job does not belong to this run's workflow"

    def test_rejects_when_check_run_fetch_fails(self, repo, mocker):
        run = self._make_run(repo)
        mock_response = mocker.MagicMock()
        mock_response.status_code = 404
        mocker.patch("products.visual_review.backend.logic.github_api._github_api_request", return_value=mock_response)

        success, error = ci_status._rerun_github_job(run, "72855643533")

        assert success is False
        assert error is not None
        assert "404" in error

    def test_triggers_rerun_when_sha_and_workflow_match(self, repo, mocker):
        commit_sha = "abc123def456"
        run = self._make_run(repo, commit_sha=commit_sha, workflow_run_id="98765")

        job_response = mocker.MagicMock()
        job_response.status_code = 200
        job_response.json.return_value = {"head_sha": commit_sha, "run_id": 98765}

        rerun_response = mocker.MagicMock()
        rerun_response.status_code = 201

        mocker.patch(
            "products.visual_review.backend.logic.github_api._github_api_request",
            side_effect=[job_response, rerun_response],
        )

        success, error = ci_status._rerun_github_job(run, "72855643533")

        assert success is True
        assert error is None


def _run(repo: Repo, *, minute: int = 0, **fields) -> Run:
    defaults = {
        "run_type": RunType.STORYBOOK,
        "commit_sha": "c1",
        "branch": "feat",
        "pr_number": 1,
        "purpose": RunPurpose.REVIEW,
        "status": RunStatus.PROCESSING,
    }
    run = Run.objects.create(repo=repo, team_id=repo.team_id, **{**defaults, **fields})
    # Two runs created in a row can share a timestamp, and the newest run decides the status.
    created_at = timezone.now() - timedelta(hours=1) + timedelta(minutes=minute)
    Run.objects.filter(id=run.id).update(created_at=created_at)
    run.created_at = created_at
    return run


def _snapshot(run: Run, identifier: str, result: str, review_state: str = "") -> RunSnapshot:
    return RunSnapshot.objects.create(
        run=run,
        team_id=run.team_id,
        identifier=identifier,
        result=result,
        current_hash=f"{identifier}-new",
        baseline_hash=f"{identifier}-old",
        review_state=review_state,
    )


def _posted(sender) -> list[tuple[str, str, str]]:
    return [(c.kwargs["context"], c.kwargs["state"], c.kwargs["description"]) for c in sender.call_args_list]


def _facts(**fields) -> commit_status.RunFacts:
    defaults = {
        "status": RunStatus.COMPLETED,
        "error_message": "",
        "purpose": RunPurpose.REVIEW,
        "approved": False,
        "is_partial": False,
        "tracking": False,
        "changes_summary": "",
    }
    return commit_status.RunFacts(**{**defaults, **fields})


def _verdict(state: str, description: str) -> commit_status.StatusVerdict:
    return commit_status.StatusVerdict(state=state, description=description)


STALE_ONE = _verdict("failure", "Baseline changed after approval: 1 snapshot. Update the branch and review again")
CHANGES_DETECTED = _verdict("failure", "Visual changes detected: 1 changed")


class TestStatusVerdict:
    @pytest.mark.parametrize(
        ("facts", "expected"),
        [
            pytest.param(
                _facts(status=RunStatus.PENDING), _verdict("pending", "Visual review in progress"), id="pending"
            ),
            pytest.param(
                _facts(status=RunStatus.PROCESSING, error_message="Diff processing failed"),
                _verdict("pending", "Visual review in progress"),
                id="processing_comes_before_an_error",
            ),
            pytest.param(
                _facts(status=RunStatus.FAILED, error_message="Diff processing failed"),
                _verdict("error", "Visual review failed: Diff processing failed"),
                id="failed",
            ),
            pytest.param(
                _facts(error_message="x" * 150),
                _verdict("error", f"Visual review failed: {'x' * 100}"),
                id="completed_with_an_error_message",
            ),
            pytest.param(
                _facts(changes_summary="1 changed", unresolved=1),
                CHANGES_DETECTED,
                id="pull_request_run_with_snapshots_to_review",
            ),
            pytest.param(
                _facts(changes_summary="1 changed", awaiting_finalize=1),
                _verdict("failure", "1 approved change(s) not finalized. Finalize the run to pass this check"),
                id="pull_request_run_with_approved_changes_not_finalized",
            ),
            pytest.param(_facts(), _verdict("success", "No visual changes"), id="clean_pull_request_run"),
            pytest.param(
                _facts(hidden_by_quarantine=2),
                _verdict("success", "No gating changes; 2 quarantined snapshots differ"),
                id="clean_pull_request_run_with_quarantined_changes",
            ),
            pytest.param(
                _facts(approved=True, changes_summary="1 changed"),
                _verdict("success", "Visual changes approved"),
                id="finalized_pull_request_run",
            ),
            pytest.param(
                _facts(approved=True, changes_summary="1 changed", stale_approvals=1),
                STALE_ONE,
                id="finalized_on_a_stale_approval",
            ),
            pytest.param(
                _facts(stale_approvals=2),
                _verdict("failure", "Baseline changed after approval: 2 snapshots. Update the branch and review again"),
                id="clean_on_two_stale_approvals",
            ),
            pytest.param(
                _facts(changes_summary="1 changed", unresolved=1, stale_approvals=1),
                CHANGES_DETECTED,
                id="a_review_failure_comes_before_a_stale_approval",
            ),
            pytest.param(
                _facts(purpose=RunPurpose.OBSERVE, changes_summary="1 changed"),
                _verdict("failure", "Visual changes nobody approved: 1 changed"),
                id="merge_queue_run_with_drift",
            ),
            pytest.param(
                _facts(purpose=RunPurpose.OBSERVE, hidden_by_quarantine=1),
                _verdict("success", "No gating changes; 1 quarantined snapshot differs"),
                id="clean_merge_queue_run",
            ),
            pytest.param(
                _facts(purpose=RunPurpose.OBSERVE, tracking=True, changes_summary="1 changed"),
                _verdict("success", "Tracking only: 1 changed recorded"),
                id="default_branch_run_with_drift",
            ),
            pytest.param(
                _facts(purpose=RunPurpose.OBSERVE, tracking=True),
                _verdict("success", "Tracking only: no visual changes"),
                id="clean_default_branch_run",
            ),
            pytest.param(
                _facts(purpose=RunPurpose.OBSERVE, tracking=True, status=RunStatus.FAILED, error_message="boom"),
                _verdict("error", "Visual review failed: boom"),
                id="failed_default_branch_run",
            ),
            pytest.param(
                _facts(is_partial=True, changes_summary="1 changed", unresolved=1),
                _verdict("failure", "Visual changes detected: 1 changed (partial run)"),
                id="partial_run",
            ),
            pytest.param(
                _facts(is_partial=True, purpose=RunPurpose.OBSERVE, tracking=True),
                _verdict("success", "Tracking only: no visual changes"),
                id="partial_default_branch_run",
            ),
        ],
    )
    def test_status_table(self, facts, expected) -> None:
        assert commit_status.status_verdict(facts) == expected


def _refuse_every_post(sender, repo: Repo) -> None:
    sender.return_value = ci_status.StatusPost.REFUSED


def _create_a_run_on_every_post(sender, repo: Repo) -> None:
    def a_new_run_arrives(*args, **kwargs):
        _run(repo, branch=f"rerun-{sender.call_count}", minute=sender.call_count)
        return ci_status.StatusPost.POSTED

    sender.side_effect = a_new_run_arrives


def _approve_button(run: Run, snapshot: RunSnapshot, user_id: int) -> None:
    approvals.approve_snapshots(
        run_id=run.id, user_id=user_id, approved_snapshots=[{"identifier": "Button", "new_hash": "Button-new"}]
    )


def _tolerate_button(run: Run, snapshot: RunSnapshot, user_id: int) -> None:
    toleration.mark_snapshot_as_tolerated(run.id, snapshot.id, user_id, run.team_id)


def _quarantine_button(run: Run, snapshot: RunSnapshot, user_id: int) -> None:
    quarantine.quarantine_identifier(
        repo_id=run.repo_id,
        identifier="Button",
        run_type=RunType.STORYBOOK,
        reason="flaky",
        user_id=user_id,
        team_id=run.team_id,
    )


def _finalized_run_on_a_moved_baseline(repo: Repo, gate: RunGate) -> Run:
    ledger.seed(repo, SEED, {RunType.STORYBOOK: {"Button": "b0"}})
    approval = approve(repo, 1, "Button", "Button-new")
    run = _run(
        repo, status=RunStatus.COMPLETED, approved=True, gate=gate, metadata={METADATA_KEY: make_record().to_json()}
    )
    _snapshot(run, "Button", SnapshotResult.CHANGED, review_state=ReviewState.APPROVED)
    BaselineApproval.objects.filter(id=approval.id).update(source_run=run)
    move_ledger(repo, "Button", "b9", previous_hash="b0")
    return run


def _no_push(repo: Repo, run: Run) -> None:
    pass


def _push_again(repo: Repo, run: Run) -> None:
    newer = _run(repo, commit_sha="c2", branch="feat-pushed-again")
    Run.objects.filter(id=run.id).update(superseded_by=newer)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestStatusByCommit:
    GATING = "PostHog Visual Review / storybook"
    NO_RUN_NEEDED = (GATING, "success", commit_status.NO_RUN_NEEDED_DESCRIPTION)

    @pytest.fixture
    def repo(self, team, mocker) -> Repo:
        FakeGit(mocker, SEED)
        repo = repos.create_repo(team_id=team.id, repo_external_id=55601, repo_full_name="org/status-by-commit")
        set_baseline_mode(repo, BaselineMode.LEDGER)
        return repo

    @pytest.fixture
    def sender(self, mocker):
        return mocker.patch.object(ci_status, "_send_commit_status", return_value=ci_status.StatusPost.POSTED)

    @pytest.mark.parametrize("mode", [BaselineMode.SHADOW, BaselineMode.LEDGER])
    @pytest.mark.parametrize(
        ("fields", "result", "expected"),
        [
            pytest.param(
                {"is_partial": True},
                SnapshotResult.UNCHANGED,
                (GATING, "success", "No visual changes (partial run)"),
                id="partial_pull_request_run",
            ),
            pytest.param(
                {"purpose": RunPurpose.OBSERVE, "branch": "trunk-merge/q1", "pr_number": None},
                SnapshotResult.CHANGED,
                (GATING, "failure", "Visual changes nobody approved: 1 changed"),
                id="queue_run_with_drift",
            ),
            pytest.param(
                {"purpose": RunPurpose.OBSERVE, "branch": "master", "pr_number": None},
                SnapshotResult.CHANGED,
                (f"{GATING} (tracking)", "success", "Tracking only: 1 changed recorded"),
                id="default_branch_run_with_drift",
            ),
        ],
    )
    def test_with_the_status_gate_on_completion_posts_the_commit_verdict(
        self, repo, sender, django_capture_on_commit_callbacks, mode, fields, result, expected
    ) -> None:
        set_baseline_mode(repo, mode, status_gate=True)
        run = _run(repo, **fields)
        _snapshot(run, "Button", result)

        with django_capture_on_commit_callbacks(using=WRITER_DB, execute=True):
            runs.finish_processing(run.id)

        assert _posted(sender)[-1] == expected

    @pytest.mark.parametrize("mode", [BaselineMode.YAML, BaselineMode.SHADOW])
    @pytest.mark.parametrize(
        ("fields", "result", "expected"),
        [
            pytest.param(
                {"is_partial": True},
                SnapshotResult.UNCHANGED,
                (f"{GATING} (partial)", "success", "No visual changes (partial run)"),
                id="partial_pull_request_run",
            ),
            pytest.param(
                {"purpose": RunPurpose.OBSERVE, "branch": "trunk-merge/q1", "pr_number": None},
                SnapshotResult.CHANGED,
                (f"{GATING} (tracking)", "success", "Tracking only: 1 changed recorded"),
                id="queue_run_with_drift",
            ),
            pytest.param(
                {"purpose": RunPurpose.OBSERVE, "branch": "master", "pr_number": None},
                SnapshotResult.CHANGED,
                (f"{GATING} (tracking)", "success", "Tracking only: 1 changed recorded"),
                id="default_branch_run_with_drift",
            ),
        ],
    )
    def test_with_the_status_gate_off_completion_posts_by_run_kind(
        self, repo, sender, django_capture_on_commit_callbacks, mode, fields, result, expected
    ) -> None:
        set_baseline_mode(repo, mode, status_gate=False)
        run = _run(repo, **fields)
        _snapshot(run, "Button", result)

        with django_capture_on_commit_callbacks(using=WRITER_DB, execute=True):
            runs.finish_processing(run.id)

        assert _posted(sender)[-1] == expected

    def test_an_older_run_that_finishes_late_posts_the_newer_runs_verdict(
        self, repo, sender, django_capture_on_commit_callbacks
    ) -> None:
        older = _run(repo)
        _snapshot(older, "Button", SnapshotResult.CHANGED)
        newer = _run(repo, branch="feat-rerun", status=RunStatus.COMPLETED, minute=1)

        with django_capture_on_commit_callbacks(using=WRITER_DB, execute=True):
            runs.finish_processing(older.id)

        assert _posted(sender) == [(self.GATING, "success", "No visual changes")]
        assert str(newer.id) in sender.call_args.kwargs["target_url"]

    def test_a_verdict_that_changes_during_the_post_ends_on_the_newer_one(self, repo, sender) -> None:
        run = _run(repo, status=RunStatus.COMPLETED)
        created: list[Run] = []

        def a_new_run_arrives_while_posting(*args, **kwargs):
            if not created:
                created.append(_run(repo, branch="feat-rerun", minute=1))
            return ci_status.StatusPost.POSTED

        sender.side_effect = a_new_run_arrives_while_posting

        commit_status.publish(repo, run.commit_sha, run.run_type)

        assert [state for _context, state, _description in _posted(sender)] == ["success", "pending"]
        assert str(created[0].id) in sender.call_args.kwargs["target_url"]

    def test_a_recompute_posts_only_after_its_transaction_commits(
        self, repo, sender, django_capture_on_commit_callbacks
    ) -> None:
        run = _run(repo, status=RunStatus.COMPLETED)
        _snapshot(run, "Button", SnapshotResult.CHANGED)

        with django_capture_on_commit_callbacks(using=WRITER_DB) as callbacks:
            runs.recompute_run(run.id, team_id=repo.team_id)
        assert sender.call_count == 0

        for callback in callbacks:
            callback()
        assert _posted(sender) == [(self.GATING, CHANGES_DETECTED.state, CHANGES_DETECTED.description)]

    @pytest.mark.parametrize(
        ("break_the_posts", "posts"),
        [
            pytest.param(_refuse_every_post, 1, id="refused"),
            pytest.param(_create_a_run_on_every_post, commit_status.MAX_ROUNDS, id="keeps_changing"),
        ],
    )
    def test_a_status_that_does_not_settle_is_retried_by_a_task_that_publishes(
        self, repo, sender, mocker, django_capture_on_commit_callbacks, break_the_posts, posts
    ) -> None:
        run = _run(repo, status=RunStatus.COMPLETED)
        break_the_posts(sender, repo)
        retry = mocker.patch.object(tasks.publish_visual_review_commit_status, "delay")

        with django_capture_on_commit_callbacks(using=WRITER_DB, execute=True):
            commit_status.publish(repo, run.commit_sha, run.run_type)

        retry.assert_called_once_with(repo.team_id, str(repo.id), run.commit_sha, run.run_type)
        assert sender.call_count == posts

        sender.reset_mock(return_value=True, side_effect=True)
        sender.return_value = ci_status.StatusPost.POSTED
        tasks.publish_visual_review_commit_status.apply(args=retry.call_args.args)

        assert sender.call_count == 1
        newest = Run.objects.filter(commit_sha="c1").order_by("-created_at")[0]
        assert str(newest.id) in sender.call_args.kwargs["target_url"]

    @pytest.mark.parametrize(
        ("act", "expected"),
        [
            pytest.param(
                _approve_button,
                ("failure", "1 approved change(s) not finalized. Finalize the run to pass this check"),
                id="approve",
            ),
            pytest.param(_tolerate_button, ("success", "No visual changes"), id="tolerate"),
            pytest.param(
                _quarantine_button, ("success", "No gating changes; 1 quarantined snapshot differs"), id="quarantine"
            ),
        ],
    )
    def test_a_review_action_publishes_in_ledger_mode(
        self, repo, sender, user, django_capture_on_commit_callbacks, act, expected
    ) -> None:
        run = _run(repo, status=RunStatus.COMPLETED, changed_count=1)
        snapshot = _snapshot(run, "Button", SnapshotResult.CHANGED)
        finalized = _run(repo, commit_sha="c2", branch="other", status=RunStatus.COMPLETED, approved=True)
        _snapshot(finalized, "Button", SnapshotResult.CHANGED, review_state=ReviewState.APPROVED)
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="Button-new", storage_path="p/new")

        with django_capture_on_commit_callbacks(using=WRITER_DB, execute=True):
            act(run, snapshot, user.id)

        assert _posted(sender)[-1] == (self.GATING, *expected)
        assert all(str(finalized.id) not in call.kwargs["target_url"] for call in sender.call_args_list)

    @pytest.mark.parametrize(
        ("mode", "gate", "after", "expected", "stale_count"),
        [
            pytest.param(BaselineMode.LEDGER, RunGate.COMMIT_STATUS, _no_push, STALE_ONE, 1, id="stale_approval"),
            pytest.param(BaselineMode.LEDGER, RunGate.CI_JOB, _no_push, STALE_ONE, 1, id="run_made_in_shadow_mode"),
            pytest.param(
                BaselineMode.SHADOW,
                RunGate.CI_JOB,
                _no_push,
                _verdict("success", "Visual changes approved"),
                0,
                id="shadow_mode",
            ),
            pytest.param(
                BaselineMode.LEDGER, RunGate.COMMIT_STATUS, _push_again, STALE_ONE, 0, id="superseded_by_a_newer_push"
            ),
        ],
    )
    def test_a_finalized_run_on_a_moved_baseline(self, repo, sender, mode, gate, after, expected, stale_count) -> None:
        run = _finalized_run_on_a_moved_baseline(repo, gate)
        set_baseline_mode(repo, mode, status_gate=True)
        after(repo, run)

        commit_status.publish(repo, run.commit_sha, run.run_type)

        assert _posted(sender) == [(self.GATING, expected.state, expected.description)]
        assert api.get_run(run.id).stale_approval_count == stale_count

    def test_with_the_status_gate_off_no_approval_counts_as_stale(self, repo) -> None:
        run = _finalized_run_on_a_moved_baseline(repo, RunGate.COMMIT_STATUS)
        set_baseline_mode(repo, BaselineMode.SHADOW, status_gate=False)

        assert api.get_run(run.id).stale_approval_count == 0

    @pytest.mark.parametrize(
        ("mode", "status_gate", "runs_before", "report_run_type", "expected", "posted"),
        [
            (BaselineMode.LEDGER, True, 0, "storybook", NoRunNeededOutcome.POSTED, [NO_RUN_NEEDED]),
            (BaselineMode.LEDGER, True, 1, "storybook", NoRunNeededOutcome.RUN_EXISTS, []),
            (BaselineMode.LEDGER, True, 1, "Storybook", NoRunNeededOutcome.RUN_EXISTS, []),
            (BaselineMode.YAML, False, 0, "storybook", NoRunNeededOutcome.STATUS_GATE_OFF, []),
            (BaselineMode.SHADOW, False, 0, "storybook", NoRunNeededOutcome.STATUS_GATE_OFF, []),
            (BaselineMode.SHADOW, True, 0, "storybook", NoRunNeededOutcome.POSTED, [NO_RUN_NEEDED]),
        ],
    )
    def test_the_no_run_needed_report(
        self, repo, sender, mode, status_gate, runs_before, report_run_type, expected, posted
    ) -> None:
        set_baseline_mode(repo, mode, status_gate=status_gate)
        for _ in range(runs_before):
            _run(repo)
        report = NoRunNeededInput(repo_id=repo.id, run_type=report_run_type, commit_sha="c1", branch="feat")

        assert commit_status.report_no_run_needed(repo, report) == expected

        assert _posted(sender) == posted
        assert Run.objects.filter(repo=repo).count() == runs_before

    def test_a_no_run_needed_report_github_refuses_fails_the_job(self, repo, sender) -> None:
        sender.return_value = ci_status.StatusPost.REFUSED
        report = NoRunNeededInput(repo_id=repo.id, run_type=RunType.STORYBOOK, commit_sha="c1", branch="feat")

        with pytest.raises(errors.CommitStatusNotPostedError):
            commit_status.report_no_run_needed(repo, report)

        assert _posted(sender) == [self.NO_RUN_NEEDED]

    def test_a_run_created_while_the_report_posts_owns_the_status(self, repo, sender) -> None:
        def a_run_arrives_while_posting(*args, **kwargs):
            if sender.call_count == 1:
                _run(repo)
            return ci_status.StatusPost.POSTED

        sender.side_effect = a_run_arrives_while_posting

        commit_status.report_no_run_needed(
            repo, NoRunNeededInput(repo_id=repo.id, run_type=RunType.STORYBOOK, commit_sha="c1", branch="feat")
        )

        assert _posted(sender)[-1] == (self.GATING, "pending", "Visual review in progress")
