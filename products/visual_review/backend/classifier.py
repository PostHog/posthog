"""
Snapshot classification against baselines.

Determines whether each snapshot is unchanged, changed, new, or removed
by comparing current hashes against baseline hashes. Links artifact FKs.

Reads the run's snapshots once, classifies them in Python, and writes each
row that changes once, with a set-based UPDATE. The number of queries does
not grow with the number of snapshots.
"""

from dataclasses import replace
from uuid import UUID

from django.db import connections

from posthog.dataclasses import frozen

from .db import WRITER_DB
from .facade.enums import ClassificationReason, ReviewState, SnapshotResult
from .models import Artifact, Run, RunSnapshot, ToleratedHash

# Bounds the size of one UPDATE statement and of its parameter arrays.
WRITE_BATCH_SIZE = 2000

# Joins the new values to the rows by primary key. A CASE expression with one
# WHEN per row makes Postgres test every WHEN for every row, and that cost
# grows with the square of the number of snapshots.
# Trusted identifier: the table name comes from Django ORM metadata.
_WRITE_CLASSIFICATIONS_SQL = f"""
    UPDATE {RunSnapshot._meta.db_table} AS snapshot
    SET baseline_hash = classified.baseline_hash,
        result = classified.result,
        classification_reason = classified.classification_reason,
        review_state = classified.review_state,
        tolerated_hash_match_id = classified.tolerated_hash_match_id,
        diff_percentage = classified.diff_percentage,
        baseline_artifact_id = classified.baseline_artifact_id,
        current_artifact_id = classified.current_artifact_id
    FROM unnest(
        %s::uuid[],
        %s::varchar[],
        %s::varchar[],
        %s::varchar[],
        %s::varchar[],
        %s::uuid[],
        %s::float8[],
        %s::uuid[],
        %s::uuid[]
    ) AS classified(
        id,
        baseline_hash,
        result,
        classification_reason,
        review_state,
        tolerated_hash_match_id,
        diff_percentage,
        baseline_artifact_id,
        current_artifact_id
    )
    WHERE snapshot.run_id = %s AND snapshot.id = classified.id
"""


@frozen
class ToleratedKey:
    identifier: str
    baseline_hash: str
    current_hash: str


@frozen
class SnapshotClassification:
    baseline_hash: str
    result: str
    classification_reason: str
    review_state: str
    tolerated_hash_match_id: UUID | None
    diff_percentage: float | None
    baseline_artifact_id: UUID | None
    current_artifact_id: UUID | None


