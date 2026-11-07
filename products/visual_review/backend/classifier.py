"""
Snapshot classification against baselines.

Determines whether each snapshot is unchanged, changed, new, or removed
by comparing current hashes against baseline hashes. Links artifact FKs.

Reads a run's snapshots once, classifies them in Python, and writes each row
at most once with one bulk_update. Every column the classifier sets is indexed
on RunSnapshot, so no update can be HOT: each rewrite of a row also writes
every index on the table, and a row that does not change is not written.
"""

from posthog.dataclasses import frozen

from .db import WRITER_DB
from .facade.enums import ClassificationReason, ReviewState, SnapshotResult
from .models import Artifact, Run, RunSnapshot, ToleratedHash

CLASSIFIED_FIELDS = [
    "baseline_hash",
    "result",
    "classification_reason",
    "review_state",
    "tolerated_hash_match",
    "diff_percentage",
    "baseline_artifact",
    "current_artifact",
]


@frozen
class ToleratedKey:
    identifier: str
    baseline_hash: str
    current_hash: str


class SnapshotClassifier:
    def __init__(
        self,
        run: Run,
        baseline: dict[str, str],
        tolerated_lookup: dict[ToleratedKey, ToleratedHash],
        is_partial: bool = False,
    ):
        self.run = run
        self.repo_id = run.repo_id
        self.team_id = run.team_id
        self.baseline = baseline
        self.tolerated_lookup = tolerated_lookup
        self.snapshots_qs = run.snapshots.using(WRITER_DB)
        self.artifact_cache: dict[str, Artifact] = {}
        # Caller-supplied so the client-controlled flag can be fenced
        # server-side rather than read from run.is_partial. See complete_run.
        self.is_partial = is_partial

    def classify(self) -> None:
        snapshots = list(self.snapshots_qs)
        self.prefetch_artifacts(snapshots)
        changed = [snapshot for snapshot in snapshots if self.classify_snapshot(snapshot)]
        if changed:
            RunSnapshot.objects.using(WRITER_DB).bulk_update(changed, CLASSIFIED_FIELDS, batch_size=500)
        self.create_removed_snapshots({snapshot.identifier for snapshot in snapshots})

    def prefetch_artifacts(self, snapshots: list[RunSnapshot]) -> None:
        """Load all artifacts for this repo's hashes in one query."""
        all_hashes = {snapshot.current_hash for snapshot in snapshots if snapshot.current_hash}
        # Baseline hashes cover both the stamped snapshots and the removed ones
        all_hashes.update(h for h in self.baseline.values() if h)

        if all_hashes:
            for art in Artifact.objects.filter(repo_id=self.repo_id, content_hash__in=all_hashes):
                self.artifact_cache[art.content_hash] = art

    def classify_snapshot(self, snapshot: RunSnapshot) -> bool:
        """Set the baseline hash, classification and artifact FKs. Returns whether any of them changed."""
        before = _classified_values(snapshot)

        baseline_hash = self.baseline.get(snapshot.identifier, "")
        classification_reason = ""
        tolerated_match = None

        if not baseline_hash:
            result = SnapshotResult.NEW
        elif snapshot.current_hash == baseline_hash:
            result = SnapshotResult.UNCHANGED
            classification_reason = ClassificationReason.EXACT
        else:
            match = self.tolerated_lookup.get(
                ToleratedKey(
                    identifier=snapshot.identifier,
                    baseline_hash=baseline_hash,
                    current_hash=snapshot.current_hash,
                )
            )
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

        snapshot.baseline_hash = baseline_hash
        snapshot.result = result
        snapshot.classification_reason = classification_reason
        snapshot.review_state = review_state
        snapshot.tolerated_hash_match = tolerated_match
        snapshot.diff_percentage = tolerated_match.diff_percentage if tolerated_match else None
        snapshot.baseline_artifact = self.artifact_cache.get(baseline_hash) if baseline_hash else None
        snapshot.current_artifact = self.artifact_cache.get(snapshot.current_hash)

        return _classified_values(snapshot) != before

    def create_removed_snapshots(self, produced: set[str]) -> None:
        """Detect baseline identifiers missing from the run and create REMOVED rows."""
        if not self.baseline:
            return
        if self.is_partial:
            # Partial runs only render a subset of the suite. The omitted
            # baseline identifiers haven't been deleted, they just weren't
            # exercised — leave them untouched.
            return
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


def _classified_values(snapshot: RunSnapshot) -> tuple:
    return (
        snapshot.baseline_hash,
        snapshot.result,
        snapshot.classification_reason,
        snapshot.review_state,
        snapshot.tolerated_hash_match_id,
        snapshot.diff_percentage,
        snapshot.baseline_artifact_id,
        snapshot.current_artifact_id,
    )
