import uuid
import logging
from typing import Any, cast, get_args

from django.db import models
from django.db.models import Max, Q, QuerySet
from django.utils import timezone

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.integration import github_rate_limited_response
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission, get_authenticator_scoped_team_ids

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.requested_reviews import (
    RUN_MODE_FLASH,
    RUN_MODE_RESOLVE_ONLY,
    RUN_MODE_REVIEW,
    RUN_MODE_REVIEW_ONLY,
    PRReviewRequestStatus,
    ResolveSkipReason,
    request_pr_review,
)
from products.review_hog.backend.review_request_rules import ReviewRequestRefusal
from products.review_hog.backend.reviewer.artefact_content import (
    ReviewIssueCategory,
    ReviewIssueFinding,
    ValidationVerdict,
)
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH, REVIEW_MODE_FULL, effective_priority
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.persistence import TurnFindingsBundle, load_chunk_set, load_findings_bundle
from products.review_hog.backend.reviewer.progress import (
    IN_PROGRESS_STALE_AFTER,
    RESOLUTION_COMPLETED,
    RESOLUTION_RESOLVING,
    RESOLUTION_STOPPED,
    REVIEW_STAGES,
    ResolutionRunState,
    ResolutionSummary,
    SnapshotStats,
    TurnMarker,
    TurnStats,
    latest_resolution_summaries,
    progress_payload,
    resolution_states,
    snapshot_stats,
    turn_markers,
    turn_stats,
)
from products.review_hog.backend.reviewer.review_state import completed_turn_review_mode
from products.review_hog.backend.reviewer.tools.github_meta import PRParser

logger = logging.getLogger(__name__)

DEFAULT_REVIEWS_LIMIT = 5
# Caps "Show more" growth — enrichment (jsonb stats + findings bundle) is per-row work.
MAX_REVIEWS_LIMIT = 100

# Effectiveness stats aggregate deeper than the list — enough history for survival rates to mean something.
PERSPECTIVE_STATS_REPORT_LIMIT = 50
OWN_DEEP_STATS_REVIEW_LIMIT = 10

_PRIORITY_CHOICES = [priority.value for priority in IssuePriority]
# Display order for the detail view: most urgent first.
_PRIORITY_DISPLAY_RANK = {IssuePriority.MUST_FIX: 0, IssuePriority.SHOULD_FIX: 1, IssuePriority.CONSIDER: 2}

SCOPE_MINE = "mine"
SCOPE_EVERYONE = "everyone"


class ReviewsListParamsSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(
        choices=[SCOPE_MINE, SCOPE_EVERYONE],
        default=SCOPE_MINE,
        help_text="Whose reviews to list: `mine` (the default) for reviews the requesting user ran "
        "plus reviews of pull requests they authored (matched via their linked GitHub login), "
        "`everyone` for every review on this project.",
    )
    limit = serializers.IntegerField(
        default=DEFAULT_REVIEWS_LIMIT,
        min_value=1,
        max_value=MAX_REVIEWS_LIMIT,
        help_text="Maximum rows to return. The list grows this instead of paging by offset — "
        "in-progress rows reorder the list between refreshes, so offset pages would shift under the reader.",
    )


class PerspectiveStatsScope(models.TextChoices):
    MINE = SCOPE_MINE, "Mine"
    EVERYONE = SCOPE_EVERYONE, "Everyone"
    OWN_DEEP = "own_deep", "Own Deep reviews"


class PerspectiveStatsParamsSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(
        choices=PerspectiveStatsScope.choices,
        default=PerspectiveStatsScope.MINE,
        help_text="Whose reviews to aggregate: `mine` (the default) for reviews the requesting user ran "
        "plus reviews of pull requests they authored (matched via their linked GitHub login), "
        "`everyone` for every review on this project, `own_deep` for the last "
        f"{OWN_DEEP_STATS_REVIEW_LIMIT} Deep reviews the requesting user started. The review skills "
        "in the settings use `own_deep`, because only the person who starts a Deep review picks its skills.",
    )


class ReviewProgressSerializer(serializers.Serializer):
    review_stage = serializers.ChoiceField(
        choices=REVIEW_STAGES,
        help_text="How far the in-flight review turn has come: fetching the diff, chunking, picking "
        "each chunk's perspectives, reviewing chunks, merging overlapping findings, validating them, "
        "or finalizing (building and publishing the review). A single-agent Standard turn reports its "
        "own `single_agent_*` stages instead: preparing, reviewing (main and lens sessions), and "
        "finalizing (merging, capping, and publishing the findings).",
    )
    done = serializers.IntegerField(
        allow_null=True, help_text="Work units finished within the stage; null when the stage has no counter."
    )
    total = serializers.IntegerField(
        allow_null=True, help_text="Work units the stage expects in total; null when unknown."
    )


