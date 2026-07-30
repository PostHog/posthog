"""In-flight review progress, derived from the persisted working state.

The pipeline persists its working state as it goes (`pr_snapshot`, `chunk_set`,
`perspective_selection`, per-unit `perspective_result` rows, findings, verdicts), so a turn's stage
and counters can be inferred from which artefacts exist at the turn's head — no separate progress
bookkeeping. Shared by the reviews API (the UI's "Step k · stage · x/y" rows) and the PR status
comment, so the two surfaces can never disagree.
"""

import logging
import operator
from dataclasses import dataclass
from functools import reduce
from typing import Any

from django.db.models import Func, IntegerField, JSONField, Q, QuerySet
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast

from pydantic import ValidationError

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact, ReviewSkillConfig
from products.review_hog.backend.reviewer.artefact_content import (
    PerspectiveSelectionArtefact,
    ReviewIssueFinding,
    ValidationVerdict,
)
from products.review_hog.backend.reviewer.constants import BLIND_SPOT_PASS_NUMBER
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.perspective_selection import ChunkPerspectiveSelection
from products.review_hog.backend.reviewer.skill_loader import (
    CANONICAL_PERSPECTIVE_SKILL_NAMES,
    REVIEW_HOG_PERSPECTIVE_PREFIX,
)

logger = logging.getLogger(__name__)

REVIEW_STAGES = ["fetching", "chunking", "selecting", "reviewing", "deduplicating", "validating", "finalizing"]


@dataclass
class SnapshotStats:
    """PR facts from the report's latest `pr_snapshot` artefact (metadata only, never `pr_files`)."""

    meta: PRMetadata | None = None
    files_reviewed: int | None = None
    # Whether a snapshot exists for the report's CURRENT head (vs. a stale-turn fallback) — the
    # in-flight stage detection needs "has this turn fetched yet", not "was anything ever fetched".
    head_matched: bool = False


@dataclass
class TurnStats:
    """Pipeline shape of the latest turn, from `chunk_set` / `perspective_result` working state."""

    chunk_count: int | None = None
    perspective_count: int | None = None
    perspective_issue_count: int | None = None
    blind_spot_issue_count: int | None = None
    # (pass, chunk) review units completed this turn — the in-flight "reviewing" progress counter.
    perspective_reads: int | None = None
    # The selector's persisted plan for the turn: the full menu + the normalized per-chunk picks.
    # None when the turn ran without a selection (failed, skipped, or predates the feature).
    selection_roster: list[str] | None = None
    selection_chunks: list[ChunkPerspectiveSelection] | None = None


def _content_json() -> Cast:
    return Cast("content", JSONField())


def _turn_scope_q(head_by_report: dict[str, str | None]) -> Q | None:
    """OR of (report, head_sha) pairs, so artefact reads stay scoped to each report's reviewed turn
    instead of scanning the report's whole append-only history. None when no report has a head yet."""
    pairs = [(report_id, head_sha) for report_id, head_sha in head_by_report.items() if head_sha]
    if not pairs:
        return None
    return reduce(operator.or_, (Q(report_id=report_id, head_sha=head_sha) for report_id, head_sha in pairs))


