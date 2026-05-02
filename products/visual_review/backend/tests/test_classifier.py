from datetime import timedelta

import pytest

from django.utils import timezone

from products.visual_review.backend.classifier import SnapshotClassifier
from products.visual_review.backend.facade.enums import (
    ClassificationReason,
    ReviewState,
    RunType,
    SnapshotResult,
    ToleratedReason,
)
from products.visual_review.backend.models import Artifact, Repo, Run, RunSnapshot, ToleratedHash
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


def _make_repo(team) -> Repo:
    return Repo.objects.create(
        team_id=team.id,
        repo_external_id=12345,
        repo_full_name="org/test-repo",
        baseline_file_paths={"storybook": ".snapshots.yml"},
    )


def _make_run(repo: Repo, snapshots: list[dict], **kwargs) -> Run:
    run = Run.objects.create(
        repo=repo,
        team_id=repo.team_id,
        run_type=kwargs.pop("run_type", RunType.STORYBOOK),
        commit_sha=kwargs.pop("commit_sha", "abc123"),
        branch=kwargs.pop("branch", "main"),
        **kwargs,
    )
    for snap in snapshots:
        RunSnapshot.objects.create(
            run=run,
            team_id=repo.team_id,
            identifier=snap["identifier"],
            current_hash=snap.get("current_hash", ""),
            metadata={},
        )
    return run


def _make_artifact(repo: Repo, content_hash: str) -> Artifact:
    return Artifact.objects.create(
        repo=repo,
        team_id=repo.team_id,
        content_hash=content_hash,
        storage_path=f"visual_review/{content_hash}",
        width=800,
        height=600,
    )


def _make_tolerated(repo: Repo, identifier: str, baseline_hash: str, alternate_hash: str, **kwargs) -> ToleratedHash:
    return ToleratedHash.objects.create(
        repo=repo,
        team_id=repo.team_id,
        identifier=identifier,
        baseline_hash=baseline_hash,
        alternate_hash=alternate_hash,
        reason=kwargs.pop("reason", ToleratedReason.HUMAN),
        **kwargs,
    )


