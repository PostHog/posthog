import uuid
import logging
import operator
from dataclasses import dataclass
from datetime import timedelta
from functools import reduce
from typing import Any, get_args

from django.db.models import Func, IntegerField, JSONField, Max, Q, QuerySet
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast
from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse, extend_schema
from pydantic import ValidationError
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.scoping.manager import resolve_effective_team_id

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact, ReviewSkillConfig
from products.review_hog.backend.reviewer.artefact_content import (
    PerspectiveSelectionArtefact,
    ReviewIssueCategory,
    ReviewIssueFinding,
    ValidationVerdict,
)
from products.review_hog.backend.reviewer.constants import BLIND_SPOT_PASS_NUMBER, effective_priority
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.review_hog.backend.reviewer.models.perspective_selection import ChunkPerspectiveSelection
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.persistence import load_chunk_set, load_findings_bundle, load_turn_findings
from products.review_hog.backend.reviewer.skill_loader import (
    CANONICAL_PERSPECTIVE_SKILL_NAMES,
    REVIEW_HOG_PERSPECTIVE_PREFIX,
)

logger = logging.getLogger(__name__)

RECENT_REVIEWS_LIMIT = 5

# Effectiveness stats aggregate deeper than the list — enough history for survival rates to mean something.
PERSPECTIVE_STATS_REPORT_LIMIT = 50

# An ACTIVE report only counts as "in progress" while its run is visibly moving (artefacts stream in
# throughout a run); past this an abandoned/crashed run stops rendering as a live row.
IN_PROGRESS_STALE_AFTER = timedelta(minutes=30)

_PRIORITY_CHOICES = [priority.value for priority in IssuePriority]
# Display order for the detail view: most urgent first.
_PRIORITY_DISPLAY_RANK = {IssuePriority.MUST_FIX: 0, IssuePriority.SHOULD_FIX: 1, IssuePriority.CONSIDER: 2}

_REVIEW_STAGES = ["fetching", "chunking", "selecting", "reviewing", "deduplicating", "validating", "finalizing"]


class ReviewProgressSerializer(serializers.Serializer):
    review_stage = serializers.ChoiceField(
        choices=_REVIEW_STAGES,
        help_text="How far the in-flight review turn has come: fetching the diff, chunking, picking "
        "each chunk's perspectives, reviewing chunks, merging overlapping findings, validating them, "
        "or finalizing (building and publishing the review).",
    )
    done = serializers.IntegerField(
        allow_null=True, help_text="Work units finished within the stage; null when the stage has no counter."
    )
    total = serializers.IntegerField(
        allow_null=True, help_text="Work units the stage expects in total; null when unknown."
    )


class ReviewSelectionChunkSerializer(serializers.Serializer):
    chunk_id = serializers.IntegerField(help_text="The chunk this row describes, as numbered by the chunker.")
    chunk_type = serializers.CharField(
        allow_null=True,
        help_text="The chunker's category for the chunk; null on the deterministic single-chunk path.",
    )
    files = serializers.ListField(
        child=serializers.CharField(), help_text="The chunk's files, from the turn's chunk set."
    )
    perspectives = serializers.ListField(
        child=serializers.CharField(), help_text="Perspectives the selector ran on this chunk, in pass order."
    )
    skipped = serializers.ListField(
        child=serializers.CharField(),
        help_text="Roster perspectives the selector skipped on this chunk, in pass order.",
    )
    reason = serializers.CharField(
        allow_blank=True, help_text="The selector's one-line reasoning for this chunk's picks."
    )


class ReviewPerspectiveSelectionSerializer(serializers.Serializer):
    roster = serializers.ListField(
        child=serializers.CharField(),
        help_text="Every enabled perspective the selector chose from, in pass order.",
    )
    chunks = ReviewSelectionChunkSerializer(many=True, help_text="Per-chunk picks with reasons, in chunk order.")


class ReviewRecentReviewSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The review report's id, for fetching the review's detail.")
    repository = serializers.CharField(help_text="The reviewed repository, as `owner/repo`.")
    pr_number = serializers.IntegerField(
        allow_null=True, help_text="The reviewed pull request's number; null for a branch target with no PR yet."
    )
    pr_title = serializers.CharField(
        allow_null=True, help_text="The pull request's title, from the latest reviewed snapshot; null if unknown."
    )
    pr_author = serializers.CharField(
        allow_null=True, help_text="The pull request author's GitHub login; null if unknown."
    )
    additions = serializers.IntegerField(allow_null=True, help_text="Lines added by the PR; null if unknown.")
    deletions = serializers.IntegerField(allow_null=True, help_text="Lines deleted by the PR; null if unknown.")
    changed_files = serializers.IntegerField(allow_null=True, help_text="Files the PR changes; null if unknown.")
    head_branch = serializers.CharField(help_text="The pull request's head branch.")
    github_url = serializers.CharField(
        help_text="Where to see the review on GitHub: the pull request when its URL is known, "
        "otherwise the head branch."
    )
    run_count = serializers.IntegerField(help_text="How many review turns have completed on this report.")
    last_run_at = serializers.DateTimeField(
        allow_null=True, help_text="When the latest review turn completed; null while the first is in flight."
    )
    published = serializers.BooleanField(help_text="Whether a review has been published back to GitHub.")
    in_progress = serializers.BooleanField(
        help_text="Whether a review turn is running on this report right now (activity within the last 30 minutes)."
    )
    progress = ReviewProgressSerializer(
        allow_null=True, help_text="The in-flight turn's stage and counters; null unless `in_progress`."
    )
    must_fix_count = serializers.IntegerField(
        help_text="The latest turn's valid findings at must_fix effective priority."
    )
    should_fix_count = serializers.IntegerField(
        help_text="The latest turn's valid findings at should_fix effective priority."
    )
    consider_count = serializers.IntegerField(
        help_text="The latest turn's valid findings at consider effective priority."
    )
    candidate_count = serializers.IntegerField(
        help_text="All findings the latest turn raised after dedupe, before validation."
    )
    dismissed_count = serializers.IntegerField(
        help_text="The latest turn's findings the validator dismissed as not worth publishing."
    )
    files_reviewed = serializers.IntegerField(
        allow_null=True,
        help_text="Meaningful files the latest turn actually read, after skipping generated/lock/snapshot files; "
        "null if unknown.",
    )
    chunk_count = serializers.IntegerField(
        allow_null=True, help_text="Reviewable chunks the latest turn split the PR into; null if unknown."
    )
    perspective_count = serializers.IntegerField(
        allow_null=True, help_text="Review perspectives that read each chunk in the latest turn; null if unknown."
    )
    perspective_issue_count = serializers.IntegerField(
        allow_null=True,
        help_text="Raw issues the perspectives raised in the latest turn, before dedupe; null if unknown.",
    )
    blind_spot_issue_count = serializers.IntegerField(
        allow_null=True,
        help_text="Raw issues the blind-spot sweep added in the latest turn, before dedupe; null if unknown.",
    )


class ReviewFindingLineRangeSerializer(serializers.Serializer):
    start = serializers.IntegerField(help_text="First affected line.")
    end = serializers.IntegerField(allow_null=True, help_text="Last affected line; null for a single line.")


class ReviewFindingSerializer(serializers.Serializer):
    title = serializers.CharField(help_text="One-line summary of the finding.")
    file = serializers.CharField(help_text="Repository-relative path of the affected file.")
    lines = ReviewFindingLineRangeSerializer(many=True, help_text="Affected line ranges within the file.")
    body = serializers.CharField(help_text="Description of the problem.")
    suggestion = serializers.CharField(help_text="The specific fix or improvement the reviewer proposes.")
    effective_priority = serializers.ChoiceField(
        choices=_PRIORITY_CHOICES,
        help_text="The priority that gates publishing: the validator's override when set, else the reviewer's.",
    )
    reviewer_priority = serializers.ChoiceField(
        choices=_PRIORITY_CHOICES, help_text="The reviewer's original priority, before any validator override."
    )
    source_perspective = serializers.CharField(
        allow_null=True, help_text="The review skill that produced the finding (perspective or blind-spot sweep)."
    )
    validator_category = serializers.ChoiceField(
        choices=list(get_args(ReviewIssueCategory)),
        allow_null=True,
        help_text="The validator's category for the finding; null when it didn't set one.",
    )
    validator_note = serializers.CharField(
        help_text="The validator's argumentation for keeping or dismissing the finding."
    )