@frozen
class StoredSnapshot:
    id: UUID
    identifier: str
    current_hash: str
    classification: SnapshotClassification


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
        self.artifact_ids: dict[str, UUID] = {}
        # Caller-supplied so the client-controlled flag can be fenced
        # server-side rather than read from run.is_partial. See complete_run.
        self.is_partial = is_partial

    def classify(self) -> None:
        stored = self.load_snapshots()
        stamped = [self.stamp_baseline_hash(snapshot) for snapshot in stored]
        self.prefetch_artifacts(stamped)
        changed = [
            (snapshot.id, classification)
            for snapshot, stamped_snapshot in zip(stored, stamped, strict=True)
            if (classification := self.classify_snapshot(stamped_snapshot)) != snapshot.classification
        ]
        self.write_classifications(changed)
        self.create_removed_snapshots()

    def load_snapshots(self) -> list[StoredSnapshot]:
        rows = self.snapshots_qs.values_list(
            "id",
            "identifier",
            "current_hash",
            "baseline_hash",
            "result",
            "classification_reason",
            "review_state",
            "tolerated_hash_match_id",
            "diff_percentage",
            "baseline_artifact_id",
            "current_artifact_id",
        )
        return [
            StoredSnapshot(
                id=snapshot_id,
                identifier=identifier,
                current_hash=current_hash,
                classification=SnapshotClassification(
                    baseline_hash=baseline_hash,
                    result=result,
                    classification_reason=classification_reason,
                    review_state=review_state,
                    tolerated_hash_match_id=tolerated_hash_match_id,
                    diff_percentage=diff_percentage,
                    baseline_artifact_id=baseline_artifact_id,
                    current_artifact_id=current_artifact_id,
                ),
            )
            for (
                snapshot_id,
                identifier,
                current_hash,
                baseline_hash,
                result,
                classification_reason,
                review_state,
                tolerated_hash_match_id,
                diff_percentage,
                baseline_artifact_id,
                current_artifact_id,
            ) in rows
        ]

    def stamp_baseline_hash(self, snapshot: StoredSnapshot) -> StoredSnapshot:
        """Take the baseline hash from the baseline. Without a baseline, keep the stored hash."""
        if not self.baseline:
            return snapshot
        baseline_hash = self.baseline.get(snapshot.identifier, "")
        return replace(snapshot, classification=replace(snapshot.classification, baseline_hash=baseline_hash))

    def prefetch_artifacts(self, snapshots: list[StoredSnapshot]) -> None:
        """Load all artifacts for this repo's hashes in one query."""
        all_hashes: set[str] = set()
        for snapshot in snapshots:
            if snapshot.current_hash:
                all_hashes.add(snapshot.current_hash)
            if snapshot.classification.baseline_hash:
                all_hashes.add(snapshot.classification.baseline_hash)
        # Also include baseline hashes for removed detection
        all_hashes.update(h for h in self.baseline.values() if h)

        if all_hashes:
            self.artifact_ids.update(
                Artifact.objects.filter(repo_id=self.repo_id, content_hash__in=all_hashes).values_list(
                    "content_hash", "id"
                )
            )

    def classify_snapshot(self, snapshot: StoredSnapshot) -> SnapshotClassification:
        stored = snapshot.classification
        baseline_hash = stored.baseline_hash

        if baseline_hash and snapshot.current_hash == baseline_hash:
            stored = replace(
                stored,
                result=SnapshotResult.UNCHANGED,
                classification_reason=ClassificationReason.EXACT,
                review_state="",
            )
        if stored.result == SnapshotResult.UNCHANGED and stored.classification_reason == ClassificationReason.EXACT:
            return replace(
                stored,
                current_artifact_id=self.artifact_ids.get(snapshot.current_hash),
                baseline_artifact_id=self.artifact_ids.get(baseline_hash),
            )

        classification_reason = ""
        tolerated_match = None
        if not baseline_hash:
            result = SnapshotResult.NEW
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

        return SnapshotClassification(
            baseline_hash=baseline_hash,
            result=result,
            classification_reason=classification_reason,
            review_state=review_state,
            tolerated_hash_match_id=tolerated_match.id if tolerated_match else None,
            diff_percentage=tolerated_match.diff_percentage if tolerated_match else None,
            baseline_artifact_id=self.artifact_ids.get(baseline_hash) if baseline_hash else None,
            current_artifact_id=self.artifact_ids.get(snapshot.current_hash),
        )

    def write_classifications(self, changed: list[tuple[UUID, SnapshotClassification]]) -> None:
        with connections[WRITER_DB].cursor() as cursor:
            for start in range(0, len(changed), WRITE_BATCH_SIZE):
                batch = changed[start : start + WRITE_BATCH_SIZE]
                classifications = [classification for _, classification in batch]
                cursor.execute(
                    _WRITE_CLASSIFICATIONS_SQL,
                    [
                        [snapshot_id for snapshot_id, _ in batch],
                        [c.baseline_hash for c in classifications],
                        [c.result for c in classifications],
                        [c.classification_reason for c in classifications],
                        [c.review_state for c in classifications],
                        [c.tolerated_hash_match_id for c in classifications],
                        [c.diff_percentage for c in classifications],
                        [c.baseline_artifact_id for c in classifications],
                        [c.current_artifact_id for c in classifications],
                        self.run.id,
                    ],
                )

    def create_removed_snapshots(self) -> None:
        """Detect baseline identifiers missing from the run and create REMOVED rows."""
        if not self.baseline:
            return
        if self.is_partial:
            # Partial runs only render a subset of the suite. The omitted
            # baseline identifiers haven't been deleted, they just weren't
            # exercised — leave them untouched.
            return
        produced = set(self.snapshots_qs.values_list("identifier", flat=True))
        removed = [
            RunSnapshot(
                run=self.run,
                team_id=self.team_id,
                identifier=identifier,
                current_hash="",
                baseline_hash=b_hash or "",
                baseline_artifact_id=self.artifact_ids.get(b_hash) if b_hash else None,
                result=SnapshotResult.REMOVED,
                review_state=ReviewState.PENDING,
                metadata={},
            )
            for identifier, b_hash in self.baseline.items()
            if identifier not in produced
        ]
        if removed:
            RunSnapshot.objects.using(WRITER_DB).bulk_create(removed, ignore_conflicts=True)