def _classify(run: Run, baseline: dict[str, str], tolerated_lookup: dict | None = None) -> dict[str, RunSnapshot]:
    classifier = SnapshotClassifier(run, baseline, tolerated_lookup or {})
    classifier.classify()
    return {s.identifier: s for s in run.snapshots.all()}


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestExactMatchClassification:
    @pytest.fixture
    def repo(self, team):
        return _make_repo(team)

    def test_unchanged_when_hashes_match(self, repo):
        _make_artifact(repo, "aaa")
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "aaa"}])

        result = _classify(run, {"Button": "aaa"})

        assert result["Button"].result == SnapshotResult.UNCHANGED
        assert result["Button"].classification_reason == ClassificationReason.EXACT
        assert result["Button"].review_state == ""

    def test_exact_match_links_both_artifacts(self, repo):
        art = _make_artifact(repo, "aaa")
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "aaa"}])

        result = _classify(run, {"Button": "aaa"})

        assert result["Button"].current_artifact_id == art.id
        assert result["Button"].baseline_artifact_id == art.id

    def test_multiple_exact_matches_bulk_classified(self, repo):
        _make_artifact(repo, "h1")
        _make_artifact(repo, "h2")
        _make_artifact(repo, "h3")
        run = _make_run(
            repo,
            [
                {"identifier": "A", "current_hash": "h1"},
                {"identifier": "B", "current_hash": "h2"},
                {"identifier": "C", "current_hash": "h3"},
            ],
        )

        result = _classify(run, {"A": "h1", "B": "h2", "C": "h3"})

        assert all(s.result == SnapshotResult.UNCHANGED for s in result.values())
        assert all(s.classification_reason == ClassificationReason.EXACT for s in result.values())


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestChangedClassification:
    @pytest.fixture
    def repo(self, team):
        return _make_repo(team)

    def test_changed_when_hashes_differ(self, repo):
        _make_artifact(repo, "old")
        _make_artifact(repo, "new")
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "new"}])

        result = _classify(run, {"Button": "old"})

        assert result["Button"].result == SnapshotResult.CHANGED
        assert result["Button"].classification_reason == ""
        assert result["Button"].review_state == ReviewState.PENDING

    def test_changed_links_both_artifacts(self, repo):
        art_old = _make_artifact(repo, "old")
        art_new = _make_artifact(repo, "new")
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "new"}])

        result = _classify(run, {"Button": "old"})

        assert result["Button"].current_artifact_id == art_new.id
        assert result["Button"].baseline_artifact_id == art_old.id


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestNewClassification:
    @pytest.fixture
    def repo(self, team):
        return _make_repo(team)

    def test_new_when_no_baseline(self, repo):
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "abc"}])

        result = _classify(run, {})

        assert result["Button"].result == SnapshotResult.NEW
        assert result["Button"].review_state == ReviewState.PENDING

    def test_new_when_identifier_not_in_baseline(self, repo):
        run = _make_run(
            repo,
            [
                {"identifier": "New", "current_hash": "new_hash"},
                {"identifier": "Existing", "current_hash": "same"},
            ],
        )

        result = _classify(run, {"Existing": "same"})

        assert result["New"].result == SnapshotResult.NEW
        assert result["Existing"].result == SnapshotResult.UNCHANGED

    def test_new_snapshot_has_no_baseline_artifact(self, repo):
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "abc"}])

        result = _classify(run, {})

        assert result["Button"].baseline_artifact is None


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRemovedClassification:
    @pytest.fixture
    def repo(self, team):
        return _make_repo(team)

    def test_removed_when_baseline_identifier_missing_from_run(self, repo):
        art = _make_artifact(repo, "old_hash")
        run = _make_run(repo, [{"identifier": "Kept", "current_hash": "h1"}])

        result = _classify(run, {"Kept": "h1", "Deleted": "old_hash"})

        assert "Deleted" in result
        assert result["Deleted"].result == SnapshotResult.REMOVED
        assert result["Deleted"].review_state == ReviewState.PENDING
        assert result["Deleted"].current_hash == ""
        assert result["Deleted"].baseline_hash == "old_hash"
        assert result["Deleted"].baseline_artifact_id == art.id

    def test_no_removed_when_baseline_empty(self, repo):
        run = _make_run(repo, [{"identifier": "A", "current_hash": "h1"}])

        result = _classify(run, {})

        assert len(result) == 1

    def test_removed_idempotent_via_ignore_conflicts(self, repo):
        run = _make_run(repo, [])
        baseline = {"Gone": "old_hash"}

        _classify(run, baseline)
        _classify(run, baseline)

        assert run.snapshots.filter(identifier="Gone").count() == 1


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestToleratedHashClassification:
    @pytest.fixture
    def repo(self, team):
        return _make_repo(team)

    def test_tolerated_hash_classifies_as_unchanged(self, repo):
        tolerated = _make_tolerated(repo, "Button", "baseline_h", "current_h")
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "current_h"}])

        lookup = {("Button", "baseline_h", "current_h"): tolerated}
        result = _classify(run, {"Button": "baseline_h"}, lookup)

        assert result["Button"].result == SnapshotResult.UNCHANGED
        assert result["Button"].classification_reason == ClassificationReason.TOLERATED_HASH
        assert result["Button"].tolerated_hash_match_id == tolerated.id
        assert result["Button"].review_state == ""

    def test_tolerated_hash_propagates_diff_percentage(self, repo):
        tolerated = _make_tolerated(repo, "Button", "baseline_h", "current_h", diff_percentage=0.42)
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "current_h"}])

        lookup = {("Button", "baseline_h", "current_h"): tolerated}
        result = _classify(run, {"Button": "baseline_h"}, lookup)

        assert result["Button"].diff_percentage == 0.42

    def test_tolerated_hash_without_diff_percentage_sets_none(self, repo):
        tolerated = _make_tolerated(repo, "Button", "baseline_h", "current_h")
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "current_h"}])

        lookup = {("Button", "baseline_h", "current_h"): tolerated}
        result = _classify(run, {"Button": "baseline_h"}, lookup)

        assert result["Button"].diff_percentage is None

    def test_tolerated_hash_not_matched_when_different_identifier(self, repo):
        tolerated = _make_tolerated(repo, "OtherButton", "baseline_h", "current_h")
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "current_h"}])

        lookup = {("OtherButton", "baseline_h", "current_h"): tolerated}
        result = _classify(run, {"Button": "baseline_h"}, lookup)

        assert result["Button"].result == SnapshotResult.CHANGED

    def test_tolerated_hash_not_matched_when_different_baseline(self, repo):
        tolerated = _make_tolerated(repo, "Button", "different_baseline", "current_h")
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "current_h"}])

        lookup = {("Button", "different_baseline", "current_h"): tolerated}
        result = _classify(run, {"Button": "baseline_h"}, lookup)

        assert result["Button"].result == SnapshotResult.CHANGED

    def test_tolerated_hash_not_matched_when_different_current(self, repo):
        tolerated = _make_tolerated(repo, "Button", "baseline_h", "expected_current")
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "actual_current"}])

        lookup = {("Button", "baseline_h", "expected_current"): tolerated}
        result = _classify(run, {"Button": "baseline_h"}, lookup)

        assert result["Button"].result == SnapshotResult.CHANGED

    def test_empty_tolerated_lookup_means_no_tolerance(self, repo):
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "new_h"}])

        result = _classify(run, {"Button": "old_h"}, {})

        assert result["Button"].result == SnapshotResult.CHANGED