def snapshot_stats(team_id: int, heads: dict[str, str | None]) -> dict[str, SnapshotStats]:
    """The latest snapshot's PR metadata per report, extracted DB-side, scoped to `heads`.

    `heads` maps report id → the head to describe: the completed turn's head for row/detail payloads
    (so an in-flight turn's snapshot never splices onto the previous turn's findings), the live
    watermark for in-flight progress. `pr_snapshot` content embeds the PR's full files payload
    (easily hundreds of KB), so the jsonb extraction pulls only `pr_metadata` and the `pr_files`
    length across the wire, and the `head_sha` column keeps the jsonb work off prior turns' rows.
    Prefers the snapshot matching the requested head, falling back to the newest one.
    """
    stats: dict[str, SnapshotStats] = {}
    snapshots = ReviewReportArtefact.objects.for_team(team_id).filter(
        report_id__in=list(heads), type=ReviewReportArtefact.ArtefactType.PR_SNAPSHOT
    )

    def _annotated(qs: QuerySet) -> QuerySet:
        return qs.annotate(
            meta=KeyTransform("pr_metadata", _content_json()),
            files_reviewed=Func(
                KeyTransform("pr_files", _content_json()), function="jsonb_array_length", output_field=IntegerField()
            ),
        ).values("report_id", "meta", "files_reviewed")

    def _ingest(row: dict[str, Any], *, head_matched: bool) -> None:
        report_id = str(row["report_id"])
        raw_meta = row["meta"]
        try:
            # Depending on the driver the jsonb expression may land as a decoded dict or a string.
            meta = (
                PRMetadata.model_validate_json(raw_meta)
                if isinstance(raw_meta, str)
                else PRMetadata.model_validate(raw_meta)
                if raw_meta
                else None
            )
        except ValidationError as e:
            logger.warning("Skipping unparseable pr_snapshot metadata for report %s: %s", report_id, e)
            meta = None
        stats[report_id] = SnapshotStats(meta=meta, files_reviewed=row["files_reviewed"], head_matched=head_matched)

    head_q = _turn_scope_q(heads)
    if head_q is not None:
        for row in _annotated(snapshots.filter(head_q).order_by("created_at", "id")):
            _ingest(row, head_matched=True)  # oldest-first, so the turn's latest snapshot wins
    missing = [report_id for report_id in heads if report_id not in stats]
    if missing:
        # No snapshot at the reviewed head (degraded fetch, or fetch not run yet): newest one wins.
        fallback = (
            _annotated(snapshots.filter(report_id__in=missing))
            .order_by("report_id", "-created_at", "-id")
            .distinct("report_id")
        )
        for row in fallback:
            _ingest(row, head_matched=False)
    return stats


def turn_stats(team_id: int, heads: dict[str, str | None]) -> dict[str, TurnStats]:
    """Chunk/perspective shape of each report's turn at `heads[report_id]`, extracted DB-side."""
    stats = {report_id: TurnStats() for report_id in heads}
    head_q = _turn_scope_q(heads)
    if head_q is None:
        return stats

    chunk_rows = (
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(head_q, type=ReviewReportArtefact.ArtefactType.CHUNK_SET)
        .annotate(
            chunk_count=Func(
                KeyTransform("chunks", _content_json()), function="jsonb_array_length", output_field=IntegerField()
            ),
        )
        .order_by("created_at", "id")
        .values("report_id", "chunk_count")
    )
    for row in chunk_rows:  # oldest-first, so the turn's latest chunking wins
        stats[str(row["report_id"])].chunk_count = row["chunk_count"]

    result_rows = (
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(head_q, type=ReviewReportArtefact.ArtefactType.PERSPECTIVE_RESULT)
        .annotate(
            pass_number=Cast(KeyTextTransform("pass_number", _content_json()), IntegerField()),
            chunk_id=Cast(KeyTextTransform("chunk_id", _content_json()), IntegerField()),
            issue_count=Func(
                KeyTransform("issues", KeyTransform("review", _content_json())),
                function="jsonb_array_length",
                output_field=IntegerField(),
            ),
        )
        .order_by("created_at", "id")
        .values("report_id", "pass_number", "chunk_id", "issue_count")
    )
    # Selection artefacts are small (names + one-line reasons), so full content comes across the wire.
    selection_rows = (
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(head_q, type=ReviewReportArtefact.ArtefactType.PERSPECTIVE_SELECTION)
        .order_by("created_at", "id")
        .values("report_id", "content")
    )
    for selection_row in selection_rows:  # oldest-first, so the turn's latest selection wins
        report_id = str(selection_row["report_id"])
        try:
            artefact = PerspectiveSelectionArtefact.model_validate_json(selection_row["content"])
        except ValidationError as e:
            logger.warning("Skipping unparseable perspective_selection for report %s: %s", report_id, e)
            continue
        stats[report_id].selection_roster = artefact.roster
        stats[report_id].selection_chunks = artefact.selection.chunks

    # Latest-wins per (pass, chunk) within the turn, mirroring how the pipeline resumes them.
    issues_by_unit: dict[str, dict[tuple[int, int], int]] = {report_id: {} for report_id in stats}
    for row in result_rows:
        issues_by_unit[str(row["report_id"])][(row["pass_number"], row["chunk_id"])] = row["issue_count"]
    for report_id, units in issues_by_unit.items():
        wave_units = {unit: count for unit, count in units.items() if unit[0] != BLIND_SPOT_PASS_NUMBER}
        blind_units = {unit: count for unit, count in units.items() if unit[0] == BLIND_SPOT_PASS_NUMBER}
        if units:
            stats[report_id].perspective_reads = len(units)
        if wave_units:
            stats[report_id].perspective_count = len({pass_number for pass_number, _ in wave_units})
            stats[report_id].perspective_issue_count = sum(wave_units.values())
        if blind_units:
            stats[report_id].blind_spot_issue_count = sum(blind_units.values())
    return stats


