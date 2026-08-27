"""Unit tests for logic/runs.py — Run creation, ingestion, completion, supersession, and recompute."""

import pytest

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import RunStatus, RunType, SnapshotResult
from products.visual_review.backend.logic import approvals, artifact_store, errors, repos, run_queries, runs
from products.visual_review.backend.models import Repo, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRunOperations:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test")

    def test_create_run_basic(self, repo):
        run, uploads = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123def456",
                branch="main",
                pr_number=42,
                snapshots=[
                    SnapshotManifestItem(identifier="Button-primary", content_hash="hash1"),
                    SnapshotManifestItem(identifier="Button-secondary", content_hash="hash2"),
                ],
                baseline_hashes={},
            ),
            team_id=repo.team_id,
        )

        assert run.repo_id == repo.id
        assert run.run_type == RunType.STORYBOOK
        assert run.commit_sha == "abc123def456"
        assert run.branch == "main"
        assert run.pr_number == 42
        assert run.status == RunStatus.PENDING
        assert run.total_snapshots == 2
        # uploads is a list of dicts with content_hash, url, fields
        upload_hashes = {u["content_hash"] for u in uploads}
        assert upload_hashes == {"hash1", "hash2"}

    def test_create_run_with_existing_artifacts(self, repo):
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="existing", storage_path="p/existing")

        run, uploads = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.PLAYWRIGHT,
                commit_sha="abc",
                branch="feat",
                pr_number=None,
                snapshots=[
                    SnapshotManifestItem(identifier="snap1", content_hash="existing"),
                    SnapshotManifestItem(identifier="snap2", content_hash="new"),
                ],
                baseline_hashes={},
            ),
            team_id=repo.team_id,
        )

        # Only "new" needs upload, "existing" already has artifact
        assert len(uploads) == 1
        assert uploads[0]["content_hash"] == "new"

    def test_create_run_with_baselines(self, repo, mocker):
        baseline_artifact, _ = artifact_store.get_or_create_artifact(
            repo_id=repo.id, content_hash="baseline_hash", storage_path="p/baseline"
        )

        run, _uploads = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="new_hash")],
                baseline_hashes={"Button": "baseline_hash"},
            ),
            team_id=repo.team_id,
        )

        # Classification happens at complete_run time, not create_run time
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"Button": "baseline_hash"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)

        snapshot = run.snapshots.first()
        assert snapshot is not None
        assert snapshot.baseline_artifact_id == baseline_artifact.id
        assert snapshot.result == SnapshotResult.CHANGED

    def test_create_run_snapshot_results(self, repo, mocker):
        baseline_artifact, _ = artifact_store.get_or_create_artifact(
            repo_id=repo.id, content_hash="same_hash", storage_path="p/same"
        )

        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[
                    SnapshotManifestItem(identifier="unchanged", content_hash="same_hash"),
                    SnapshotManifestItem(identifier="new", content_hash="brand_new"),
                    SnapshotManifestItem(identifier="changed", content_hash="different"),
                ],
                baseline_hashes={
                    "unchanged": "same_hash",
                    "changed": "old_hash",
                },
            ),
            team_id=repo.team_id,
        )

        # Classification happens at complete_run time
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"unchanged": "same_hash", "changed": "old_hash"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)

        snapshots = {s.identifier: s for s in run.snapshots.all()}
        assert snapshots["unchanged"].result == SnapshotResult.UNCHANGED
        assert snapshots["new"].result == SnapshotResult.NEW
        assert snapshots["changed"].result == SnapshotResult.CHANGED

    def test_create_run_empty(self, repo):
        run, uploads = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[],
            ),
            team_id=repo.team_id,
        )

        assert run.total_snapshots == 0
        assert run.changed_count == 0
        assert run.new_count == 0
        assert run.removed_count == 0
        assert run.snapshots.count() == 0
        assert len(uploads) == 0

    def test_add_snapshots_to_run(self, repo):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[],
            ),
            team_id=repo.team_id,
        )
        assert run.total_snapshots == 0

        # Shard 1
        added, _uploads = runs.add_snapshots_to_run(
            run_id=run.id,
            team_id=repo.team_id,
            snapshots=[{"identifier": "btn", "content_hash": "h1"}],
        )
        assert added == 1
        run.refresh_from_db()
        assert run.total_snapshots == 1
        assert run.new_count == 1

        # Shard 2
        added, _uploads = runs.add_snapshots_to_run(
            run_id=run.id,
            team_id=repo.team_id,
            snapshots=[{"identifier": "card", "content_hash": "h2"}],
        )
        assert added == 1
        run.refresh_from_db()
        assert run.total_snapshots == 2
        assert run.new_count == 2
        assert run.snapshots.count() == 2

    def test_add_snapshots_idempotent(self, repo):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[],
            ),
            team_id=repo.team_id,
        )

        for _ in range(2):
            runs.add_snapshots_to_run(
                run_id=run.id,
                team_id=repo.team_id,
                snapshots=[{"identifier": "btn", "content_hash": "h1"}],
            )

        assert run.snapshots.count() == 1

    def test_add_snapshots_rejects_non_pending(self, repo):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[],
            ),
            team_id=repo.team_id,
        )
        runs.finish_processing(run.id)

        with pytest.raises(ValueError, match="pending"):
            runs.add_snapshots_to_run(
                run_id=run.id,
                team_id=repo.team_id,
                snapshots=[{"identifier": "btn", "content_hash": "h1"}],
            )

    def test_complete_run_detects_removals(self, repo, mocker):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="kept", content_hash="h1")],
            ),
            team_id=repo.team_id,
        )

        # Mock baseline to include an identifier not in the run
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"kept": "h1", "deleted": "h2"}, 0),
        )

        completed = runs.complete_run(run.id)

        assert completed.removed_count == 1
        removed = run.snapshots.get(identifier="deleted")
        assert removed.result == SnapshotResult.REMOVED

    def test_complete_run_partial_skips_removals_off_default_branch(self, repo, mocker):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="feature-x",
                pr_number=7,
                snapshots=[SnapshotManifestItem(identifier="kept", content_hash="h1")],
                is_partial=True,
            ),
            team_id=repo.team_id,
        )

        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"kept": "h1", "deleted": "h2"}, 0),
        )
        mocker.patch("products.visual_review.backend.logic.baselines._run_is_on_default_branch", return_value=False)

        completed = runs.complete_run(run.id)

        assert completed.removed_count == 0
        assert not run.snapshots.filter(identifier="deleted").exists()

    def test_complete_run_partial_ignored_on_default_branch(self, repo, mocker):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="master",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="kept", content_hash="h1")],
                is_partial=True,
            ),
            team_id=repo.team_id,
        )

        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"kept": "h1", "deleted": "h2"}, 0),
        )
        mocker.patch("products.visual_review.backend.logic.baselines._run_is_on_default_branch", return_value=True)

        completed = runs.complete_run(run.id)

        # is_partial must not suppress removal detection on the default branch.
        assert completed.removed_count == 1
        removed = run.snapshots.get(identifier="deleted")
        assert removed.result == SnapshotResult.REMOVED
        # The default-branch correction is persisted, so the run is no longer
        # treated as partial anywhere downstream (status context, UI).
        assert completed.is_partial is False

    def test_complete_run_passes_commit_sha_to_baseline_resolution(self, repo, mocker):
        # Pins the baseline to the commit, and limits healing to what rendered.
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="deadbeef123",
                branch="master",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="A", content_hash="h1")],
            ),
            team_id=repo.team_id,
        )

        mock_resolve = mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"A": "h1"}, 0),
        )

        runs.complete_run(run.id)

        mock_resolve.assert_called_once_with(
            repo,
            RunType.STORYBOOK,
            "master",
            rendered_identifiers={"A"},
            commit_sha="deadbeef123",
        )

    def test_create_run_with_purpose(self, repo):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[],
                purpose="observe",
            ),
            team_id=repo.team_id,
        )
        assert run.purpose == "observe"

    def test_approve_rejects_observe_runs(self, repo):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="btn", content_hash="h1")],
                purpose="observe",
            ),
            team_id=repo.team_id,
        )
        runs.finish_processing(run.id)

        with pytest.raises(ValueError, match="Observational"):
            approvals.finalize_run(run_id=run.id, user_id=1, approve_all=True)

    def test_get_run(self, repo):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[],
                baseline_hashes={},
            ),
            team_id=repo.team_id,
        )

        retrieved = run_queries.get_run(run.id)

        assert retrieved.id == run.id

    def test_get_run_not_found(self):
        import uuid

        with pytest.raises(errors.RunNotFoundError):
            run_queries.get_run(uuid.uuid4())

    def test_mark_run_processing(self, repo):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[],
                baseline_hashes={},
            ),
            team_id=repo.team_id,
        )

        updated = runs.mark_run_processing(run.id)

        assert updated.status == RunStatus.PROCESSING

    def test_finish_processing_success(self, repo, mocker):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[
                    SnapshotManifestItem(identifier="changed1", content_hash="h1"),
                    SnapshotManifestItem(identifier="new1", content_hash="h2"),
                ],
                baseline_hashes={"changed1": "old"},
            ),
            team_id=repo.team_id,
        )

        # Classification happens at complete_run time
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"changed1": "old"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)

        # complete_run leaves the run in PROCESSING when there are changes;
        # finish_processing completes it
        updated = runs.finish_processing(run.id)

        assert updated.status == RunStatus.COMPLETED
        assert updated.completed_at is not None
        assert updated.changed_count == 1
        assert updated.new_count == 1
        assert updated.error_message == ""

    def test_finish_processing_with_error(self, repo):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[],
                baseline_hashes={},
            ),
            team_id=repo.team_id,
        )

        updated = runs.finish_processing(run.id, error_message="Something failed")

        assert updated.status == RunStatus.FAILED
        assert updated.error_message == "Something failed"

    def test_update_run_counts_reads_and_writes_through_requested_db(self, repo, mocker):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[],
                baseline_hashes={},
            ),
            team_id=repo.team_id,
        )

        snapshot_queryset = mocker.Mock()
        snapshot_queryset.values.return_value.annotate.return_value = [
            {"result": SnapshotResult.CHANGED, "n": 2},
            {"result": SnapshotResult.NEW, "n": 1},
        ]
        snapshot_manager = mocker.Mock()
        snapshot_manager.filter.return_value = snapshot_queryset

        run_snapshot_using = mocker.patch.object(RunSnapshot.objects, "using", return_value=snapshot_manager)
        run_save = mocker.patch.object(run, "save")

        runs._update_run_counts(run, using=WRITER_DB)

        run_snapshot_using.assert_called_once_with(WRITER_DB)
        snapshot_manager.filter.assert_called_once_with(run_id=run.id)
        run_save.assert_called_once_with(using=WRITER_DB, update_fields=["changed_count", "new_count", "removed_count"])
        assert run.changed_count == 2
        assert run.new_count == 1
        assert run.removed_count == 0


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRunSupersession:
    """When a new run is created for the same (repo, branch, run_type), older runs get superseded."""

    @pytest.fixture
    def repo(self, team):
        return Repo.objects.create(team_id=team.id, repo_external_id=66666, repo_full_name="org/test-repo")

    def _create_run(self, repo, *, branch="feat/x", run_type=RunType.STORYBOOK, commit_sha="abc"):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=run_type,
                commit_sha=commit_sha,
                branch=branch,
                pr_number=1,
                snapshots=[SnapshotManifestItem(identifier="snap", content_hash=commit_sha)],
                baseline_hashes={},
            ),
            team_id=repo.team_id,
        )
        runs.finish_processing(run.id)
        run.refresh_from_db()
        return run

    def test_single_run_not_superseded(self, repo):
        run = self._create_run(repo)

        assert run.superseded_by is None
        assert run_queries.is_run_stale(run) is False

    def test_newer_run_supersedes_older(self, repo):
        old = self._create_run(repo, commit_sha="old")
        new = self._create_run(repo, commit_sha="new")

        old.refresh_from_db()
        assert old.superseded_by_id == new.id
        assert new.superseded_by is None

    def test_supersession_chains(self, repo):
        first = self._create_run(repo, commit_sha="1st")
        second = self._create_run(repo, commit_sha="2nd")
        third = self._create_run(repo, commit_sha="3rd")

        first.refresh_from_db()
        second.refresh_from_db()
        # first was superseded by second, then second by third
        # first still points to second (not updated again)
        assert first.superseded_by_id == second.id
        assert second.superseded_by_id == third.id
        assert third.superseded_by is None

    def test_different_branches_are_independent(self, repo):
        run_a = self._create_run(repo, branch="feat/a", commit_sha="a")
        self._create_run(repo, branch="feat/b", commit_sha="b")

        run_a.refresh_from_db()
        assert run_a.superseded_by is None

    def test_different_run_types_are_independent(self, repo):
        run_sb = self._create_run(repo, run_type=RunType.STORYBOOK, commit_sha="a")
        self._create_run(repo, run_type=RunType.PLAYWRIGHT, commit_sha="b")

        run_sb.refresh_from_db()
        assert run_sb.superseded_by is None

    def test_review_state_filter_excludes_superseded(self, repo, team):
        self._create_run(repo, commit_sha="old")
        self._create_run(repo, commit_sha="new")

        current_runs = list(run_queries.list_runs_for_team(team.id, review_state="needs_review"))
        stale_runs = list(run_queries.list_runs_for_team(team.id, review_state="stale"))

        assert len(current_runs) == 1
        assert current_runs[0].commit_sha == "new"
        assert len(stale_runs) == 1
        assert stale_runs[0].commit_sha == "old"

    def test_review_state_counts(self, repo, team):
        self._create_run(repo, commit_sha="old")
        self._create_run(repo, commit_sha="new")

        counts = run_queries.get_review_state_counts(team.id)

        assert counts["stale"] == 1
        assert counts["needs_review"] == 1

    def test_approve_superseded_run_raises(self, repo, user):
        old = self._create_run(repo, commit_sha="old")
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="old", storage_path="p/old")
        self._create_run(repo, commit_sha="new")

        old.refresh_from_db()
        with pytest.raises(errors.StaleRunError):
            approvals.finalize_run(run_id=old.id, user_id=user.id, approve_all=True, commit_to_github=False)

    def test_approve_latest_run_succeeds(self, repo, user):
        self._create_run(repo, commit_sha="old")
        newest = self._create_run(repo, commit_sha="new")
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="new", storage_path="p/new")

        run = approvals.finalize_run(run_id=newest.id, user_id=user.id, approve_all=True, commit_to_github=False)

        assert run.approved is True

    def test_approved_run_superseded_but_stays_clean(self, repo, user, team):
        first = self._create_run(repo, commit_sha="1st")
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="1st", storage_path="p/1st")
        approvals.finalize_run(run_id=first.id, user_id=user.id, approve_all=True, commit_to_github=False)

        self._create_run(repo, commit_sha="2nd")

        first.refresh_from_db()
        assert first.superseded_by is not None
        # Approved runs still show in clean filter, not stale
        clean = list(run_queries.list_runs_for_team(team.id, review_state="clean"))
        assert any(r.id == first.id for r in clean)

    def test_clean_run_superseded_but_stays_clean(self, repo, team, mocker):
        clean_run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="clean",
                branch="feat/x",
                pr_number=1,
                snapshots=[SnapshotManifestItem(identifier="snap", content_hash="same")],
                baseline_hashes={"snap": "same"},
            ),
            team_id=repo.team_id,
        )

        # Classification happens at complete_run time
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"snap": "same"}, 0),
        )
        runs.complete_run(clean_run.id)

        self._create_run(repo, commit_sha="next")

        clean_run.refresh_from_db()
        assert clean_run.superseded_by is not None
        # Clean runs still show in clean filter, not stale
        clean = list(run_queries.list_runs_for_team(team.id, review_state="clean"))
        assert any(r.id == clean_run.id for r in clean)

    def test_approved_run_shows_in_clean_not_stale(self, repo, team, user):
        first = self._create_run(repo, commit_sha="1st")
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="1st", storage_path="p/1st")
        approvals.finalize_run(run_id=first.id, user_id=user.id, approve_all=True, commit_to_github=False)

        self._create_run(repo, commit_sha="2nd")

        stale = list(run_queries.list_runs_for_team(team.id, review_state="stale"))
        clean = list(run_queries.list_runs_for_team(team.id, review_state="clean"))

        assert len(stale) == 0
        clean_shas = {r.commit_sha for r in clean}
        assert "1st" in clean_shas


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRecomputeRun:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=77777, repo_full_name="org/test-repo")

    def _create_completed_run(self, repo, mocker, identifiers_and_hashes, baseline=None, metadata=None):
        snapshots = [SnapshotManifestItem(identifier=ident, content_hash=h) for ident, h in identifiers_and_hashes]
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="my-branch",
                pr_number=1,
                snapshots=snapshots,
                metadata=metadata or {},
            ),
            team_id=repo.team_id,
        )
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=(baseline or {}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        mocker.patch("products.visual_review.backend.logic.ci_status._post_commit_status")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)
        run.refresh_from_db()
        return run

    def test_recompute_run_updates_counts_after_quarantine(self, repo, team, mocker):
        from products.visual_review.backend.models import QuarantinedIdentifier

        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[("Button", "h1"), ("Card", "h2")],
            baseline={"Button": "old1", "Card": "old2"},
        )
        assert run.changed_count == 2

        QuarantinedIdentifier.objects.create(
            repo=repo,
            team_id=team.id,
            identifier="Button",
            run_type=RunType.STORYBOOK,
            reason="flaky",
        )
        QuarantinedIdentifier.objects.create(
            repo=repo,
            team_id=team.id,
            identifier="Card",
            run_type=RunType.STORYBOOK,
            reason="flaky",
        )

        result = runs.recompute_run(run.id, team_id=team.id)

        assert result["counts_changed"] is True
        run.refresh_from_db()
        assert run.changed_count == 0

    def test_recompute_run_no_change_without_quarantine(self, repo, team, mocker):
        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[("Button", "h1")],
            baseline={"Button": "old1"},
        )

        result = runs.recompute_run(run.id, team_id=team.id)

        assert result["counts_changed"] is False
        assert "CI job ID not available" in result["ci_rerun_error"]

    def test_recompute_run_rejects_non_completed_run(self, repo, team, mocker):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id, run_type=RunType.STORYBOOK, commit_sha="abc", branch="main", pr_number=1, snapshots=[]
            ),
            team_id=repo.team_id,
        )

        with pytest.raises(ValueError, match="Can only recompute completed runs"):
            runs.recompute_run(run.id, team_id=team.id)

    def test_recompute_run_rejects_approved_run(self, repo, team, user, mocker):
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="h1", storage_path="p/h1")
        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[("Button", "h1")],
            baseline={"Button": "old1"},
        )
        approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)

        with pytest.raises(ValueError, match="already approved"):
            runs.recompute_run(run.id, team_id=team.id)

    def test_recompute_run_reports_missing_ci_metadata(self, repo, team, mocker):
        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[("Button", "h1")],
            baseline={"Button": "old1"},
        )

        result = runs.recompute_run(run.id, team_id=team.id)

        assert result["ci_rerun_triggered"] is False
        assert "CI job ID not available" in result["ci_rerun_error"]

    def test_recompute_run_triggers_ci_rerun(self, repo, team, mocker):
        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[("Button", "h1")],
            baseline={"Button": "old1"},
            metadata={"github_check_run_id": "72855643533"},
        )

        mocker.patch(
            "products.visual_review.backend.logic.ci_status._rerun_github_job",
            return_value=(True, None),
        )

        result = runs.recompute_run(run.id, team_id=team.id)

        assert result["ci_rerun_triggered"] is True
        assert result["ci_rerun_error"] is None

    def test_recompute_run_handles_ci_rerun_failure(self, repo, team, mocker):
        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[("Button", "h1")],
            baseline={"Button": "old1"},
            metadata={"github_check_run_id": "72855643533"},
        )

        mocker.patch(
            "products.visual_review.backend.logic.ci_status._rerun_github_job",
            return_value=(False, "GitHub API returned 403 when rerunning job"),
        )

        result = runs.recompute_run(run.id, team_id=team.id)

        assert result["ci_rerun_triggered"] is False
        assert "403" in result["ci_rerun_error"]
