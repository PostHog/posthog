"""Unit tests for logic/ci_status.py — Commit statuses and CI job reruns."""

import pytest

from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import RunType
from products.visual_review.backend.logic import approvals, artifact_store, ci_status, repos, runs
from products.visual_review.backend.models import Repo, Run
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


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
        assert f"/visual_review/runs/{run.id}" in check["target_url"]

    def test_complete_run_posts_success_when_no_changes(self, github_repo, mock_github_api, mocker):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=github_repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                pr_number=1,
                snapshots=[SnapshotManifestItem(identifier="snap", content_hash="same")],
                baseline_hashes={"snap": "same"},
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
        assert statuses[-1]["description"] == "No visual changes"
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
        assert f"/visual_review/runs/{run.id}" in comment
        # Verify comment ID stored for future updates
        run.refresh_from_db()
        assert run.metadata["github_comment_id"] is not None

    def test_subsequent_run_updates_existing_comment(self, github_repo, mock_github_api):
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

        created = [c for c in mock_github_api.issue_comments if c["action"] == "created"]
        updated = [c for c in mock_github_api.issue_comments if c["action"] == "updated"]
        assert len(created) == 1
        assert len(updated) == 1
        assert f"/visual_review/runs/{run2.id}" in updated[0]["body"]

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