def _expected_reads(team_id: int, report: ReviewReport, turn: TurnStats) -> int | None:
    """How many (pass, chunk) reviews this turn should produce.

    Once the selector's plan is persisted, the answer is exact: its planned wave units plus one
    blind-spot unit per chunk. Until then (or when the turn runs without a selection), estimate the
    dense product — chunks × (enabled perspectives + blind spot) — which may briefly overshoot on a
    pruned run before the selection artefact lands.
    """
    if report.acting_user_id is None:
        return None
    chunk_count = turn.chunk_count or 0
    if turn.selection_chunks is not None:
        planned = sum(len(chunk.perspectives) for chunk in turn.selection_chunks)
        return planned + chunk_count
    enabled = (
        ReviewSkillConfig.objects.for_team(team_id)
        .filter(user_id=report.acting_user_id, enabled=True, skill_name__startswith=REVIEW_HOG_PERSPECTIVE_PREFIX)
        .count()
    )
    # No configs yet means the run will seed and use the canonical set.
    perspectives = enabled or len(CANONICAL_PERSPECTIVE_SKILL_NAMES)
    return chunk_count * (perspectives + 1)


def progress_payload(
    team_id: int,
    report: ReviewReport,
    snapshot: SnapshotStats,
    turn: TurnStats,
    current_pairs: list[tuple[ReviewIssueFinding, ValidationVerdict | None]],
) -> dict[str, Any]:
    """Stage + counters for the in-flight turn, inferred from which working state exists at the head.

    Covers the full pipeline: fetching → chunking → selecting → reviewing → deduplicating →
    validating → finalizing (body build + publish, the moments before the turn completes).
    """
    if current_pairs:
        judged = sum(1 for _, verdict in current_pairs if verdict is not None)
        if judged >= len(current_pairs):
            return {"review_stage": "finalizing", "done": judged, "total": len(current_pairs)}
        return {"review_stage": "validating", "done": judged, "total": len(current_pairs)}
    if turn.chunk_count is not None:
        done = turn.perspective_reads or 0
        # The selector runs between chunking and the fan-out; its persisted plan is the stage marker.
        # A selection-less run (fallback) skips straight to "reviewing" once its first read lands.
        if done == 0 and turn.selection_chunks is None:
            return {"review_stage": "selecting", "done": None, "total": None}
        expected = _expected_reads(team_id, report, turn)
        if expected is not None and done >= expected:
            return {"review_stage": "deduplicating", "done": done, "total": expected}
        return {"review_stage": "reviewing", "done": done, "total": max(expected, done) if expected else None}
    if snapshot.head_matched:
        return {"review_stage": "chunking", "done": None, "total": None}
    return {"review_stage": "fetching", "done": None, "total": None}