class ReviewDetailSerializer(ReviewRecentReviewSerializer):
    head_sha = serializers.CharField(
        allow_null=True,
        help_text="The PR head commit the latest turn reviewed — anchors GitHub links to the exact code.",
    )
    perspective_selection = ReviewPerspectiveSelectionSerializer(
        allow_null=True,
        help_text="The selector's per-chunk perspective plan for the latest turn; null when the turn ran "
        "without a selection (selector unavailable, failed, or the run predates it).",
    )
    report_markdown = serializers.CharField(
        allow_blank=True, help_text="The rendered review body published to GitHub, as markdown."
    )
    findings = ReviewFindingSerializer(many=True, help_text="The latest turn's validated findings, most urgent first.")
    dismissed_findings = ReviewFindingSerializer(
        many=True, help_text="The latest turn's findings the validator dismissed, with its reasoning."
    )


class ReviewPerspectiveStatItemSerializer(serializers.Serializer):
    skill_name = serializers.CharField(
        help_text="The review skill (perspective or blind-spot sweep) that raised the findings."
    )
    raised = serializers.IntegerField(
        help_text="Findings this skill raised across the aggregated reviews (post-dedupe candidates)."
    )
    kept = serializers.IntegerField(help_text="Of those, findings the validator kept.")
    dismissed = serializers.IntegerField(help_text="Of those, findings the validator dismissed.")


class ReviewPerspectiveStatsSerializer(serializers.Serializer):
    report_count = serializers.IntegerField(help_text="How many recent completed reviews the stats aggregate over.")
    perspectives = ReviewPerspectiveStatItemSerializer(
        many=True, help_text="Per-skill effectiveness across those reviews, most kept findings first."
    )


@dataclass
class _SnapshotStats:
    """PR facts from the report's latest `pr_snapshot` artefact (metadata only, never `pr_files`)."""

    meta: PRMetadata | None = None
    files_reviewed: int | None = None
    # Whether a snapshot exists for the report's CURRENT head (vs. a stale-turn fallback) — the
    # in-flight stage detection needs "has this turn fetched yet", not "was anything ever fetched".
    head_matched: bool = False


@dataclass
class _TurnStats:
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


def _snapshot_stats(team_id: int, heads: dict[str, str | None]) -> dict[str, _SnapshotStats]:
    """The latest snapshot's PR metadata per report, extracted DB-side, scoped to `heads`.

    `heads` maps report id → the head to describe: the completed turn's head for row/detail payloads
    (so an in-flight turn's snapshot never splices onto the previous turn's findings), the live
    watermark for in-flight progress. `pr_snapshot` content embeds the PR's full files payload
    (easily hundreds of KB), so the jsonb extraction pulls only `pr_metadata` and the `pr_files`
    length across the wire, and the `head_sha` column keeps the jsonb work off prior turns' rows.
    Prefers the snapshot matching the requested head, falling back to the newest one.
    """
    stats: dict[str, _SnapshotStats] = {}
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
        stats[report_id] = _SnapshotStats(meta=meta, files_reviewed=row["files_reviewed"], head_matched=head_matched)

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


def _turn_stats(team_id: int, heads: dict[str, str | None]) -> dict[str, _TurnStats]:
    """Chunk/perspective shape of each report's turn at `heads[report_id]`, extracted DB-side."""
    stats = {report_id: _TurnStats() for report_id in heads}
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


def _in_progress_report_ids(team_id: int, reports: list[ReviewReport]) -> set[str]:
    """Which ACTIVE reports are visibly running: artefact or report activity within the staleness window.

    Artefacts stream in throughout a run (snapshot, chunk set, per-chunk results, verdicts), so the
    newest artefact is the liveness signal; a crashed run goes quiet and ages out instead of showing
    a stuck spinner forever.
    """
    candidates = [report for report in reports if report.status == ReviewReport.Status.ACTIVE]
    if not candidates:
        return set()
    latest_artefact = dict(
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(report_id__in=[report.id for report in candidates])
        .values_list("report_id")
        .annotate(latest=Max("created_at"))
        .values_list("report_id", "latest")
    )
    cutoff = timezone.now() - IN_PROGRESS_STALE_AFTER
    fresh: set[str] = set()
    for report in candidates:
        last_activity = max(filter(None, [report.updated_at, latest_artefact.get(report.id)]), default=None)
        if last_activity is not None and last_activity >= cutoff:
            fresh.add(str(report.id))
    return fresh


