import uuid
import logging
from dataclasses import dataclass
from typing import Any, get_args

from django.db.models import Func, IntegerField, JSONField, QuerySet
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from pydantic import ValidationError
from rest_framework import serializers, viewsets
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
from products.review_hog.backend.reviewer.constants import BLIND_SPOT_PASS_NUMBER, effective_priority
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.review_hog.backend.reviewer.persistence import load_turn_findings

logger = logging.getLogger(__name__)

RECENT_REVIEWS_LIMIT = 10

_PRIORITY_CHOICES = [priority.value for priority in IssuePriority]
# Display order for the detail view: most urgent first.
_PRIORITY_DISPLAY_RANK = {IssuePriority.MUST_FIX: 0, IssuePriority.SHOULD_FIX: 1, IssuePriority.CONSIDER: 2}


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
    last_run_at = serializers.DateTimeField(help_text="When the latest review turn completed.")
    published = serializers.BooleanField(help_text="Whether a review has been published back to GitHub.")
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
    report_markdown = serializers.CharField(
        allow_blank=True, help_text="The rendered review body published to GitHub, as markdown."
    )
    findings = ReviewFindingSerializer(many=True, help_text="The latest turn's validated findings, most urgent first.")
    dismissed_findings = ReviewFindingSerializer(
        many=True, help_text="The latest turn's findings the validator dismissed, with its reasoning."
    )


@dataclass
class _SnapshotStats:
    """PR facts from the report's latest `pr_snapshot` artefact (metadata only, never `pr_files`)."""

    meta: PRMetadata | None = None
    files_reviewed: int | None = None


@dataclass
class _TurnStats:
    """Pipeline shape of the latest turn, from `chunk_set` / `perspective_result` working state."""

    chunk_count: int | None = None
    perspective_count: int | None = None
    perspective_issue_count: int | None = None
    blind_spot_issue_count: int | None = None


def _content_json() -> Cast:
    return Cast("content", JSONField())


def _snapshot_stats(team_id: int, reports: list[ReviewReport]) -> dict[str, _SnapshotStats]:
    """The latest snapshot's PR metadata per report, extracted DB-side.

    `pr_snapshot` content embeds the PR's full files payload (easily hundreds of KB), so the
    jsonb extraction pulls only `pr_metadata` and the `pr_files` length across the wire. Prefers
    the snapshot matching the report's reviewed head, falling back to the newest one.
    """
    stats: dict[str, _SnapshotStats] = {}
    head_by_report = {str(report.id): report.head_sha for report in reports}
    rows = (
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(report_id__in=list(head_by_report), type=ReviewReportArtefact.ArtefactType.PR_SNAPSHOT)
        .annotate(
            meta=KeyTransform("pr_metadata", _content_json()),
            snapshot_head_sha=KeyTextTransform("head_sha", _content_json()),
            files_reviewed=Func(
                KeyTransform("pr_files", _content_json()), function="jsonb_array_length", output_field=IntegerField()
            ),
        )
        .order_by("created_at", "id")
        .values("report_id", "meta", "snapshot_head_sha", "files_reviewed")
    )
    matched_head: set[str] = set()
    for row in rows:
        report_id = str(row["report_id"])
        # Rows come oldest-first: a later row always wins, but a head-matching row is never
        # displaced by a newer non-matching one (e.g. a fetch for a head that never finished).
        is_match = row["snapshot_head_sha"] == head_by_report[report_id]
        if not is_match and report_id in matched_head:
            continue
        if is_match:
            matched_head.add(report_id)
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
        stats[report_id] = _SnapshotStats(meta=meta, files_reviewed=row["files_reviewed"])
    return stats


