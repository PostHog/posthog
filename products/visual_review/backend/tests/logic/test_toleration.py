"""Unit tests for logic/toleration.py — Tolerated hashes."""

from datetime import timedelta

import pytest

from django.utils import timezone

from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import ActorType, RunType, SnapshotResult
from products.visual_review.backend.logic import artifact_store, repos, runs, toleration
from products.visual_review.backend.models import ToleratedHash
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestToleratedHashes:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=99997, repo_full_name="org/test-tol")

    def _create_completed_run(
        self, repo, mocker, identifier="Button", current_hash="new_hash", baseline_hash="old_hash"
    ):
        artifact_store.get_or_create_artifact(
            repo_id=repo.id, content_hash=current_hash, storage_path=f"p/{current_hash}"
        )
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier=identifier, content_hash=current_hash)],
                baseline_hashes={identifier: baseline_hash},
            ),
            team_id=repo.team_id,
        )
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({identifier: baseline_hash}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)
        return run

    @pytest.mark.parametrize(
        "actor,expected_reason",
        [(ActorType.HUMAN, "human"), (ActorType.AGENT, "agent")],
    )
    def test_mark_snapshot_as_tolerated(self, repo, user, mocker, actor, expected_reason):
        run = self._create_completed_run(repo, mocker)
        snapshot = run.snapshots.first()
        assert snapshot.result == SnapshotResult.CHANGED

        updated = toleration.mark_snapshot_as_tolerated(run.id, snapshot.id, user.id, repo.team_id, actor=actor)

        assert updated.result == SnapshotResult.CHANGED  # result stays technical truth
        assert updated.review_state == "tolerated"
        assert updated.reviewed_by_id == user.id
        assert updated.tolerated_hash_match is not None
        assert updated.tolerated_hash_match.alternate_hash == "new_hash"
        assert updated.tolerated_hash_match.baseline_hash == "old_hash"
        assert updated.tolerated_hash_match.reason == expected_reason

    def test_tolerating_revives_an_expired_hash(self, repo, user, mocker):
        run = self._create_completed_run(repo, mocker)
        snapshot = run.snapshots.first()
        toleration.mark_snapshot_as_tolerated(run.id, snapshot.id, user.id, repo.team_id)
        tolerated = ToleratedHash.objects.get(repo_id=repo.id, identifier="Button")
        created_at = tolerated.created_at
        tolerated.expires_at = timezone.now() - timedelta(days=1)
        tolerated.save(update_fields=["expires_at"])

        updated = toleration.mark_snapshot_as_tolerated(
            run.id, snapshot.id, user.id, repo.team_id, actor=ActorType.AGENT
        )

        # An expired row is invisible to the classifier, so leaving it expired would
        # make the toleration look like it worked and change nothing.
        assert updated.tolerated_hash_match is not None
        assert updated.tolerated_hash_match.expires_at is None
        # The row is shared with the snapshots that already matched it, and the
        # flakiness and overview aggregates read reason and created_at to describe
        # those runs, so a revive must not rewrite them.
        assert updated.tolerated_hash_match.reason == "human"
        assert updated.tolerated_hash_match.created_at == created_at
        assert ToleratedHash.objects.filter(repo_id=repo.id, identifier="Button").count() == 1

    def test_mark_unchanged_snapshot_rejected(self, repo, user, mocker):
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="same", storage_path="p/same")
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="same")],
                baseline_hashes={"Button": "same"},
            ),
            team_id=repo.team_id,
        )
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"Button": "same"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)

        snapshot = run.snapshots.first()
        assert snapshot is not None
        with pytest.raises(ValueError, match="Can only mark CHANGED"):
            toleration.mark_snapshot_as_tolerated(run.id, snapshot.id, user.id, repo.team_id)

    def test_tolerated_hash_shortcircuits_classification(self, repo, user, mocker):
        from products.visual_review.backend.models import ToleratedHash

        # Create a tolerated hash entry
        ToleratedHash.objects.create(
            repo=repo,
            team_id=repo.team_id,
            identifier="Button",
            baseline_hash="old_hash",
            alternate_hash="new_hash",
            reason="auto_threshold",
        )

        # Run with the same hashes — should be classified UNCHANGED via cache
        run = self._create_completed_run(repo, mocker)
        snapshot = run.snapshots.first()

        assert snapshot.result == SnapshotResult.UNCHANGED
        assert snapshot.classification_reason == "tolerated_hash"
        assert snapshot.tolerated_hash_match is not None

    def test_tolerated_hash_expires_on_baseline_change(self, repo, user, mocker):
        from products.visual_review.backend.models import ToleratedHash

        # Tolerated hash tied to OLD baseline
        ToleratedHash.objects.create(
            repo=repo,
            team_id=repo.team_id,
            identifier="Button",
            baseline_hash="old_hash",
            alternate_hash="new_hash",
            reason="auto_threshold",
        )

        # Run with a DIFFERENT baseline — tolerated hash should not match
        run = self._create_completed_run(repo, mocker, baseline_hash="updated_baseline")
        snapshot = run.snapshots.first()

        assert snapshot.result == SnapshotResult.CHANGED
        assert snapshot.classification_reason == ""
        assert snapshot.tolerated_hash_match is None

    def test_get_tolerated_hashes_for_identifier(self, repo):
        from products.visual_review.backend.models import ToleratedHash

        ToleratedHash.objects.create(
            repo=repo,
            team_id=repo.team_id,
            identifier="Button",
            baseline_hash="b1",
            alternate_hash="c1",
            reason="auto_threshold",
        )
        ToleratedHash.objects.create(
            repo=repo,
            team_id=repo.team_id,
            identifier="Button",
            baseline_hash="b1",
            alternate_hash="c2",
            reason="human",
        )
        ToleratedHash.objects.create(
            repo=repo,
            team_id=repo.team_id,
            identifier="Other",
            baseline_hash="b1",
            alternate_hash="c3",
            reason="auto_threshold",
        )

        results = toleration.get_tolerated_hashes_for_identifier(repo.id, "Button")
        assert len(results) == 2
        assert {r.alternate_hash for r in results} == {"c1", "c2"}