def _build_tolerated_lookup(
    repo: Repo, identifiers: set[str], baseline_hashes: set[str]
) -> dict[tuple[str, str, str], ToleratedHash]:
    """Mirrors the tolerated hash query in logic.complete_run."""
    from django.db.models import Q

    now = timezone.now()
    lookup: dict[tuple[str, str, str], ToleratedHash] = {}
    for t in ToleratedHash.objects.filter(
        repo=repo,
        identifier__in=identifiers,
        baseline_hash__in=baseline_hashes,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)):
        lookup[(t.identifier, t.baseline_hash, t.alternate_hash)] = t
    return lookup


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestExpiredToleratedHashFiltering:
    """The tolerated lookup is built in complete_run before being passed to the
    classifier. These tests verify that the query correctly filters on expires_at,
    and that the classifier behaves accordingly."""

    @pytest.fixture
    def repo(self, team):
        return _make_repo(team)

    def test_expired_tolerated_hash_excluded(self, repo):
        _make_tolerated(repo, "Button", "baseline_h", "current_h", expires_at=timezone.now() - timedelta(hours=1))
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "current_h"}])

        lookup = _build_tolerated_lookup(repo, {"Button"}, {"baseline_h"})

        assert len(lookup) == 0

        result = _classify(run, {"Button": "baseline_h"}, lookup)

        assert result["Button"].result == SnapshotResult.CHANGED

    def test_active_tolerated_hash_included(self, repo):
        tolerated = _make_tolerated(
            repo, "Button", "baseline_h", "current_h", expires_at=timezone.now() + timedelta(hours=1)
        )
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "current_h"}])

        lookup = _build_tolerated_lookup(repo, {"Button"}, {"baseline_h"})

        assert len(lookup) == 1

        result = _classify(run, {"Button": "baseline_h"}, lookup)

        assert result["Button"].result == SnapshotResult.UNCHANGED
        assert result["Button"].tolerated_hash_match_id == tolerated.id

    def test_no_expiry_tolerated_hash_included(self, repo):
        tolerated = _make_tolerated(repo, "Button", "baseline_h", "current_h", expires_at=None)
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "current_h"}])

        lookup = _build_tolerated_lookup(repo, {"Button"}, {"baseline_h"})

        assert len(lookup) == 1

        result = _classify(run, {"Button": "baseline_h"}, lookup)

        assert result["Button"].result == SnapshotResult.UNCHANGED
        assert result["Button"].tolerated_hash_match_id == tolerated.id

    def test_mixed_expired_and_active(self, repo):
        _make_tolerated(repo, "Expired", "base_e", "curr_e", expires_at=timezone.now() - timedelta(minutes=5))
        active = _make_tolerated(repo, "Active", "base_a", "curr_a", expires_at=timezone.now() + timedelta(hours=24))

        run = _make_run(
            repo,
            [
                {"identifier": "Expired", "current_hash": "curr_e"},
                {"identifier": "Active", "current_hash": "curr_a"},
            ],
        )

        lookup = _build_tolerated_lookup(repo, {"Expired", "Active"}, {"base_e", "base_a"})

        assert len(lookup) == 1
        assert ("Active", "base_a", "curr_a") in lookup

        result = _classify(run, {"Expired": "base_e", "Active": "base_a"}, lookup)

        assert result["Expired"].result == SnapshotResult.CHANGED
        assert result["Active"].result == SnapshotResult.UNCHANGED
        assert result["Active"].tolerated_hash_match_id == active.id


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestBaselineHashStamping:
    @pytest.fixture
    def repo(self, team):
        return _make_repo(team)

    def test_stamps_baseline_hash_on_matching_identifiers(self, repo):
        run = _make_run(
            repo,
            [
                {"identifier": "A", "current_hash": "h1"},
                {"identifier": "B", "current_hash": "h2"},
            ],
        )

        _classify(run, {"A": "base_a", "B": "base_b"})

        snapshots = {s.identifier: s for s in run.snapshots.all()}
        assert snapshots["A"].baseline_hash == "base_a"
        assert snapshots["B"].baseline_hash == "base_b"

    def test_no_baseline_for_new_identifiers(self, repo):
        run = _make_run(repo, [{"identifier": "New", "current_hash": "h1"}])

        _classify(run, {"Other": "base"})

        snap = run.snapshots.get(identifier="New")
        assert snap.baseline_hash == ""

    def test_empty_baseline_skips_stamping(self, repo):
        run = _make_run(repo, [{"identifier": "A", "current_hash": "h1"}])

        _classify(run, {})

        snap = run.snapshots.get(identifier="A")
        assert snap.baseline_hash == ""


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestArtifactPrefetch:
    @pytest.fixture
    def repo(self, team):
        return _make_repo(team)

    def test_links_current_artifact_for_new_snapshot(self, repo):
        art = _make_artifact(repo, "new_hash")
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "new_hash"}])

        result = _classify(run, {})

        assert result["Button"].current_artifact_id == art.id

    def test_links_baseline_artifact_for_removed_snapshot(self, repo):
        art = _make_artifact(repo, "old_hash")
        run = _make_run(repo, [])

        result = _classify(run, {"Removed": "old_hash"})

        assert result["Removed"].baseline_artifact_id == art.id

    def test_no_artifact_when_hash_missing(self, repo):
        run = _make_run(repo, [{"identifier": "Button", "current_hash": "no_artifact_for_this"}])

        result = _classify(run, {})

        assert result["Button"].current_artifact is None


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestMixedClassification:
    @pytest.fixture
    def repo(self, team):
        return _make_repo(team)

    def test_mixed_unchanged_changed_new_removed(self, repo):
        _make_artifact(repo, "same_hash")
        _make_artifact(repo, "old_hash")
        _make_artifact(repo, "new_hash")
        _make_artifact(repo, "removed_hash")

        run = _make_run(
            repo,
            [
                {"identifier": "Unchanged", "current_hash": "same_hash"},
                {"identifier": "Changed", "current_hash": "new_hash"},
                {"identifier": "New", "current_hash": "brand_new"},
            ],
        )

        result = _classify(
            run,
            {
                "Unchanged": "same_hash",
                "Changed": "old_hash",
                "Removed": "removed_hash",
            },
        )

        assert result["Unchanged"].result == SnapshotResult.UNCHANGED
        assert result["Unchanged"].classification_reason == ClassificationReason.EXACT
        assert result["Changed"].result == SnapshotResult.CHANGED
        assert result["New"].result == SnapshotResult.NEW
        assert result["Removed"].result == SnapshotResult.REMOVED
        assert len(result) == 4

    def test_review_state_only_set_for_actionable_results(self, repo):
        _make_artifact(repo, "same")
        run = _make_run(
            repo,
            [
                {"identifier": "Unchanged", "current_hash": "same"},
                {"identifier": "Changed", "current_hash": "different"},
                {"identifier": "New", "current_hash": "brand_new"},
            ],
        )

        result = _classify(run, {"Unchanged": "same", "Changed": "old"})

        assert result["Unchanged"].review_state == ""
        assert result["Changed"].review_state == ReviewState.PENDING
        assert result["New"].review_state == ReviewState.PENDING

    def test_tolerated_alongside_exact_and_changed(self, repo):
        _make_artifact(repo, "exact_h")
        tolerated = _make_tolerated(repo, "Tolerated", "tol_base", "tol_curr")

        run = _make_run(
            repo,
            [
                {"identifier": "Exact", "current_hash": "exact_h"},
                {"identifier": "Tolerated", "current_hash": "tol_curr"},
                {"identifier": "Changed", "current_hash": "new_h"},
            ],
        )

        lookup = {("Tolerated", "tol_base", "tol_curr"): tolerated}
        result = _classify(run, {"Exact": "exact_h", "Tolerated": "tol_base", "Changed": "old_h"}, lookup)

        assert result["Exact"].result == SnapshotResult.UNCHANGED
        assert result["Exact"].classification_reason == ClassificationReason.EXACT
        assert result["Tolerated"].result == SnapshotResult.UNCHANGED
        assert result["Tolerated"].classification_reason == ClassificationReason.TOLERATED_HASH
        assert result["Changed"].result == SnapshotResult.CHANGED

    def test_large_run_all_unchanged(self, repo):
        count = 50
        for i in range(count):
            _make_artifact(repo, f"hash_{i}")
        run = _make_run(repo, [{"identifier": f"snap_{i}", "current_hash": f"hash_{i}"} for i in range(count)])
        baseline = {f"snap_{i}": f"hash_{i}" for i in range(count)}

        result = _classify(run, baseline)

        assert len(result) == count
        assert all(s.result == SnapshotResult.UNCHANGED for s in result.values())
