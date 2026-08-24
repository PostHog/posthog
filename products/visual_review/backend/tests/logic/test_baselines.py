"""Unit tests for logic/baselines.py — Baseline resolution, merge-base healing, and hash verification."""

from datetime import timedelta

import pytest

from django.utils import timezone

from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import ReviewState, RunStatus, RunType, SnapshotResult
from products.visual_review.backend.logic import artifact_store, baselines, errors, repos, runs
from products.visual_review.backend.models import Repo, Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRunIsOnDefaultBranch:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=1234, repo_full_name="org/test-repo")

    def _mock_github(self, mocker, default_branch="master"):
        mock_github = mocker.MagicMock()
        mock_github.access_token_expired.return_value = False
        mocker.patch(
            "products.visual_review.backend.logic.github_api.get_github_integration_for_repo", return_value=mock_github
        )
        mocker.patch("products.visual_review.backend.logic.github_api._get_default_branch", return_value=default_branch)

    def test_true_when_branch_matches_default(self, repo, mocker):
        self._mock_github(mocker, default_branch="main")
        assert baselines._run_is_on_default_branch(repo, "main") is True

    def test_false_when_branch_differs(self, repo, mocker):
        self._mock_github(mocker, default_branch="main")
        assert baselines._run_is_on_default_branch(repo, "feature-x") is False

    def test_false_when_no_github_integration(self, repo, mocker):
        mocker.patch(
            "products.visual_review.backend.logic.github_api.get_github_integration_for_repo",
            side_effect=errors.GitHubIntegrationNotFoundError("none"),
        )
        assert baselines._run_is_on_default_branch(repo, "master") is False


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestMergeBaseBaselineHealing:
    """Tests for _resolve_baselines_with_merge_base healing rebase-corrupted baselines."""

    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test-repo")

    def _mock_github(
        self,
        mocker,
        branch_baseline,
        merge_base_baseline=None,
        merge_base_sha="abc123",
        default_branch="master",
        commit_sha_baselines=None,
        pr_head_sha=None,
        pr_head_is_ancestor=True,
    ):
        mock_github = mocker.MagicMock()
        mock_github.integration.sensitive_config = {"access_token": "fake"}
        mock_github.access_token_expired.return_value = False
        mocker.patch(
            "products.visual_review.backend.logic.github_api.get_github_integration_for_repo", return_value=mock_github
        )

        _commit_sha_baselines = commit_sha_baselines or {}

        def fake_fetch(github, repo_full_name, file_path, ref):
            if ref in _commit_sha_baselines:
                return {k: {"hash": v} for k, v in _commit_sha_baselines[ref].items()}, f"sha-{ref}"
            if ref in ("my-branch", default_branch):
                return {k: {"hash": v} for k, v in branch_baseline.items()}, "sha1"
            if ref == merge_base_sha:
                baselines = merge_base_baseline if merge_base_baseline is not None else branch_baseline
                return {k: {"hash": v} for k, v in baselines.items()}, "sha2"
            return {}, None

        pr_response = mocker.MagicMock()
        if pr_head_sha is None:
            pr_response.status_code = 404
            pr_response.json.return_value = {"message": "Not Found"}
        else:
            pr_response.status_code = 200
            pr_response.json.return_value = {"head": {"sha": pr_head_sha}}
        mock_github.api_request.return_value = pr_response

        def fake_merge_base(github, repo_full_name, base, head):
            if pr_head_sha is not None and base == pr_head_sha:
                return pr_head_sha if pr_head_is_ancestor else "unrelated-sha"
            return merge_base_sha

        mocker.patch("products.visual_review.backend.logic.github_api._fetch_baseline_file", side_effect=fake_fetch)
        mocker.patch("products.visual_review.backend.logic.github_api._get_merge_base_sha", side_effect=fake_merge_base)
        mocker.patch("products.visual_review.backend.logic.github_api._get_default_branch", return_value=default_branch)
        mocker.patch(
            "products.visual_review.backend.logic.baselines._verify_baseline_hashes",
            side_effect=lambda repo, hashes: hashes,
        )
        return mock_github

    def test_no_healing_when_baselines_match(self, repo, mocker):
        baseline = {"A": "h1", "B": "h2"}
        self._mock_github(mocker, branch_baseline=baseline, merge_base_baseline=baseline)

        merged, healed = baselines._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert merged == baseline
        assert healed == 0

    def test_heals_entries_missing_from_branch(self, repo, mocker):
        branch_baseline = {"A": "h1"}
        merge_base_baseline = {"A": "h1", "B": "h2", "C": "h3"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        merged, healed = baselines._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert merged == {"A": "h1", "B": "h2", "C": "h3"}
        assert healed == 2

    def test_branch_wins_on_conflict(self, repo, mocker):
        branch_baseline = {"A": "branch_hash"}
        merge_base_baseline = {"A": "master_hash", "B": "h2"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        merged, healed = baselines._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert merged["A"] == "branch_hash"
        assert merged["B"] == "h2"
        assert healed == 1

    def test_branch_approvals_preserved(self, repo, mocker):
        branch_baseline = {"A": "h1", "NewStory": "new_hash"}
        merge_base_baseline = {"A": "h1"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        merged, healed = baselines._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert "NewStory" in merged
        assert merged["NewStory"] == "new_hash"
        assert healed == 0

    def test_skips_merge_base_for_default_branch(self, repo, mocker):
        baseline = {"A": "h1"}
        self._mock_github(mocker, branch_baseline=baseline, default_branch="master")

        merged, healed = baselines._resolve_baselines_with_merge_base(repo, "storybook", "master")

        assert merged == baseline
        assert healed == 0

    @pytest.mark.parametrize(
        "commit_sha, expected_baseline",
        [
            ("deadbeef", {"A": "h1"}),  # pinned to commit SHA
            (None, {"A": "h1", "B": "h2"}),  # falls back to branch tip
        ],
    )
    def test_default_branch_baseline_ref(self, repo, mocker, commit_sha, expected_baseline):
        """Baseline is pinned to commit SHA when provided, otherwise falls back to branch tip."""
        branch_tip_baseline = {"A": "h1", "B": "h2"}
        commit_baseline = {"A": "h1"}
        self._mock_github(
            mocker,
            branch_baseline=branch_tip_baseline,
            default_branch="master",
            commit_sha_baselines={"deadbeef": commit_baseline},
        )

        merged, healed = baselines._resolve_baselines_with_merge_base(
            repo, "storybook", "master", commit_sha=commit_sha
        )

        assert merged == expected_baseline
        assert healed == 0

    def test_non_default_branch_ignores_commit_sha(self, repo, mocker):
        """On non-default branches, commit_sha is ignored — branch name is used."""
        branch_baseline = {"A": "h1"}
        merge_base_baseline = {"A": "h1", "C": "h3"}
        commit_baseline = {"X": "hx"}  # Should NOT be used
        self._mock_github(
            mocker,
            branch_baseline=branch_baseline,
            merge_base_baseline=merge_base_baseline,
            commit_sha_baselines={"deadbeef": commit_baseline},
        )

        merged, healed = baselines._resolve_baselines_with_merge_base(
            repo, "storybook", "my-branch", commit_sha="deadbeef"
        )

        # Should use branch baseline + merge-base healing, NOT the commit baseline
        assert merged == {"A": "h1", "C": "h3"}
        assert healed == 1

    def test_falls_back_on_merge_base_failure(self, repo, mocker):
        branch_baseline = {"A": "h1"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_sha=None)

        merged, healed = baselines._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert merged == branch_baseline
        assert healed == 0

    def test_falls_back_when_merge_base_file_fetch_raises(self, repo, mocker):
        branch_baseline = {"A": "h1"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline={"A": "h1", "B": "h2"})
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_at_ref",
            side_effect=[branch_baseline, Exception("GitHub 500")],
        )

        merged, healed = baselines._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert merged == branch_baseline
        assert healed == 0

    def test_first_run_both_baselines_empty(self, repo, mocker):
        self._mock_github(mocker, branch_baseline={}, merge_base_baseline={})

        merged, healed = baselines._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert merged == {}
        assert healed == 0

    def test_heals_rebase_scenario_end_to_end(self, repo, mocker):
        """Simulates Paul's bug: rebase replayed bot commit, dropping 8 entries."""
        branch_baseline = {"story1": "h1", "story2": "h2"}
        merge_base_baseline = {
            "story1": "h1",
            "story2": "h2",
            "lost1": "h3",
            "lost2": "h4",
            "lost3": "h5",
            "lost4": "h6",
            "lost5": "h7",
            "lost6": "h8",
            "lost7": "h9",
            "lost8": "h10",
        }
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        merged, healed = baselines._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert len(merged) == 10
        assert healed == 8
        assert all(f"lost{i}" in merged for i in range(1, 9))

    def test_healing_integrates_with_complete_run(self, repo, mocker):
        """Healed entries classify as unchanged when hashes match."""
        branch_baseline = {"existing": "h1"}
        merge_base_baseline = {"existing": "h1", "healed": "h2"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="h1", storage_path="p/h1")
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="h2", storage_path="p/h2")
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="my-branch",
                pr_number=1,
                snapshots=[
                    SnapshotManifestItem(identifier="existing", content_hash="h1"),
                    SnapshotManifestItem(identifier="healed", content_hash="h2"),
                ],
            ),
            team_id=repo.team_id,
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)

        snapshots = {s.identifier: s for s in run.snapshots.all()}
        assert snapshots["existing"].result == SnapshotResult.UNCHANGED
        assert snapshots["healed"].result == SnapshotResult.UNCHANGED

        run.refresh_from_db()
        assert run.metadata.get("baseline_healed_from_merge_base") == 1

    def test_default_branch_race_condition_no_false_removals(self, repo, mocker):
        """Reproduces the race where a newer commit advances the baseline on master.

        Scenario: commit A (posthog-js upgrade) lands on master, then commit B
        (trendlines, adding 6 stories) lands right after.  By the time commit A's
        VR run calls complete_run, the branch tip already points at commit B's
        baseline (with 6 extra entries).  Without pinning, VR would report 6
        false "removed" snapshots.  With pinning, it fetches the baseline at
        commit A's SHA and sees 0 removals.
        """
        # Commit A's baseline: 3 stories
        commit_a_baseline = {"story1": "h1", "story2": "h2", "story3": "h3"}
        # Branch tip (after commit B landed): 3 + 6 = 9 stories
        branch_tip_baseline = {
            **commit_a_baseline,
            "new1": "n1",
            "new2": "n2",
            "new3": "n3",
            "new4": "n4",
            "new5": "n5",
            "new6": "n6",
        }
        self._mock_github(
            mocker,
            branch_baseline=branch_tip_baseline,
            default_branch="master",
            commit_sha_baselines={"commit_a_sha": commit_a_baseline},
        )

        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="h1", storage_path="p/h1")
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="h2", storage_path="p/h2")
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="h3", storage_path="p/h3")

        # Commit A's run only has the 3 original stories
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="commit_a_sha",
                branch="master",
                pr_number=None,
                snapshots=[
                    SnapshotManifestItem(identifier="story1", content_hash="h1"),
                    SnapshotManifestItem(identifier="story2", content_hash="h2"),
                    SnapshotManifestItem(identifier="story3", content_hash="h3"),
                ],
            ),
            team_id=repo.team_id,
        )

        runs.complete_run(run.id)

        run.refresh_from_db()
        assert run.removed_count == 0
        assert run.new_count == 0
        assert run.changed_count == 0

    def test_healing_detects_changed_when_hash_differs(self, repo, mocker):
        """Healed entry with different hash shows as changed, not new."""
        branch_baseline: dict[str, str] = {}
        merge_base_baseline = {"flaky": "master_hash"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="master_hash", storage_path="p/master")
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="branch_hash", storage_path="p/branch")
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="my-branch",
                pr_number=1,
                snapshots=[SnapshotManifestItem(identifier="flaky", content_hash="branch_hash")],
            ),
            team_id=repo.team_id,
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)

        snapshot = run.snapshots.get(identifier="flaky")
        assert snapshot.result == SnapshotResult.CHANGED
        assert snapshot.baseline_hash == "master_hash"

    @pytest.mark.parametrize(
        "run_branch, prior_branch, prior_pr_number, prior_run_type, prior_approved, prior_review_state, pr_head_sha, pr_head_is_ancestor, expect_tombstoned",
        [
            ("my-branch", "my-branch", None, RunType.STORYBOOK, True, ReviewState.APPROVED, None, True, True),
            ("my-branch", "someone-else", None, RunType.STORYBOOK, True, ReviewState.APPROVED, None, True, False),
            ("my-branch", "my-branch", None, "playwright", True, ReviewState.APPROVED, None, True, False),
            ("my-branch", "my-branch", None, RunType.STORYBOOK, False, ReviewState.PENDING, None, True, False),
            (
                "trunk-merge/pr-42/0c0ffee",
                "source-pr-branch",
                42,
                RunType.STORYBOOK,
                True,
                ReviewState.APPROVED,
                "pr42-head",
                True,
                True,
            ),
            (
                "trunk-merge/pr-42/0c0ffee",
                "source-pr-branch",
                43,
                RunType.STORYBOOK,
                True,
                ReviewState.APPROVED,
                "pr42-head",
                True,
                False,
            ),
            (
                "trunk-merge/pr-42/0c0ffee",
                "source-pr-branch",
                42,
                RunType.STORYBOOK,
                True,
                ReviewState.APPROVED,
                "pr42-head",
                False,
                False,
            ),
            (
                "trunk-merge/pr-42/0c0ffee",
                "source-pr-branch",
                42,
                RunType.STORYBOOK,
                True,
                ReviewState.APPROVED,
                None,
                True,
                False,
            ),
            ("my-branch", "someone-else", 42, RunType.STORYBOOK, True, ReviewState.APPROVED, None, True, False),
        ],
        ids=[
            "approved_on_branch",
            "wrong_branch",
            "wrong_run_type",
            "not_approved",
            "merge_queue_source_pr",
            "merge_queue_other_pr",
            "merge_queue_spoofed_branch_not_ancestor",
            "merge_queue_source_pr_not_found",
            "pr_number_ignored_off_queue",
        ],
    )
    def test_tombstone_excludes_only_approved_removals_on_branch(
        self,
        repo,
        team,
        mocker,
        run_branch,
        prior_branch,
        prior_pr_number,
        prior_run_type,
        prior_approved,
        prior_review_state,
        pr_head_sha,
        pr_head_is_ancestor,
        expect_tombstoned,
    ):
        branch_baseline: dict[str, str] = {}
        merge_base_baseline = {"candidate": "h1"}
        self._mock_github(
            mocker,
            branch_baseline=branch_baseline,
            merge_base_baseline=merge_base_baseline,
            pr_head_sha=pr_head_sha,
            pr_head_is_ancestor=pr_head_is_ancestor,
        )

        prior_run = Run.objects.create(
            team_id=team.id,
            repo=repo,
            run_type=prior_run_type,
            branch=prior_branch,
            pr_number=prior_pr_number,
            commit_sha="prior-sha",
            status=RunStatus.COMPLETED,
            approved=prior_approved,
        )
        RunSnapshot.objects.create(
            run=prior_run,
            team_id=team.id,
            identifier="candidate",
            baseline_hash="h1",
            current_hash="",
            result=SnapshotResult.REMOVED,
            review_state=prior_review_state,
        )

        merged, healed = baselines._resolve_baselines_with_merge_base(repo, RunType.STORYBOOK, run_branch)

        if expect_tombstoned:
            assert merged == {}
            assert healed == 0
        else:
            assert merged == merge_base_baseline
            assert healed == 1

    def test_tombstone_cleared_by_later_re_addition(self, repo, team, mocker):
        """Remove→approve→restore→approve: the re-addition clears the tombstone."""
        branch_baseline: dict[str, str] = {}
        merge_base_baseline = {"story-x": "h1"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        # Run 1: story-x removed and approved
        run1 = Run.objects.create(
            team_id=team.id,
            repo=repo,
            run_type=RunType.STORYBOOK,
            branch="my-branch",
            commit_sha="sha1",
            status=RunStatus.COMPLETED,
            approved=True,
            created_at=timezone.now() - timedelta(hours=2),
        )
        RunSnapshot.objects.create(
            run=run1,
            team_id=team.id,
            identifier="story-x",
            baseline_hash="h1",
            current_hash="",
            result=SnapshotResult.REMOVED,
            review_state=ReviewState.APPROVED,
        )

        # Supersede run1 (as create_run would)
        run1.superseded_by = run1
        run1.save(update_fields=["superseded_by"])

        # Run 2: story-x re-added and approved as NEW
        run2 = Run.objects.create(
            team_id=team.id,
            repo=repo,
            run_type=RunType.STORYBOOK,
            branch="my-branch",
            commit_sha="sha2",
            status=RunStatus.COMPLETED,
            approved=True,
            created_at=timezone.now() - timedelta(hours=1),
        )
        RunSnapshot.objects.create(
            run=run2,
            team_id=team.id,
            identifier="story-x",
            baseline_hash="",
            current_hash="h1",
            result=SnapshotResult.NEW,
            review_state=ReviewState.APPROVED,
        )

        merged, healed = baselines._resolve_baselines_with_merge_base(repo, RunType.STORYBOOK, "my-branch")

        # Latest approved outcome is NEW, not REMOVED — tombstone cleared, healing works
        assert "story-x" in merged
        assert healed == 1

    def test_tombstone_persists_without_later_approval(self, repo, team, mocker):
        """Remove→approve: tombstone stays until a later approval overrides it."""
        branch_baseline: dict[str, str] = {}
        merge_base_baseline = {"story-x": "h1"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        run1 = Run.objects.create(
            team_id=team.id,
            repo=repo,
            run_type=RunType.STORYBOOK,
            branch="my-branch",
            commit_sha="sha1",
            status=RunStatus.COMPLETED,
            approved=True,
        )
        RunSnapshot.objects.create(
            run=run1,
            team_id=team.id,
            identifier="story-x",
            baseline_hash="h1",
            current_hash="",
            result=SnapshotResult.REMOVED,
            review_state=ReviewState.APPROVED,
        )

        merged, healed = baselines._resolve_baselines_with_merge_base(repo, RunType.STORYBOOK, "my-branch")

        assert "story-x" not in merged
        assert healed == 0


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestVerifyBaselineHashes:
    """Bootstrap-window guard: unsigned baselines must not be honored."""

    def test_drops_all_entries_when_no_signing_keys(self, team):
        repo = Repo.objects.create(
            team_id=team.id,
            repo_external_id=77777,
            repo_full_name="org/no-keys",
            signing_keys={},
        )

        result = baselines._verify_baseline_hashes(repo, {"snap-a": "v1.k1.deadbeef.fake"})

        assert result == {}