class ReviewResolutionStatusSerializer(serializers.Serializer):
    resolution_status = serializers.ChoiceField(
        choices=[RESOLUTION_RESOLVING, RESOLUTION_STOPPED],
        help_text="Where the run stands: `resolving` while threads are being settled, `stopped` when the "
        "run died partway (went quiet with no closing summary).",
    )
    done = serializers.IntegerField(help_text="Queued threads settled so far this run.")
    total = serializers.IntegerField(help_text="Threads queued for this run.")
    fixed = serializers.IntegerField(help_text="Settled threads that were fixed with a commit to the branch.")
    needs_attention = serializers.IntegerField(
        help_text="Settled threads left for the author: judged worth doing but not safe to fix unattended."
    )


class ReviewTriggerReviewMode(models.TextChoices):
    FULL = REVIEW_MODE_FULL, "Deep"
    FLASH = REVIEW_MODE_FLASH, "Standard"


class ReviewLatestResolutionStatus(models.TextChoices):
    RESOLVING = RESOLUTION_RESOLVING, "Resolving"
    STOPPED = RESOLUTION_STOPPED, "Stopped"
    COMPLETED = RESOLUTION_COMPLETED, "Completed"


class ReviewLatestResolutionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=ReviewLatestResolutionStatus.choices,
        help_text="Where the run stands: 'resolving' while threads are being settled, 'completed' when it "
        "finished, 'stopped' when it died partway or a newer review turn replaced it.",
    )
    started_at = serializers.DateTimeField(help_text="When the run queued its threads.")
    completed_at = serializers.DateTimeField(
        allow_null=True, help_text="When the run finished; null unless the status is 'completed'."
    )
    total = serializers.IntegerField(help_text="Threads queued for this run.")
    fixed = serializers.IntegerField(help_text="Threads the run fixed with a commit to the branch.")
    needs_attention = serializers.IntegerField(
        help_text="Threads left for the author: judged worth doing but not safe to fix unattended."
    )
    commits = serializers.ListField(
        child=serializers.CharField(),
        help_text="SHAs of the run's fix commits, oldest first. Only commits confirmed on the pull request "
        "branch that touch no protected files; the replies on GitHub link the same commits.",
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
    published = serializers.BooleanField(
        help_text="Whether any turn of this report has been published back to GitHub. See `turn_published` "
        "for the returned turn."
    )
    turn_published = serializers.BooleanField(
        help_text="Whether the returned turn (the latest completed one, or `run_index` on the detail) was "
        "published to GitHub. False when it found nothing to post or publishing was off."
    )
    review_mode = serializers.ChoiceField(
        choices=ReviewTriggerReviewMode.choices,
        allow_null=True,
        help_text="What the returned turn ran: 'full' (Deep) or 'flash' (Standard). Null when the turn did "
        "not record its mode (turns from before the mode was recorded).",
    )
    status_comment_url = serializers.CharField(
        allow_null=True,
        help_text="Link to the review's status comment on the pull request; null when there is no status "
        "comment or no pull request URL.",
    )
    full_review_published = serializers.BooleanField(
        help_text="Whether a Deep review of this pull request has been published. No Standard review runs after one."
    )
    in_progress = serializers.BooleanField(
        help_text="Whether a run is on this report right now: a review turn or a resolution run "
        "(activity within the last 30 minutes)."
    )
    progress = ReviewProgressSerializer(
        allow_null=True,
        help_text="The in-flight review turn's stage and counters; null unless a review turn is running "
        "(a resolving report carries `resolution` instead).",
    )
    resolution = ReviewResolutionStatusSerializer(
        allow_null=True,
        help_text="The report's latest resolution run (settling the PR's review threads): live progress "
        "while it runs, or where it stopped when it died partway. Null when there is none, it completed, "
        "or a newer review turn superseded it.",
    )
    latest_resolution = ReviewLatestResolutionSerializer(
        allow_null=True,
        help_text="The report's latest resolution run, completed runs included: its status, counts, and "
        "fix commits. Null when no resolution run has queued threads on this report.",
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


class ReviewRecentReviewsPageSerializer(serializers.Serializer):
    results = ReviewRecentReviewSerializer(
        many=True, help_text="The scoped reviews: in-progress runs first, then completed newest first."
    )
    has_more = serializers.BooleanField(
        help_text='Whether reviews exist beyond this page — drives the list\'s "Show more" button.'
    )


_TRIGGER_REFUSAL_STATUS = {
    PRReviewRequestStatus.INVALID: status.HTTP_400_BAD_REQUEST,
    PRReviewRequestStatus.NOT_ALLOWED: status.HTTP_403_FORBIDDEN,
    PRReviewRequestStatus.BUSY: status.HTTP_409_CONFLICT,
    PRReviewRequestStatus.REFUSED: status.HTTP_409_CONFLICT,
}


# Values come from `requested_reviews`, so the API and the comment trigger name the same modes. A
# class (not an inline list) pins the generated enum name.
class ReviewTriggerRequestRunMode(models.TextChoices):
    REVIEW = RUN_MODE_REVIEW, "Review"
    REVIEW_ONLY = RUN_MODE_REVIEW_ONLY, "Review only"
    RESOLVE_ONLY = RUN_MODE_RESOLVE_ONLY, "Resolve only"
    FLASH = RUN_MODE_FLASH, "Standard"


class ReviewTriggerRequestSerializer(serializers.Serializer):
    pr_url = serializers.CharField(
        help_text="GitHub pull request URL to review, e.g. 'https://github.com/PostHog/posthog.com/pull/123'. "
        "The repository must be accessible to the project's GitHub App installation.",
    )
    run_mode = serializers.ChoiceField(
        required=False,
        default=ReviewTriggerRequestRunMode.REVIEW,
        choices=ReviewTriggerRequestRunMode.choices,
        help_text="What to run on the pull request. 'review' (default) reviews it and, when the pull "
        "request owner's resolve_comments setting is on, chains the resolution stage; 'review_only' "
        "reviews without resolving regardless of that setting; 'resolve_only' skips the review and only "
        "runs the resolution stage on the PR's existing unresolved review threads, which needs the owner's "
        "opt-in; 'flash' runs a Standard review: a lower-cost model for the review passes and validation, never resolves "
        "comments, and is refused once the PR has a published Deep review. The owner is the PR's author, "
        "or the Inbox reviewer of a pull request the PostHog app opened.",
    )


class ReviewTriggerResponseSerializer(serializers.Serializer):
    workflow_id = serializers.CharField(
        allow_blank=True, help_text="Temporal workflow id for the started review run; empty when no run was started."
    )
    status = serializers.CharField(
        help_text="Run lifecycle marker: 'started' when the review was queued, 'already_reviewed' when the "
        "pull request's current commit already has a published review in the requested mode, "
        "'joined_running_review' when a review was already running and the request was queued on that "
        "pull request's run, to start after the running turn. "
        "A requested Deep review waits for an active Standard review."
    )
    repository = serializers.CharField(help_text="The pull request's repository as 'owner/repo'.")
    pr_number = serializers.IntegerField(help_text="The pull request number.")
    head_sha = serializers.CharField(
        allow_null=True, help_text="The pull request's head commit when the request was accepted."
    )
    review_mode = serializers.ChoiceField(
        choices=ReviewTriggerReviewMode.choices,
        allow_null=True,
        help_text="The review this request runs: 'full' (Deep) or 'flash' (Standard). Null for 'resolve_only', "
        "which runs no review.",
    )
    report_id = serializers.UUIDField(
        allow_null=True,
        help_text="Id of the pull request's existing review, for `review-hog-reviews-get`. Null on the pull "
        "request's first run, which creates the review later.",
    )
    requested_at = serializers.DateTimeField(help_text="Server time when the request was accepted.")
    resolve_will_run = serializers.BooleanField(
        help_text="Whether this request runs the resolution stage, which can push fix commits to the pull request."
    )
    resolve_skip_reason = serializers.ChoiceField(
        choices=ResolveSkipReason.choices,
        allow_null=True,
        help_text="Why the resolution stage does not run: 'run_mode_excludes_resolve' ('review_only' and "
        "'flash' never resolve), 'owner_not_opted_in' (the pull request owner has not turned on resolving "
        "comments), 'already_reviewed' (no run starts). Null when it runs.",
    )


class ReviewTriggerErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Human-readable explanation of why the trigger was rejected.")
    code = serializers.ChoiceField(
        required=False,
        choices=ReviewRequestRefusal.choices,
        help_text="Why the request was refused, for a client that shows its own reason: 'flash_after_full' "
        "(the PR already has a published Deep review), 'resolution_not_opted_in' (the PR owner has not "
        "turned on resolving comments). Absent for other errors.",
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


class ReviewDetailParamsSerializer(serializers.Serializer):
    run_index = serializers.IntegerField(
        required=False,
        help_text="The completed review turn to read, from 1 to `run_count`. Defaults to the latest "
        "completed turn. Use it to read an older turn's findings.",
    )


class ReviewDetailSerializer(ReviewRecentReviewSerializer):
    run_index = serializers.IntegerField(help_text="The review turn this detail describes, from 1 to `run_count`.")
    head_sha = serializers.CharField(
        allow_null=True,
        help_text="The PR head commit the returned turn reviewed. Anchors GitHub links to the exact code. "
        "Null for an older turn whose head was not recorded.",
    )
    perspective_selection = ReviewPerspectiveSelectionSerializer(
        allow_null=True,
        help_text="The selector's per-chunk perspective plan for the latest turn; null when the turn ran "
        "without a selection (selector unavailable, failed, or the run predates it).",
    )
    report_markdown = serializers.CharField(
        allow_blank=True,
        allow_null=True,
        help_text="The rendered review body published to GitHub, as markdown. Only kept for the latest "
        "turn, so null when `run_index` selects an older turn.",
    )
    run_urgency_threshold = serializers.ChoiceField(
        choices=_PRIORITY_CHOICES,
        allow_null=True,
        help_text="The urgency threshold the returned turn's publishing gated on (stamped at finalize "
        "from the run's own resolve snapshot); null for turns that predate its recording — readers "
        "fall back to the viewer's current setting as an approximation.",
    )
    findings = ReviewFindingSerializer(
        many=True, help_text="The returned turn's validated findings, most urgent first."
    )
    dismissed_findings = ReviewFindingSerializer(
        many=True, help_text="The returned turn's findings the validator dismissed, with its reasoning."
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


class _PageEnvelopeSchema(AutoSchema):
    """Stops drf-spectacular's list-view heuristic from wrapping the `list` response in an array.

    `list` returns a single page envelope (`results` + `has_more`), not a bare collection. The
    default heuristic already returns False for this viewset's other operations, but forcing it
    renames the list operation to `*_retrieve` — pin the operationId back so the generated client
    keeps its `*List` name and doesn't collide with the real retrieve.
    """

    def _is_list_view(self, serializer: Any = None) -> bool:
        return False

    def get_operation_id(self) -> str:
        operation_id = super().get_operation_id()
        if getattr(self.view, "action", None) == "list" and operation_id.endswith("_retrieve"):
            return operation_id.removesuffix("_retrieve") + "_list"
        return operation_id


def _in_progress_report_ids(team_id: int, reports: list[ReviewReport]) -> set[str]:
    """Which ACTIVE reports are visibly running: artefact or report activity within the staleness window.

    Artefacts mark persisted progress, and long review activities refresh the report timestamp while
    their sandbox runs. Both stop when a worker dies, so a crashed run ages out instead of showing
    a stuck spinner forever.

    `finding_outcome` is excluded because it is the one artefact type not written by a turn: the
    outcome sweep appends it after the PR merges, which can be long after the run ended. Counting it
    would restart the staleness window and re-show the spinner for a report with nothing running —
    exactly the crashed-and-never-finalized report (status only leaves ACTIVE on a successful
    finalize) that the ageing-out exists to retire.
    """
    candidates = [report for report in reports if report.status == ReviewReport.Status.ACTIVE]
    if not candidates:
        return set()
    latest_artefact = dict(
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(report_id__in=[report.id for report in candidates])
        .exclude(type=ReviewReportArtefact.ArtefactType.FINDING_OUTCOME)
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


def _turn_progress(
    team_id: int,
    reports: list[ReviewReport],
    in_progress_ids: set[str],
    resolutions: dict[str, ResolutionRunState],
    bundle: TurnFindingsBundle,
) -> dict[str, dict[str, Any]]:
    """The in-flight review turn's stage payload for each visibly running report.

    A resolving report's live run is the resolution, not a review turn. Inferring a review stage
    from the completed turn's artefacts would relabel it "deduplicating".
    """
    resolving_ids = {report_id for report_id, state in resolutions.items() if state.status == RESOLUTION_RESOLVING}
    in_flight = [
        report for report in reports if str(report.id) in in_progress_ids and str(report.id) not in resolving_ids
    ]
    if not in_flight:
        return {}
    live_heads = {str(report.id): report.head_sha for report in in_flight}
    live_snapshots = snapshot_stats(team_id, live_heads)
    live_turns = turn_stats(team_id, live_heads)
    return {
        str(report.id): progress_payload(
            team_id,
            report,
            live_snapshots.get(str(report.id), SnapshotStats()),
            live_turns.get(str(report.id), TurnStats()),
            # The in-flight turn's findings live one run_index ahead of the completed watermark.
            bundle.turn(str(report.id), report.run_count + 1),
        )
        for report in in_flight
    }


def _latest_resolution_payload(summary: ResolutionSummary | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    return {
        "status": summary.status,
        "started_at": summary.started_at,
        "completed_at": summary.completed_at,
        "total": summary.total,
        "fixed": summary.fixed,
        "needs_attention": summary.needs_attention,
        "commits": list(summary.commits),
    }


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
    run_index: int,
    snapshot: SnapshotStats,
    turn: TurnStats,
    pairs: list[tuple[ReviewIssueFinding, ValidationVerdict | None]],
    marker: TurnMarker | None,
    progress: dict[str, Any] | None,
    resolution: ResolutionRunState | None,
    latest_resolution: ResolutionSummary | None,
) -> dict[str, Any]:
    """The list-row payload for one report's turn at `run_index`; the detail endpoint layers findings on top."""
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
        "turn_published": str(run_index) in (report.published_head_shas or {}),
        "review_mode": marker.review_mode if marker else None,
        "status_comment_url": f"{report.pr_url}#issuecomment-{report.status_comment_id}"
        if report.pr_url and report.status_comment_id
        else None,
        # Reads only the per-mode marker, so the list never loads findings to tell older reports apart.
        "full_review_published": REVIEW_MODE_FULL in (report.published_heads_by_mode or {}),
        "in_progress": progress is not None or (resolution is not None and resolution.status == RESOLUTION_RESOLVING),
        "progress": progress,
        "resolution": {
            "resolution_status": resolution.status,
            "done": resolution.done,
            "total": resolution.total,
            "fixed": resolution.fixed,
            "needs_attention": resolution.needs_attention,
        }
        if resolution is not None
        else None,
        "latest_resolution": _latest_resolution_payload(latest_resolution),
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


class EffectiveTeamScopedKeyPermission(BasePermission):
    """Reviews live on the root project, and the API scope check covers only the URL project.

    So a key scoped to an environment must not reach its parent project through an environment URL.
    """

    message = "This key is not scoped to the project that holds the reviews."

    def has_permission(self, request: Request, view: Any) -> bool:
        scoped_teams = get_authenticator_scoped_team_ids(request.successful_authenticator)
        return scoped_teams is None or resolve_effective_team_id(view.team_id) in scoped_teams


class ReviewRecentReviewsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Recent ReviewHog reviews on this project.

    Read-only meta for the Code review tab's "recent reviews" block: what was reviewed, how many
    valid findings at each effective priority, the reviewed PR's facts, and the pipeline shape of
    the latest turn. `list` covers the requesting user's reviews by default — reports where they are
    the acting user OR the PR's author (`author_login` matched case-insensitively against their
    linked GitHub login) — or the whole project's via `scope=everyone`, mirroring the inbox's
    "For you / Entire project" switch; `perspective_stats` honors the same `scope` so the
    effectiveness cards can follow the page-level switch. `retrieve` adds the findings themselves
    (valid + dismissed) and the published review body; it is project-wide so any listed review can
    be opened.
    """

    # `review_hog` rather than INTERNAL so the reads and trigger the Code review UI drives are also
    # reachable with a personal API key or OAuth token, which is how MCP tools authenticate. Session
    # UI access is unchanged; this only adds token access, gated by review_hog:read / review_hog:write.
    scope_object = "review_hog"
    permission_classes = [PostHogFeatureFlagPermission, EffectiveTeamScopedKeyPermission]
    posthog_feature_flag = "review-hog"
    # Unscoped only to satisfy the router/introspection; every real query goes through `for_team`.
    queryset = ReviewReport.objects.unscoped()
    serializer_class = ReviewRecentReviewSerializer
    pagination_class = None
    schema = _PageEnvelopeSchema()

    def _reports(self, request: Request, scope: str = SCOPE_MINE) -> tuple[int, QuerySet[ReviewReport]]:
        team_id = resolve_effective_team_id(self.team_id)
        queryset = ReviewReport.objects.for_team(team_id, canonical=True)
        if scope == SCOPE_MINE:
            # "For you" is the union of reviews the user ran (acting user) and reviews of PRs they
            # authored — a teammate-triggered review of your PR lands under THEIR acting_user, so
            # without the author match the findings would never reach you. The author match rides
            # the viewer's linked GitHub login (the reverse of the author→user mapping the reviewer
            # runs under), case-insensitively; no linked login keeps the acting-user-only behavior.
            mine = Q(acting_user_id=request.user.id)
            github_login = cast(User, request.user).get_github_login()
            if github_login:
                mine |= Q(author_login__iexact=github_login)
            queryset = queryset.filter(mine)
        return team_id, queryset

    @extend_schema(
        parameters=[ReviewsListParamsSerializer],
        responses={
            200: OpenApiResponse(
                response=ReviewRecentReviewsPageSerializer,
                description="The scoped reviews: in-progress runs first, then completed newest first, "
                "with a flag for whether more exist beyond `limit`.",
            ),
        },
        summary="List recent reviews",
        description="Recent ReviewHog reviews on this project: actively running reviews first (with the "
        "in-flight turn's stage), then the most recent completed ones — at most `limit` rows (default 5), "
        "plus `has_more` for whether a larger `limit` would reveal more. By default only the requesting "
        "user's reviews; `scope=everyone` lists every review on the project.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        params = ReviewsListParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        limit: int = params.validated_data["limit"]
        # One row beyond the limit proves whether "Show more" has anything left to reveal.
        probe_limit = limit + 1
        team_id, queryset = self._reports(request, scope=params.validated_data["scope"])
        completed = list(queryset.filter(last_run_at__isnull=False).order_by("-last_run_at")[:probe_limit])
        # First-turn runs have no completed turn yet; they only surface while visibly running. A crashed
        # run stays ACTIVE, so rank by report activity: ranked by creation, newer crashed runs fill the
        # slice and hide an older live run.
        running_first_turn = list(
            queryset.filter(status=ReviewReport.Status.ACTIVE, last_run_at__isnull=True).order_by("-updated_at")[
                :probe_limit
            ]
        )
        # A re-review keeps the previous turn's last_run_at until it finalizes, so a dormant report's
        # in-flight turn can rank below the completed slice — fetch running re-reviews explicitly or
        # an actively reviewed PR vanishes from the list mid-run.
        running_re_review = list(
            queryset.filter(status=ReviewReport.Status.ACTIVE, last_run_at__isnull=False).order_by("-updated_at")[
                :probe_limit
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
        has_more = len(reports) > limit
        reports = reports[:limit]

        # Row stats anchor to each report's COMPLETED turn (matching the findings' run_count); the
        # in-flight progress payload alone reads the live head. Pre-column rows fall back to the live
        # watermark, which is also correct for never-finalized first turns.
        snapshots = snapshot_stats(team_id, {str(r.id): r.completed_head_sha or r.head_sha for r in reports})
        turns = turn_stats(team_id, {str(r.id): r.completed_head_sha or r.head_sha for r in reports})
        report_ids = [str(report.id) for report in reports]
        bundle = load_findings_bundle(team_id=team_id, report_ids=report_ids)
        resolution_map = resolution_states(team_id, reports)
        progress_map = _turn_progress(team_id, reports, in_progress_ids, resolution_map, bundle)
        markers = turn_markers(team_id, report_ids)
        latest_resolutions = latest_resolution_summaries(team_id, reports)
        items = []
        for report in reports:
            report_id = str(report.id)
            items.append(
                _review_payload(
                    report,
                    report.run_count,
                    snapshots.get(report_id, SnapshotStats()),
                    turns.get(report_id, TurnStats()),
                    bundle.turn(report_id, report.run_count),
                    markers.get((report_id, report.run_count)),
                    progress_map.get(report_id),
                    resolution_map.get(report_id),
                    latest_resolutions.get(report_id),
                )
            )
        return Response(ReviewRecentReviewsPageSerializer({"results": items, "has_more": has_more}).data)

    @extend_schema(
        parameters=[PerspectiveStatsParamsSerializer],
        responses={
            200: OpenApiResponse(
                response=ReviewPerspectiveStatsSerializer,
                description="Per-skill effectiveness across the recent completed reviews in scope.",
            ),
        },
        summary="Perspective effectiveness stats",
        description="How many findings each review skill (perspective or blind-spot sweep) raised across the "
        "recent completed reviews in scope — the requesting user's by default, every review on this project "
        "with `scope=everyone`, the user's own last Deep reviews with `scope=own_deep` — and how many of those "
        "the validator kept vs dismissed.",
    )
    @action(methods=["GET"], detail=False, required_scopes=["review_hog:read"])
    def perspective_stats(self, request: Request, **kwargs) -> Response:
        params = PerspectiveStatsParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        scope = params.validated_data["scope"]
        queryset: QuerySet[ReviewReport]
        if scope == PerspectiveStatsScope.OWN_DEEP:
            team_id = resolve_effective_team_id(self.team_id)
            # Filter before the report limit, so newer Standard reports cannot push Deep ones out of the window.
            # Rows from before the per-mode watermark predate Standard reviews.
            queryset = ReviewReport.objects.for_team(team_id, canonical=True).filter(
                Q(published_heads_by_mode__has_key=REVIEW_MODE_FULL) | Q(published_heads_by_mode__isnull=True),
                acting_user_id=request.user.id,
            )
        else:
            team_id, queryset = self._reports(request, scope=scope)
        reports = list(
            queryset.filter(last_run_at__isnull=False).order_by("-last_run_at")[:PERSPECTIVE_STATS_REPORT_LIMIT]
        )
        bundle = load_findings_bundle(team_id=team_id, report_ids=[str(report.id) for report in reports])
        turns = [bundle.turn(str(report.id), report.run_count) for report in reports]
        if scope == PerspectiveStatsScope.OWN_DEEP:
            # Standard turns read none of the user's skills, so they would dilute the kept counts.
            turns = [
                pairs
                for report, pairs in zip(reports, turns)
                if completed_turn_review_mode(report, pairs) == REVIEW_MODE_FULL
            ]
            turns = turns[:OWN_DEEP_STATS_REVIEW_LIMIT]
        stats: dict[str, dict[str, int]] = {}
        for pairs in turns:
            for finding, verdict in pairs:
                entry = stats.setdefault(
                    finding.source_perspective or "unknown", {"raised": 0, "kept": 0, "dismissed": 0}
                )
                entry["raised"] += 1
                if verdict is not None:
                    entry["kept" if verdict.is_valid else "dismissed"] += 1
        items: list[dict[str, Any]] = [{"skill_name": skill_name, **counts} for skill_name, counts in stats.items()]
        items.sort(key=lambda item: (-item["kept"], -item["raised"], item["skill_name"]))
        payload = {"report_count": len(turns), "perspectives": items}
        return Response(ReviewPerspectiveStatsSerializer(payload).data)

    @extend_schema(
        request=ReviewTriggerRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=ReviewTriggerResponseSerializer,
                description="No new run needed: the PR's current commit already has a published review.",
            ),
            202: OpenApiResponse(response=ReviewTriggerResponseSerializer, description="Review run started."),
            400: OpenApiResponse(
                response=ReviewTriggerErrorSerializer,
                description="Invalid PR URL, inaccessible repository, or a nonexistent, closed, or fork PR.",
            ),
            403: OpenApiResponse(
                response=ReviewTriggerErrorSerializer,
                description="The review-hog feature flag is off for this project.",
            ),
            409: OpenApiResponse(
                response=ReviewTriggerErrorSerializer,
                description="The pull request's cycle is busy (busy-guard): reviews are blocked while its "
                "comments are being resolved, and resolve-only runs are blocked while a review is running. "
                "Also returned with a code when a Standard review follows a published Deep review ('flash_after_full') "
                "or the PR owner has not opted in to resolution ('resolution_not_opted_in').",
            ),
            429: OpenApiResponse(description="GitHub rate-limited the App's token; retry after the Retry-After delay."),
        },
        summary="Start a review of a pull request",
        description="Start a ReviewHog review of any pull request the project's GitHub App installation can "
        "access, and publish it back to the PR. The run appears under the requesting user's recent reviews. "
        "A Deep review uses the requester's enabled perspectives, blind-spot check, validator, and urgency "
        "threshold; a Standard review uses none of them. Resolution writes to the branch only when the pull "
        "request owner opted in, whoever asks. `run_mode` picks the variant: 'review' is a Deep review that "
        "chains the resolution stage per the owner's resolve_comments setting, 'review_only' is a Deep review "
        "without resolving, 'resolve_only' runs resolution only, and 'flash' is a lower-cost Standard review "
        "that never resolves comments and is refused after a published Deep review. "
        "Nonexistent, closed, and fork PRs are rejected synchronously. "
        "A PR whose current commit already has a published review in the requested mode returns "
        "'already_reviewed' without starting a run (resolve_only skips that check, because settling threads "
        "on a reviewed head is its whole point). A request while a review runs is queued on that PR's run. "
        "Otherwise non-blocking: returns immediately with the PR's head, the review's id when one exists, and "
        "whether resolution will run, while the run executes in the worker.",
    )
    @action(methods=["POST"], detail=False, required_scopes=["review_hog:write"])
    def trigger(self, request: Request, **kwargs) -> Response:
        team_id = resolve_effective_team_id(self.team_id)
        serializer = ReviewTriggerRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            pr_info = PRParser().parse_github_pr_url(serializer.validated_data["pr_url"])
        except ValueError:
            return Response(
                {
                    "error": "That doesn't look like a GitHub pull request URL (expected https://github.com/OWNER/REPO/pull/NUMBER)"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        requested_at = timezone.now()
        try:
            outcome = request_pr_review(
                team_id=team_id,
                # The route is authenticated, so never anonymous.
                requester_id=cast(User, request.user).id,
                owner=str(pr_info["owner"]),
                repo=str(pr_info["repo"]),
                pr_number=int(pr_info["pr_number"]),
                run_mode=serializer.validated_data["run_mode"],
            )
        except GitHubRateLimitError as e:
            return github_rate_limited_response(e)
        if outcome.error:
            return Response(
                ReviewTriggerErrorSerializer({"error": outcome.error, "code": outcome.refusal}).data
                if outcome.refusal
                else {"error": outcome.error},
                status=_TRIGGER_REFUSAL_STATUS[outcome.status],
            )
        return Response(
            ReviewTriggerResponseSerializer(
                {
                    "workflow_id": outcome.workflow_id,
                    "status": outcome.status.value,
                    "repository": outcome.repository,
                    "pr_number": outcome.pr_number,
                    "head_sha": outcome.head_sha,
                    "review_mode": outcome.review_mode,
                    "report_id": outcome.report_id,
                    "requested_at": requested_at,
                    "resolve_will_run": outcome.resolve_will_run,
                    "resolve_skip_reason": outcome.resolve_skip_reason,
                }
            ).data,
            status=status.HTTP_200_OK
            if outcome.status == PRReviewRequestStatus.ALREADY_REVIEWED
            else status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        parameters=[ReviewDetailParamsSerializer],
        responses={
            200: OpenApiResponse(
                response=ReviewDetailSerializer,
                description="The review's detail: findings (valid and dismissed) and the published body.",
            ),
            404: OpenApiResponse(description="No such review on this project, or no such completed turn."),
        },
        summary="Retrieve one review's detail",
        description="One completed ReviewHog review on this project, with one turn's validated findings, "
        "the findings the validator dismissed (and why), and the review body published to GitHub. The "
        "latest completed turn by default; `run_index` reads an older one. `in_progress`, `progress`, and "
        "the resolution fields describe the report now, whatever the turn. Project-wide, so reviews listed "
        "under `scope=everyone` can be opened too.",
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

        params = ReviewDetailParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        run_index: int = params.validated_data.get("run_index", report.run_count)
        if not 1 <= run_index <= report.run_count:
            raise NotFound("No completed review turn with that run_index.")
        is_latest = run_index == report.run_count

        report_id = str(report.id)
        marker = turn_markers(team_id, [report_id]).get((report_id, run_index))
        # Everything the detail returns (stats, chunk set, link-anchoring head) describes the same
        # completed turn the findings come from, never an in-flight turn's watermark.
        if is_latest:
            turn_head = report.completed_head_sha or report.head_sha
        else:
            turn_head = (marker.head_sha if marker else None) or (report.published_head_shas or {}).get(str(run_index))
        snapshots = snapshot_stats(team_id, {report_id: turn_head})
        turns = turn_stats(team_id, {report_id: turn_head})
        bundle = load_findings_bundle(team_id=team_id, report_ids=[report_id])
        pairs = bundle.turn(report_id, run_index)
        chunk_set = load_chunk_set(team_id=team_id, report_id=report_id, head_sha=turn_head) if turn_head else None
        resolutions = resolution_states(team_id, [report])
        in_progress_ids = _in_progress_report_ids(team_id, [report])
        progress = _turn_progress(team_id, [report], in_progress_ids, resolutions, bundle).get(report_id)

        def sort_key(payload: dict[str, Any]) -> tuple[int, str]:
            return (_PRIORITY_DISPLAY_RANK[IssuePriority(payload["effective_priority"])], payload["file"])

        valid = [_finding_payload(f, v) for f, v in pairs if v is not None and v.is_valid]
        dismissed = [_finding_payload(f, v) for f, v in pairs if v is not None and not v.is_valid]
        payload = {
            **_review_payload(
                report,
                run_index,
                snapshots.get(report_id, SnapshotStats()),
                turns.get(report_id, TurnStats()),
                pairs,
                marker,
                progress,
                resolutions.get(report_id),
                latest_resolution_summaries(team_id, [report]).get(report_id),
            ),
            "run_index": run_index,
            "head_sha": turn_head,
            "report_markdown": report.report_markdown if is_latest else None,
            "run_urgency_threshold": (
                report.run_urgency_threshold
                if is_latest
                else (report.published_urgency_thresholds or {}).get(str(run_index))
            )
            or None,
            "findings": sorted(valid, key=sort_key),
            "dismissed_findings": sorted(dismissed, key=sort_key),
            "perspective_selection": _selection_payload(turns.get(report_id, TurnStats()), chunk_set),
        }
        return Response(ReviewDetailSerializer(payload).data)
