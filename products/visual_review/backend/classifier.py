"""
Snapshot classification against baselines.

Determines whether each snapshot is unchanged, changed, new, or removed
by comparing current hashes against baseline hashes. Links artifact FKs.

Uses bulk DB operations to avoid N+1 queries — a master run with 2800
unchanged snapshots hits ~5 queries instead of ~8400.
"""

from django.db.models import Case, CharField, F, Value, When

from .db import WRITER_DB
from .facade.enums import ClassificationReason, ReviewState, SnapshotResult
from .models import Artifact, Run, RunSnapshot, ToleratedHash


class SnapshotClassifier:
    def __init__(
        self,
        run: Run,
        baseline: dict[str, str],
        tolerated_lookup: dict[tuple[str, str, str], ToleratedHash],
    ):
        self.run = run
        self.repo_id = run.repo_id
        self.team_id = run.team_id
        self.baseline = baseline
        self.tolerated_lookup = tolerated_lookup
        self.snapshots_qs = run.snapshots.using(WRITER_DB)
        self.artifact_cache: dict[str, Artifact] = {}

    def classify(self) -> None:
        self.stamp_baseline_hashes()
        self.prefetch_artifacts()
        self.classify_exact_matches()
        self.link_artifacts_for_exact_matches()
        self.classify_remaining()
        self.create_removed_snapshots()

    def stamp_baseline_hashes(self) -> None:
        """Set baseline_hash on all snapshots in one UPDATE with CASE/WHEN."""
        if not self.baseline:
            return
        whens = [When(identifier=ident, then=Value(bhash)) for ident, bhash in self.baseline.items()]
        self.snapshots_qs.update(baseline_hash=Case(*whens, default=Value(""), output_field=CharField()))

    def prefetch_artifacts(self) -> None:
        """Load all artifacts for this repo's hashes in one query."""
        all_hashes: set[str] = set()
        for current_hash, baseline_hash in self.snapshots_qs.values_list("current_hash", "baseline_hash"):
            if current_hash:
                all_hashes.add(current_hash)
            if baseline_hash:
                all_hashes.add(baseline_hash)
        # Also include baseline hashes for removed detection
        all_hashes.update(h for h in self.baseline.values() if h)

        if all_hashes:
            for art in Artifact.objects.filter(repo_id=self.repo_id, content_hash__in=all_hashes):
                self.artifact_cache[art.content_hash] = art

    def classify_exact_matches(self) -> None:
        """Bulk-update snapshots where current_hash == baseline_hash."""
        self.snapshots_qs.exclude(baseline_hash="").filter(current_hash=F("baseline_hash")).update(
            result=SnapshotResult.UNCHANGED,
            classification_reason=ClassificationReason.EXACT,
            review_state="",
        )

    def link_artifacts_for_exact_matches(self) -> None:
        """Batch-link current/baseline artifact FKs for unchanged snapshots."""
        exact = list(
            self.snapshots_qs.filter(
                result=SnapshotResult.UNCHANGED,
                classification_reason=ClassificationReason.EXACT,
            )
        )
        if not exact:
            return
        for snapshot in exact:
            snapshot.current_artifact = self.artifact_cache.get(snapshot.current_hash)
            snapshot.baseline_artifact = self.artifact_cache.get(snapshot.baseline_hash)
        RunSnapshot.objects.using(WRITER_DB).bulk_update(
            exact, ["current_artifact", "baseline_artifact"], batch_size=500
        )

    def classify_remaining(self) -> None:
        """Classify non-exact snapshots individually (new, changed, tolerated)."""
        remaining = list(
            self.snapshots_qs.exclude(
                result=SnapshotResult.UNCHANGED,
                classification_reason=ClassificationReason.EXACT,
            )
        )
        if not remaining:
            return

        for snapshot in remaining:
            baseline_hash = snapshot.baseline_hash
            classification_reason = ""
            tolerated_match = None

            if not baseline_hash:
                result = SnapshotResult.NEW
            else:
                match = self.tolerated_lookup.get((snapshot.identifier, baseline_hash, snapshot.current_hash))
                if match is not None:
                    result = SnapshotResult.UNCHANGED
                    classification_reason = ClassificationReason.TOLERATED_HASH
                    tolerated_match = match
                else:
                    result = SnapshotResult.CHANGED

            review_state = (
                ReviewState.PENDING
                if result in (SnapshotResult.CHANGED, SnapshotResult.NEW, SnapshotResult.REMOVED)
                else ""
            )

            snapshot.result = result
            snapshot.classification_reason = classification_reason
            snapshot.review_state = review_state
            snapshot.tolerated_hash_match = tolerated_match
            snapshot.diff_percentage = tolerated_match.diff_percentage if tolerated_match else None
            snapshot.baseline_artifact = self.artifact_cache.get(baseline_hash) if baseline_hash else None
            snapshot.current_artifact = self.artifact_cache.get(snapshot.current_hash)

        RunSnapshot.objects.using(WRITER_DB).bulk_update(
            remaining,
            [
                "result",
                "classification_reason",
                "review_state",
                "tolerated_hash_match",
                "diff_percentage",
                "baseline_artifact",
                "current_artifact",
            ],
            batch_size=500,
        )

    def create_removed_snapshots(self) -> None:
        """Detect baseline identifiers missing from the run and create REMOVED rows."""
        if not self.baseline:
            return
        produced = set(self.snapshots_qs.values_list("identifier", flat=True))
        removed = [
            RunSnapshot(
                run=self.run,
                team_id=self.team_id,
                identifier=identifier,
                current_hash="",
                baseline_hash=b_hash or "",
                baseline_artifact=self.artifact_cache.get(b_hash) if b_hash else None,
                result=SnapshotResult.REMOVED,
                review_state=ReviewState.PENDING,
                metadata={},
            )
            for identifier, b_hash in self.baseline.items()
            if identifier not in produced
        ]
        if removed:
            RunSnapshot.objects.using(WRITER_DB).bulk_create(removed, ignore_conflicts=True)