def _expected_reads(team_id: int, report: ReviewReport, turn: _TurnStats) -> int | None:
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


def _progress_payload(
    team_id: int,
    report: ReviewReport,
    snapshot: _SnapshotStats,
    turn: _TurnStats,
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


def _finding_payload(finding: ReviewIssueFinding, verdict: ValidationVerdict) -> dict[str, Any]:
    return {
        "title": finding.title,
        "file": finding.file,
        "lines": [{"start": line_range.start, "end": line_range.end} for line_range in finding.lines],
        "body": finding.body,
        "suggestion": finding.suggestion,
        "effective_priority": effective_priority(finding.priority, verdict.adjusted_priority).value,
        "reviewer_priority": finding.priority.value,
        "source_perspective": finding.source_perspective,
        "validator_category": verdict.category,
        "validator_note": verdict.argumentation,
    }


def _selection_payload(turn: _TurnStats, chunks: ChunksList | None) -> dict[str, Any] | None:
    """The selector's per-chunk plan for the detail drawer, joined with the chunk set's metadata."""
    if turn.selection_roster is None or turn.selection_chunks is None:
        return None
    meta_by_id = {chunk.chunk_id: chunk for chunk in chunks.chunks} if chunks is not None else {}
    rows: list[dict[str, Any]] = []
    for entry in turn.selection_chunks:
        meta = meta_by_id.get(entry.chunk_id)
        selected = set(entry.perspectives)
        rows.append(
            {
                "chunk_id": entry.chunk_id,
                "chunk_type": meta.chunk_type if meta else None,
                "files": [f.filename for f in meta.files] if meta else [],
                "perspectives": [name for name in turn.selection_roster if name in selected],
                "skipped": [name for name in turn.selection_roster if name not in selected],
                "reason": entry.reason,
            }
        )
    return {"roster": turn.selection_roster, "chunks": rows}


def _review_payload(
    report: ReviewReport,
    snapshot: _SnapshotStats,
    turn: _TurnStats,
    pairs: list[tuple[ReviewIssueFinding, ValidationVerdict | None]],
    progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The list-row payload for one report; the detail endpoint layers findings on top."""
    counts = dict.fromkeys(IssuePriority, 0)
    dismissed = 0
    for finding, verdict in pairs:
        if verdict is None:
            continue
        if verdict.is_valid:
            counts[effective_priority(finding.priority, verdict.adjusted_priority)] += 1
        else:
            dismissed += 1
    meta = snapshot.meta
    return {
        "id": report.id,
        "repository": report.repository,
        "pr_number": report.pr_number,
        "pr_title": meta.title if meta else None,
        "pr_author": meta.author if meta else None,
        "additions": meta.additions if meta else None,
        "deletions": meta.deletions if meta else None,
        "changed_files": meta.changed_files if meta else None,
        "head_branch": report.head_branch,
        "github_url": report.pr_url or f"https://github.com/{report.repository}/tree/{report.head_branch}",
        "run_count": report.run_count,
        "last_run_at": report.last_run_at,
        "published": report.published_head_sha is not None,
        "in_progress": progress is not None,
        "progress": progress,
        "must_fix_count": counts[IssuePriority.MUST_FIX],
        "should_fix_count": counts[IssuePriority.SHOULD_FIX],
        "consider_count": counts[IssuePriority.CONSIDER],
        "candidate_count": len(pairs),
        "dismissed_count": dismissed,
        "files_reviewed": snapshot.files_reviewed,
        "chunk_count": turn.chunk_count,
        "perspective_count": turn.perspective_count,
        "perspective_issue_count": turn.perspective_issue_count,
        "blind_spot_issue_count": turn.blind_spot_issue_count,
    }


class ReviewRecentReviewsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The requesting user's most recent ReviewHog reviews (reports where they are the acting user).

    Read-only meta for the Code review tab's "recent reviews" block: what was reviewed, how many
    valid findings at each effective priority, the reviewed PR's facts, and the pipeline shape of
    the latest turn. `retrieve` adds the findings themselves (valid + dismissed) and the published
    review body.
    """

    scope_object = "INTERNAL"
    # Unscoped only to satisfy the router/introspection; every real query goes through `for_team`.
    queryset = ReviewReport.objects.unscoped()
    serializer_class = ReviewRecentReviewSerializer
    pagination_class = None

    def _reports(self, request: Request) -> tuple[int, QuerySet[ReviewReport]]:
        team_id = resolve_effective_team_id(self.team_id)
        return team_id, ReviewReport.objects.for_team(team_id, canonical=True).filter(acting_user_id=request.user.id)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=ReviewRecentReviewSerializer(many=True),
                description="The user's reviews: in-progress runs first, then completed newest first.",
            ),
        },
        summary="List the user's recent reviews",
        description="The requesting user's ReviewHog reviews on this project: actively running reviews "
        "first (with the in-flight turn's stage), then the most recent completed ones (at most 5 rows).",
    )
    def list(self, request: Request, **kwargs) -> Response:
        team_id, queryset = self._reports(request)
        completed = list(queryset.filter(last_run_at__isnull=False).order_by("-last_run_at")[:RECENT_REVIEWS_LIMIT])
        # First-turn runs have no completed turn yet; they only surface while visibly running.
        running_first_turn = list(
            queryset.filter(status=ReviewReport.Status.ACTIVE, last_run_at__isnull=True).order_by("-created_at")[
                :RECENT_REVIEWS_LIMIT
            ]
        )
        # A re-review keeps the previous turn's last_run_at until it finalizes, so a dormant report's
        # in-flight turn can rank below the completed slice — fetch running re-reviews explicitly or
        # an actively reviewed PR vanishes from the list mid-run.
        running_re_review = list(
            queryset.filter(status=ReviewReport.Status.ACTIVE, last_run_at__isnull=False).order_by("-updated_at")[
                :RECENT_REVIEWS_LIMIT
            ]
        )
        in_progress_ids = _in_progress_report_ids(team_id, running_first_turn + running_re_review + completed)
        # Visibly running first (first turns, then re-reviews), then recent completed — deduped so a
        # re-review that also ranks in the completed slice keeps its front position.
        seen: set[str] = set()
        reports: list[ReviewReport] = []
        for report in [
            *[report for report in running_first_turn if str(report.id) in in_progress_ids],
            *[report for report in running_re_review if str(report.id) in in_progress_ids],
            *completed,
        ]:
            if str(report.id) not in seen:
                seen.add(str(report.id))
                reports.append(report)
        reports = reports[:RECENT_REVIEWS_LIMIT]

        # Row stats anchor to each report's COMPLETED turn (matching the findings' run_count); the
        # in-flight progress payload alone reads the live head. Pre-column rows fall back to the live
        # watermark, which is also correct for never-finalized first turns.
        snapshots = _snapshot_stats(team_id, {str(r.id): r.completed_head_sha or r.head_sha for r in reports})
        turns = _turn_stats(team_id, {str(r.id): r.completed_head_sha or r.head_sha for r in reports})
        in_flight = [report for report in reports if str(report.id) in in_progress_ids]
        live_heads = {str(report.id): report.head_sha for report in in_flight}
        live_snapshots = _snapshot_stats(team_id, live_heads) if in_flight else {}
        live_turns = _turn_stats(team_id, live_heads) if in_flight else {}
        bundle = load_findings_bundle(team_id=team_id, report_ids=[str(report.id) for report in reports])
        items = []
        for report in reports:
            report_id = str(report.id)
            snapshot = snapshots.get(report_id, _SnapshotStats())
            turn = turns.get(report_id, _TurnStats())
            pairs = bundle.turn(report_id, report.run_count)
            progress = None
            if report_id in in_progress_ids:
                # The in-flight turn's findings live one run_index ahead of the completed watermark.
                current_pairs = bundle.turn(report_id, report.run_count + 1)
                progress = _progress_payload(
                    team_id,
                    report,
                    live_snapshots.get(report_id, _SnapshotStats()),
                    live_turns.get(report_id, _TurnStats()),
                    current_pairs,
                )
            items.append(_review_payload(report, snapshot, turn, pairs, progress))
        return Response(ReviewRecentReviewSerializer(items, many=True).data)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=ReviewPerspectiveStatsSerializer,
                description="Per-skill effectiveness across the user's recent completed reviews.",
            ),
        },
        summary="Perspective effectiveness stats",
        description="How many findings each review skill (perspective or blind-spot sweep) raised across the "
        "requesting user's recent completed reviews, and how many of those the validator kept vs dismissed.",
    )
    @action(methods=["GET"], detail=False)
    def perspective_stats(self, request: Request, **kwargs) -> Response:
        team_id, queryset = self._reports(request)
        reports = list(
            queryset.filter(last_run_at__isnull=False).order_by("-last_run_at")[:PERSPECTIVE_STATS_REPORT_LIMIT]
        )
        stats: dict[str, dict[str, int]] = {}
        bundle = load_findings_bundle(team_id=team_id, report_ids=[str(report.id) for report in reports])
        for report in reports:
            pairs = bundle.turn(str(report.id), report.run_count)
            for finding, verdict in pairs:
                entry = stats.setdefault(
                    finding.source_perspective or "unknown", {"raised": 0, "kept": 0, "dismissed": 0}
                )
                entry["raised"] += 1
                if verdict is not None:
                    entry["kept" if verdict.is_valid else "dismissed"] += 1
        items: list[dict[str, Any]] = [{"skill_name": skill_name, **counts} for skill_name, counts in stats.items()]
        items.sort(key=lambda item: (-item["kept"], -item["raised"], item["skill_name"]))
        payload = {"report_count": len(reports), "perspectives": items}
        return Response(ReviewPerspectiveStatsSerializer(payload).data)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=ReviewDetailSerializer,
                description="The review's detail: findings (valid and dismissed) and the published body.",
            ),
            404: OpenApiResponse(description="No such review of the requesting user's pull requests."),
        },
        summary="Retrieve one review's detail",
        description="One completed ReviewHog review of the requesting user's pull requests, with the latest "
        "turn's validated findings, the findings the validator dismissed (and why), and the review body "
        "published to GitHub.",
    )
    def retrieve(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        try:
            report_uuid = uuid.UUID(str(pk))
        except ValueError:
            raise NotFound("Review not found.")
        team_id, queryset = self._reports(request)
        # Detail describes a completed turn — a first run still in flight has nothing to show yet.
        report = queryset.filter(id=report_uuid, last_run_at__isnull=False).first()
        if report is None:
            raise NotFound("Review not found.")

        report_id = str(report.id)
        # Everything the detail returns — stats, chunk set, link-anchoring head — describes the same
        # completed turn the findings come from, never an in-flight turn's watermark.
        completed_head = report.completed_head_sha or report.head_sha
        snapshots = _snapshot_stats(team_id, {report_id: completed_head})
        turns = _turn_stats(team_id, {report_id: completed_head})
        pairs = load_turn_findings(team_id=team_id, report_id=report_id, run_index=report.run_count)
        chunk_set = (
            load_chunk_set(team_id=team_id, report_id=report_id, head_sha=completed_head) if completed_head else None
        )

        def sort_key(payload: dict[str, Any]) -> tuple[int, str]:
            return (_PRIORITY_DISPLAY_RANK[IssuePriority(payload["effective_priority"])], payload["file"])

        valid = [_finding_payload(f, v) for f, v in pairs if v is not None and v.is_valid]
        dismissed = [_finding_payload(f, v) for f, v in pairs if v is not None and not v.is_valid]
        payload = {
            **_review_payload(
                report, snapshots.get(report_id, _SnapshotStats()), turns.get(report_id, _TurnStats()), pairs
            ),
            "head_sha": completed_head,
            "report_markdown": report.report_markdown,
            "findings": sorted(valid, key=sort_key),
            "dismissed_findings": sorted(dismissed, key=sort_key),
            "perspective_selection": _selection_payload(turns.get(report_id, _TurnStats()), chunk_set),
        }
        return Response(ReviewDetailSerializer(payload).data)