def _turn_stats(team_id: int, reports: list[ReviewReport]) -> dict[str, _TurnStats]:
    """Chunk/perspective shape of each report's latest turn, extracted DB-side (counts only)."""
    stats = {str(report.id): _TurnStats() for report in reports}
    head_by_report = {str(report.id): report.head_sha for report in reports}

    chunk_rows = (
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(report_id__in=list(head_by_report), type=ReviewReportArtefact.ArtefactType.CHUNK_SET)
        .annotate(
            chunk_head_sha=KeyTextTransform("head_sha", _content_json()),
            chunk_count=Func(
                KeyTransform("chunks", _content_json()), function="jsonb_array_length", output_field=IntegerField()
            ),
        )
        .order_by("created_at", "id")
        .values("report_id", "chunk_head_sha", "chunk_count")
    )
    for row in chunk_rows:  # oldest-first, so the turn's latest chunking wins
        report_id = str(row["report_id"])
        if row["chunk_head_sha"] == head_by_report[report_id]:
            stats[report_id].chunk_count = row["chunk_count"]

    result_rows = (
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(report_id__in=list(head_by_report), type=ReviewReportArtefact.ArtefactType.PERSPECTIVE_RESULT)
        .annotate(
            result_head_sha=KeyTextTransform("head_sha", _content_json()),
            pass_number=Cast(KeyTextTransform("pass_number", _content_json()), IntegerField()),
            chunk_id=Cast(KeyTextTransform("chunk_id", _content_json()), IntegerField()),
            issue_count=Func(
                KeyTransform("issues", KeyTransform("review", _content_json())),
                function="jsonb_array_length",
                output_field=IntegerField(),
            ),
        )
        .order_by("created_at", "id")
        .values("report_id", "result_head_sha", "pass_number", "chunk_id", "issue_count")
    )
    # Latest-wins per (pass, chunk) within the turn, mirroring how the pipeline resumes them.
    issues_by_unit: dict[str, dict[tuple[int, int], int]] = {report_id: {} for report_id in head_by_report}
    for row in result_rows:
        report_id = str(row["report_id"])
        if row["result_head_sha"] == head_by_report[report_id]:
            issues_by_unit[report_id][(row["pass_number"], row["chunk_id"])] = row["issue_count"]
    for report_id, units in issues_by_unit.items():
        wave_units = {unit: count for unit, count in units.items() if unit[0] != BLIND_SPOT_PASS_NUMBER}
        blind_units = {unit: count for unit, count in units.items() if unit[0] == BLIND_SPOT_PASS_NUMBER}
        if wave_units:
            stats[report_id].perspective_count = len({pass_number for pass_number, _ in wave_units})
            stats[report_id].perspective_issue_count = sum(wave_units.values())
        if blind_units:
            stats[report_id].blind_spot_issue_count = sum(blind_units.values())
    return stats


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


def _review_payload(
    report: ReviewReport,
    snapshot: _SnapshotStats,
    turn: _TurnStats,
    pairs: list[tuple[ReviewIssueFinding, ValidationVerdict | None]],
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
        return team_id, ReviewReport.objects.for_team(team_id, canonical=True).filter(
            acting_user_id=request.user.id, last_run_at__isnull=False
        )

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=ReviewRecentReviewSerializer(many=True),
                description="The user's recent completed reviews, newest first.",
            ),
        },
        summary="List the user's recent reviews",
        description="The most recent completed ReviewHog reviews of the requesting user's pull requests "
        "on this project, newest first (at most 10).",
    )
    def list(self, request: Request, **kwargs) -> Response:
        team_id, queryset = self._reports(request)
        reports = list(queryset.order_by("-last_run_at")[:RECENT_REVIEWS_LIMIT])
        snapshots = _snapshot_stats(team_id, reports)
        turns = _turn_stats(team_id, reports)
        items = []
        for report in reports:
            report_id = str(report.id)
            pairs = load_turn_findings(team_id=team_id, report_id=report_id, run_index=report.run_count)
            items.append(
                _review_payload(
                    report, snapshots.get(report_id, _SnapshotStats()), turns.get(report_id, _TurnStats()), pairs
                )
            )
        return Response(ReviewRecentReviewSerializer(items, many=True).data)

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
        report = queryset.filter(id=report_uuid).first()
        if report is None:
            raise NotFound("Review not found.")

        report_id = str(report.id)
        snapshots = _snapshot_stats(team_id, [report])
        turns = _turn_stats(team_id, [report])
        pairs = load_turn_findings(team_id=team_id, report_id=report_id, run_index=report.run_count)

        def sort_key(payload: dict[str, Any]) -> tuple[int, str]:
            return (_PRIORITY_DISPLAY_RANK[IssuePriority(payload["effective_priority"])], payload["file"])

        valid = [_finding_payload(f, v) for f, v in pairs if v is not None and v.is_valid]
        dismissed = [_finding_payload(f, v) for f, v in pairs if v is not None and not v.is_valid]
        payload = {
            **_review_payload(
                report, snapshots.get(report_id, _SnapshotStats()), turns.get(report_id, _TurnStats()), pairs
            ),
            "report_markdown": report.report_markdown,
            "findings": sorted(valid, key=sort_key),
            "dismissed_findings": sorted(dismissed, key=sort_key),
        }
        return Response(ReviewDetailSerializer(payload).data)
