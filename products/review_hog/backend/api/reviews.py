import uuid
import logging
from datetime import timedelta
from typing import Any, get_args

from django.db.models import Max, QuerySet
from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.scoping.manager import resolve_effective_team_id

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import (
    ReviewIssueCategory,
    ReviewIssueFinding,
    ValidationVerdict,
)
from products.review_hog.backend.reviewer.constants import effective_priority
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.persistence import load_chunk_set, load_findings_bundle, load_turn_findings
from products.review_hog.backend.reviewer.progress import (
    REVIEW_STAGES,
    SnapshotStats,
    TurnStats,
    progress_payload,
    snapshot_stats,
    turn_stats,
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

SCOPE_MINE = "mine"
SCOPE_EVERYONE = "everyone"


class ReviewsListParamsSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(
        choices=[SCOPE_MINE, SCOPE_EVERYONE],
        default=SCOPE_MINE,
        help_text="Whose reviews to list: `mine` for reviews of the requesting user's pull requests "
        "(the default), `everyone` for every review on this project.",
    )


class ReviewProgressSerializer(serializers.Serializer):
    review_stage = serializers.ChoiceField(
        choices=REVIEW_STAGES,
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


def _selection_payload(turn: TurnStats, chunks: ChunksList | None) -> dict[str, Any] | None:
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
    snapshot: SnapshotStats,
    turn: TurnStats,
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
    """Recent ReviewHog reviews on this project.

    Read-only meta for the Code review tab's "recent reviews" block: what was reviewed, how many
    valid findings at each effective priority, the reviewed PR's facts, and the pipeline shape of
    the latest turn. `list` covers the requesting user's reviews (reports where they are the acting
    user) by default, or the whole project's via `scope=everyone` — mirroring the inbox's
    "For you / Entire project" switch. `retrieve` adds the findings themselves (valid + dismissed)
    and the published review body; it is project-wide so any listed review can be opened.
    """

    scope_object = "INTERNAL"
    # Unscoped only to satisfy the router/introspection; every real query goes through `for_team`.
    queryset = ReviewReport.objects.unscoped()
    serializer_class = ReviewRecentReviewSerializer
    pagination_class = None

    def _reports(self, request: Request, scope: str = SCOPE_MINE) -> tuple[int, QuerySet[ReviewReport]]:
        team_id = resolve_effective_team_id(self.team_id)
        queryset = ReviewReport.objects.for_team(team_id, canonical=True)
        if scope == SCOPE_MINE:
            queryset = queryset.filter(acting_user_id=request.user.id)
        return team_id, queryset

    @extend_schema(
        parameters=[ReviewsListParamsSerializer],
        responses={
            200: OpenApiResponse(
                response=ReviewRecentReviewSerializer(many=True),
                description="The scoped reviews: in-progress runs first, then completed newest first.",
            ),
        },
        summary="List recent reviews",
        description="Recent ReviewHog reviews on this project: actively running reviews first (with the "
        "in-flight turn's stage), then the most recent completed ones (at most 5 rows). By default only "
        "the requesting user's reviews; `scope=everyone` lists every review on the project.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        params = ReviewsListParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        team_id, queryset = self._reports(request, scope=params.validated_data["scope"])
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
        snapshots = snapshot_stats(team_id, {str(r.id): r.completed_head_sha or r.head_sha for r in reports})
        turns = turn_stats(team_id, {str(r.id): r.completed_head_sha or r.head_sha for r in reports})
        in_flight = [report for report in reports if str(report.id) in in_progress_ids]
        live_heads = {str(report.id): report.head_sha for report in in_flight}
        live_snapshots = snapshot_stats(team_id, live_heads) if in_flight else {}
        live_turns = turn_stats(team_id, live_heads) if in_flight else {}
        bundle = load_findings_bundle(team_id=team_id, report_ids=[str(report.id) for report in reports])
        items = []
        for report in reports:
            report_id = str(report.id)
            snapshot = snapshots.get(report_id, SnapshotStats())
            turn = turns.get(report_id, TurnStats())
            pairs = bundle.turn(report_id, report.run_count)
            progress = None
            if report_id in in_progress_ids:
                # The in-flight turn's findings live one run_index ahead of the completed watermark.
                current_pairs = bundle.turn(report_id, report.run_count + 1)
                progress = progress_payload(
                    team_id,
                    report,
                    live_snapshots.get(report_id, SnapshotStats()),
                    live_turns.get(report_id, TurnStats()),
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
            404: OpenApiResponse(description="No such review on this project."),
        },
        summary="Retrieve one review's detail",
        description="One completed ReviewHog review on this project, with the latest turn's validated "
        "findings, the findings the validator dismissed (and why), and the review body published to "
        "GitHub. Project-wide, so reviews listed under `scope=everyone` can be opened too.",
    )
    def retrieve(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        try:
            report_uuid = uuid.UUID(str(pk))
        except ValueError:
            raise NotFound("Review not found.")
        # Project-wide on purpose: the detail must open for any review the everyone-scope list shows.
        team_id, queryset = self._reports(request, scope=SCOPE_EVERYONE)
        # Detail describes a completed turn — a first run still in flight has nothing to show yet.
        report = queryset.filter(id=report_uuid, last_run_at__isnull=False).first()
        if report is None:
            raise NotFound("Review not found.")

        report_id = str(report.id)
        # Everything the detail returns — stats, chunk set, link-anchoring head — describes the same
        # completed turn the findings come from, never an in-flight turn's watermark.
        completed_head = report.completed_head_sha or report.head_sha
        snapshots = snapshot_stats(team_id, {report_id: completed_head})
        turns = turn_stats(team_id, {report_id: completed_head})
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
                report, snapshots.get(report_id, SnapshotStats()), turns.get(report_id, TurnStats()), pairs
            ),
            "head_sha": completed_head,
            "report_markdown": report.report_markdown,
            "findings": sorted(valid, key=sort_key),
            "dismissed_findings": sorted(dismissed, key=sort_key),
            "perspective_selection": _selection_payload(turns.get(report_id, TurnStats()), chunk_set),
        }
        return Response(ReviewDetailSerializer(payload).data)
