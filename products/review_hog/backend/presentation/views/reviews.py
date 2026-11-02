import uuid
import dataclasses
from typing import Any, cast, get_args

from django.db import models
from django.utils import timezone

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
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

from products.review_hog.backend.facade.api import (
    get_review_detail,
    get_review_perspective_stats,
    list_recent_reviews,
    list_reviews_table,
)
from products.review_hog.backend.facade.contracts import (
    OWN_DEEP_STATS_REVIEW_LIMIT,
    RESOLUTION_COMPLETED,
    RESOLUTION_RESOLVING,
    RESOLUTION_STOPPED,
    REVIEW_DESIGN_PIPELINE,
    REVIEW_DESIGN_SINGLE_AGENT,
    REVIEW_MODE_FLASH,
    REVIEW_MODE_FULL,
    REVIEW_STAGES,
    RUN_MODE_FLASH,
    RUN_MODE_RESOLVE_ONLY,
    RUN_MODE_REVIEW,
    RUN_MODE_REVIEW_ONLY,
    InvalidPullRequestURLError,
    PRStatus,
    ResolutionSummary,
    ReviewIssueCategory,
    ReviewNotFoundError,
    ReviewTurnNotFoundError,
)
from products.review_hog.backend.facade.enums import (
    IssuePriority,
    PRReviewRequestStatus,
    ResolveSkipReason,
    ReviewActivityFilter,
    ReviewPRState,
    ReviewReportScope,
    ReviewRequestOutcomeStatus,
    ReviewRequestRefusal,
    UrgencyThreshold,
)
from products.review_hog.backend.facade.reviews import get_pr_review_status, request_pr_review_by_url

DEFAULT_REVIEWS_LIMIT = 5
DEFAULT_REVIEWS_TABLE_LIMIT = 25
# Caps "Show more" growth — enrichment (jsonb stats + findings bundle) is per-row work.
MAX_REVIEWS_LIMIT = 100
# Far beyond any real history, and well inside PostgreSQL's bigint OFFSET.
MAX_REVIEWS_TABLE_OFFSET = 1_000_000

_PRIORITY_CHOICES = [priority.value for priority in IssuePriority]

SCOPE_MINE = ReviewReportScope.MINE.value
SCOPE_EVERYONE = ReviewReportScope.EVERYONE.value


class ReviewScope(models.TextChoices):
    MINE = SCOPE_MINE, "Mine"
    EVERYONE = SCOPE_EVERYONE, "Everyone"


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
    OWN_DEEP = ReviewReportScope.OWN_DEEP.value, "Own Deep reviews"


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


class ReviewTriggerReviewMode(models.TextChoices):
    FULL = REVIEW_MODE_FULL, "Deep"
    FLASH = REVIEW_MODE_FLASH, "Standard"


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
    review_mode = serializers.ChoiceField(
        choices=ReviewTriggerReviewMode.choices,
        allow_null=True,
        help_text="What the in-flight turn runs: 'full' (Deep) or 'flash' (Standard). The row's `review_mode` "
        "describes the last completed turn, which can differ. Null until the turn records its mode, "
        "shortly before its review sessions start.",
    )


class ResolutionStatus(models.TextChoices):
    # Labels equal the values, so the schema keeps the descriptions the plain list produced.
    RESOLVING = RESOLUTION_RESOLVING, RESOLUTION_RESOLVING
    STOPPED = RESOLUTION_STOPPED, RESOLUTION_STOPPED


class ReviewResolutionStatusSerializer(serializers.Serializer):
    resolution_status = serializers.ChoiceField(
        source="status",
        choices=ResolutionStatus.choices,
        help_text="Where the run stands: `resolving` while threads are being settled, `stopped` when the "
        "run died partway (went quiet with no closing summary).",
    )
    done = serializers.IntegerField(help_text="Queued threads settled so far this run.")
    total = serializers.IntegerField(help_text="Threads queued for this run.")
    fixed = serializers.IntegerField(help_text="Settled threads that were fixed with a commit to the branch.")
    needs_attention = serializers.IntegerField(
        help_text="Settled threads left for the author: judged worth doing but not safe to fix unattended."
    )


class ReviewTurnDesign(models.TextChoices):
    PIPELINE = REVIEW_DESIGN_PIPELINE, "Pipeline"
    SINGLE_AGENT = REVIEW_DESIGN_SINGLE_AGENT, "Single agent"


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
    review_design = serializers.ChoiceField(
        choices=ReviewTurnDesign.choices,
        allow_null=True,
        help_text="How the returned turn found its issues. 'pipeline': chunks, perspectives, a blind-spot sweep "
        "and a separate validation step. 'single_agent': one main review plus focused lenses, with no separate "
        "validation step. Null when the turn recorded no design (turns from before it was recorded ran the "
        "pipeline).",
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


class ReviewTableStatus(models.TextChoices):
    RUNNING = ReviewActivityFilter.RUNNING.value, "Running"
    COMPLETED = ReviewActivityFilter.COMPLETED.value, "Completed"


class ReviewsTableParamsSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(
        choices=ReviewScope.choices,
        default=SCOPE_MINE,
        help_text="Whose reviews to list: `mine` (the default) for reviews the requesting user ran "
        "plus reviews of pull requests they authored (matched via their linked GitHub login), "
        "`everyone` for every review on this project.",
    )
    repository = serializers.CharField(
        required=False,
        help_text="Only reviews of this repository, as `owner/repo`. Matched case-insensitively.",
    )
    review_mode = serializers.ChoiceField(
        choices=ReviewTriggerReviewMode.choices,
        required=False,
        help_text="Only reviews whose latest completed turn ran this mode: 'full' (Deep) or 'flash' "
        "(Standard). Turns that did not record their mode match neither value.",
    )
    status = serializers.ChoiceField(
        choices=ReviewTableStatus.choices,
        required=False,
        help_text="Only reviews in this state: 'running' for reviews with a run in flight (activity within "
        "the last 30 minutes), 'completed' for reviews with a completed turn and nothing running now.",
    )
    published = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Only reviews whose latest completed turn was (true) or was not (false) published to GitHub.",
    )
    limit = serializers.IntegerField(
        default=DEFAULT_REVIEWS_TABLE_LIMIT,
        min_value=1,
        max_value=MAX_REVIEWS_LIMIT,
        help_text=f"Rows per page. Defaults to {DEFAULT_REVIEWS_TABLE_LIMIT}, at most {MAX_REVIEWS_LIMIT}.",
    )
    offset = serializers.IntegerField(
        default=0,
        min_value=0,
        max_value=MAX_REVIEWS_TABLE_OFFSET,
        help_text="How many rows to skip, for paging through the table.",
    )


class ReviewReviewsTablePageSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="How many reviews match the scope and every filter, across all pages.")
    running_count = serializers.IntegerField(
        help_text="How many reviews have a run in flight under the scope and filters, ignoring `status`. "
        "Labels the running quick filter without a second request."
    )
    results = ReviewRecentReviewSerializer(many=True, help_text="One page of reviews, most recent activity first.")


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
        help_text="Whether this request plans to run the resolution stage, which can push fix commits to the pull "
        "request. It is the plan at request time: a request queued behind a running turn on the same head can be "
        "skipped as already published. `review-hog-reviews-pr-status` reports what actually ran."
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


class ReviewPRStatusParamsSerializer(serializers.Serializer):
    pr_url = serializers.CharField(
        help_text="GitHub pull request URL to look up, e.g. 'https://github.com/PostHog/posthog/pull/123'.",
    )
    requested_at = serializers.DateTimeField(
        required=False,
        help_text="The `requested_at` the trigger returned. When set, the response carries `request_outcome` "
        "for that request.",
    )
    run_mode = serializers.ChoiceField(
        required=False,
        default=ReviewTriggerRequestRunMode.REVIEW,
        choices=ReviewTriggerRequestRunMode.choices,
        help_text="The `run_mode` the trigger was called with (default 'review'). Only used with `requested_at`.",
    )
    head_sha = serializers.CharField(
        required=False,
        help_text="The `head_sha` the trigger returned. Lets a turn that was already running on that head when "
        "the request came in answer the request. Only used with `requested_at`.",
    )


class ReviewPRStatusLatestReviewSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The review's id, for `review-hog-reviews-get`.")
    review_mode = serializers.ChoiceField(
        choices=ReviewTriggerReviewMode.choices,
        allow_null=True,
        help_text="What the turn ran: 'full' (Deep) or 'flash' (Standard). Null when the turn did not record it.",
    )
    head_sha = serializers.CharField(allow_null=True, help_text="The PR head commit the turn reviewed.")
    run_index = serializers.IntegerField(help_text="The turn's index, for `review-hog-reviews-get`.")
    completed_at = serializers.DateTimeField(allow_null=True, help_text="When the turn completed.")
    must_fix_count = serializers.IntegerField(help_text="The turn's valid findings at must_fix priority.")
    should_fix_count = serializers.IntegerField(help_text="The turn's valid findings at should_fix priority.")
    consider_count = serializers.IntegerField(help_text="The turn's valid findings at consider priority.")
    turn_published = serializers.BooleanField(help_text="Whether the turn was published to GitHub.")
    status_comment_url = serializers.CharField(
        allow_null=True, help_text="Link to the review's status comment on the pull request; null when there is none."
    )


class ReviewPRStatusRequestOutcomeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=ReviewRequestOutcomeStatus.choices,
        help_text="How the request ended: 'pending' while a run for it is queued or running, 'completed' when a "
        "turn of the requested mode or deeper finished after `requested_at` and either started after it or "
        "reviewed the given `head_sha` (Deep covers Standard), 'skipped' "
        "when the run ended without doing the work, 'failed' when the run died or no run answered the request, "
        "'unknown' when the run state could not be read (retry later).",
    )
    reason = serializers.CharField(
        allow_null=True,
        help_text="Why it was skipped or failed: 'flash_after_full' (Standard dropped after a Deep review), "
        "'review_failed', 'stopped' (Resolve died partway), 'no_matching_run' (nothing ran for the request and "
        "nothing is queued, for example when the queue replaced it), or a Resolve skip reason such as "
        "'pr_not_open', 'resolution_not_opted_in', 'no_unresolved_threads', 'pr_in_merge_queue'. Null otherwise.",
    )
    review_id = serializers.UUIDField(
        allow_null=True, help_text="The review to read with `review-hog-reviews-get`; null before the PR has one."
    )
    run_index = serializers.IntegerField(
        allow_null=True,
        help_text="The review turn that answered or failed the request, for `review-hog-reviews-get`. Null for "
        "'resolve_only' and while pending.",
    )


class ReviewPRStatusSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="The pull request's repository as 'owner/repo'.")
    pr_number = serializers.IntegerField(help_text="The pull request number.")
    report_id = serializers.UUIDField(
        allow_null=True, help_text="The PR's review id, for `review-hog-reviews-get`; null before its first run."
    )
    state = serializers.ChoiceField(
        choices=ReviewPRState.choices,
        help_text="Where the PR stands now: 'not_reviewed' (no completed review and nothing queued), 'queued' "
        "(a run is queued or starting), 'reviewing' (a review turn is running), 'resolving' (Resolve is "
        "running), 'idle' (nothing running), 'unknown' (the run state could not be read, retry later).",
    )
    latest_review = ReviewPRStatusLatestReviewSerializer(
        allow_null=True, help_text="The latest completed review turn; null before the first one completes."
    )
    latest_resolution = ReviewLatestResolutionSerializer(
        allow_null=True,
        help_text="The latest Resolve run, finished ones too; null when no Resolve run has queued threads.",
    )
    request_outcome = ReviewPRStatusRequestOutcomeSerializer(
        allow_null=True, help_text="How the request at `requested_at` ended; null without `requested_at`."
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


# Mirrors `DropDisposition`.
class ReviewDropDisposition(models.TextChoices):
    OLD_CODE = "old_code", "On unchanged code"
    DEDUP_PRIOR = "dedup_prior", "Repeat of an earlier review"
    DEDUP_COMMENT = "dedup_comment", "Already in a PR comment"
    DEDUP_ANCHOR = "dedup_anchor", "Same spot as another finding"
    DEDUP_SIBLING = "dedup_sibling", "Repeat of a finding"
    CAP = "cap", "Over the limit"
    BUDGET = "budget", "Over the pull request limit"


class ReviewDroppedFindingPriority(models.TextChoices):
    MUST_FIX = IssuePriority.MUST_FIX.value, "Must fix"
    SHOULD_FIX = IssuePriority.SHOULD_FIX.value, "Should fix"
    CONSIDER = IssuePriority.CONSIDER.value, "Consider"


class ReviewDroppedFindingSerializer(serializers.Serializer):
    title = serializers.CharField(help_text="One-line summary of the finding.")
    file = serializers.CharField(help_text="Repository-relative path of the affected file.")
    lines = ReviewFindingLineRangeSerializer(many=True, help_text="Affected line ranges within the file.")
    body = serializers.CharField(help_text="Description of the problem.")
    suggestion = serializers.CharField(
        allow_blank=True,
        help_text="The specific fix the reviewer proposes. Usually empty: a single-agent finding ends its body "
        "with the fix direction instead.",
    )
    priority = serializers.ChoiceField(
        choices=ReviewDroppedFindingPriority.choices, help_text="The reviewer's priority for the finding."
    )
    source_perspective = serializers.CharField(
        allow_null=True, help_text="The session that raised the finding: the main review or a lens."
    )
    disposition = serializers.ChoiceField(
        choices=ReviewDropDisposition.choices,
        help_text="Why the turn did not post the finding. `old_code`: a follow-up turn's finding on code that "
        "did not change since the last reviewed head. An automatic follow-up (run 2 and later) drops P2 and P3 "
        "findings this way, a requested review drops only P3, and a first review drops none. "
        "`dedup_prior`: repeats an earlier turn's finding. "
        "`dedup_comment`: repeats a PR comment. `dedup_anchor`: repeats a main-review finding at the same "
        "spot. `dedup_sibling`: repeats another finding from the same session or lens. `cap`: ranked below "
        "the per-review finding limit.",
    )
    duplicate_of = serializers.CharField(
        allow_null=True,
        help_text="For a dedup drop, what it repeats: an issue key, or `comment:<id>` for a PR comment. "
        "Null for other dispositions.",
    )
    comment_url = serializers.CharField(
        allow_null=True,
        help_text="Link to the PR comment the finding repeats, when `duplicate_of` names one and the PR URL is "
        "known. Null otherwise.",
    )
    rank = serializers.IntegerField(
        allow_null=True,
        help_text="For a `cap` drop, the finding's 1-based position in the turn's ranked findings. Null otherwise.",
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
        choices=UrgencyThreshold.choices,
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
    dropped_findings = ReviewDroppedFindingSerializer(
        many=True,
        help_text="The returned turn's findings a single-agent (Standard) review raised but did not post, each "
        "with the reason. Empty for pipeline turns and for turns that predate the record.",
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


def _pr_status_payload(pr_status: PRStatus) -> dict[str, Any]:
    latest = pr_status.latest_review
    outcome = pr_status.request_outcome
    return {
        "repository": pr_status.repository,
        "pr_number": pr_status.pr_number,
        "report_id": pr_status.report_id,
        "state": pr_status.state,
        "latest_review": {
            "id": latest.review_id,
            "review_mode": latest.review_mode,
            "head_sha": latest.head_sha,
            "run_index": latest.run_index,
            "completed_at": latest.completed_at,
            "must_fix_count": latest.must_fix_count,
            "should_fix_count": latest.should_fix_count,
            "consider_count": latest.consider_count,
            "turn_published": latest.turn_published,
            "status_comment_url": latest.status_comment_url,
        }
        if latest is not None
        else None,
        "latest_resolution": _latest_resolution_payload(pr_status.latest_resolution),
        "request_outcome": {
            "status": outcome.status,
            "reason": outcome.reason,
            "review_id": outcome.review_id,
            "run_index": outcome.run_index,
        }
        if outcome is not None
        else None,
    }


_INVALID_PR_URL_ERROR = (
    "That doesn't look like a GitHub pull request URL (expected https://github.com/OWNER/REPO/pull/NUMBER)"
)


class EffectiveTeamScopedKeyPermission(BasePermission):
    """Reviews live on the root project, and the API scope check covers only the URL project.

    So a key scoped to an environment must not reach its parent project through an environment URL.
    """

    message = "This key is not scoped to the project that holds the reviews."

    def has_permission(self, request: Request, view: Any) -> bool:
        scoped_teams = get_authenticator_scoped_team_ids(request.successful_authenticator)
        return scoped_teams is None or resolve_effective_team_id(view.team_id) in scoped_teams


class ReviewRecentReviewsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Recent code reviews on this project.

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
    serializer_class = ReviewRecentReviewSerializer
    pagination_class = None
    schema = _PageEnvelopeSchema()

    def _root_team_id(self) -> int:
        return resolve_effective_team_id(self.team_id)

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
        description="Recent code reviews on this project: actively running reviews first (with the "
        "in-flight turn's stage), then the most recent completed ones — at most `limit` rows (default 5), "
        "plus `has_more` for whether a larger `limit` would reveal more. By default only the requesting "
        "user's reviews; `scope=everyone` lists every review on the project.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        params = ReviewsListParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        page = list_recent_reviews(
            self._root_team_id(),
            cast(User, request.user).id,
            ReviewReportScope(params.validated_data["scope"]),
            params.validated_data["limit"],
        )
        return Response(ReviewRecentReviewsPageSerializer(page).data)

    @extend_schema(
        parameters=[ReviewsTableParamsSerializer],
        responses={
            200: OpenApiResponse(
                response=ReviewReviewsTablePageSerializer,
                description="One page of reviews, most recent activity first, with the total and running counts.",
            ),
        },
        summary="List reviews as a paginated table",
        description="Code reviews on this project as a paginated table: reviews with a completed turn "
        "plus reviews with a run in flight, ordered by last activity, so a review that starts or finishes "
        "moves to the top. Pages with `limit` and `offset`; `count` is the total across pages. Filters by "
        "`repository`, `review_mode`, `status`, and `published`. `running_count` counts the running reviews "
        "under every filter except `status`. By default only the requesting user's reviews; "
        "`scope=everyone` lists every review on the project.",
    )
    @action(methods=["GET"], detail=False, required_scopes=["review_hog:read"])
    def table(self, request: Request, **kwargs) -> Response:
        params = ReviewsTableParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        filters = params.validated_data
        page = list_reviews_table(
            self._root_team_id(),
            cast(User, request.user).id,
            ReviewReportScope(filters["scope"]),
            repository=filters.get("repository"),
            review_mode=filters.get("review_mode"),
            activity=ReviewActivityFilter(filters["status"]) if "status" in filters else None,
            published=filters["published"],
            limit=filters["limit"],
            offset=filters["offset"],
        )
        return Response(ReviewReviewsTablePageSerializer(page).data)

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
        stats = get_review_perspective_stats(
            self._root_team_id(), cast(User, request.user).id, ReviewReportScope(params.validated_data["scope"])
        )
        return Response(ReviewPerspectiveStatsSerializer(stats).data)

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
        description="Start a PostHog Review run on any pull request the project's GitHub App installation can "
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
        team_id = self._root_team_id()
        serializer = ReviewTriggerRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        requested_at = timezone.now()
        try:
            outcome = request_pr_review_by_url(
                team_id=team_id,
                # The route is authenticated, so never anonymous.
                requester_id=cast(User, request.user).id,
                pr_url=serializer.validated_data["pr_url"],
                run_mode=serializer.validated_data["run_mode"],
            )
        except InvalidPullRequestURLError:
            return Response({"error": _INVALID_PR_URL_ERROR}, status=status.HTTP_400_BAD_REQUEST)
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
        parameters=[ReviewPRStatusParamsSerializer],
        responses={
            200: OpenApiResponse(response=ReviewPRStatusSerializer, description="The pull request's review status."),
            400: OpenApiResponse(description="Not a GitHub pull request URL, or an invalid parameter."),
        },
        summary="Look up a pull request's review status",
        description="Where a pull request's review runs stand: `state`, the latest completed review turn, and "
        "the latest Resolve run. Works for any pull request on the project, also ones the caller did not "
        "trigger. Pass the `requested_at` and `head_sha` the trigger returned, and the `run_mode` it was called "
        "with, to get `request_outcome`, which says when that request is done.",
    )
    @action(methods=["GET"], detail=False, required_scopes=["review_hog:read"])
    def pr_status(self, request: Request, **kwargs) -> Response:
        team_id = self._root_team_id()
        params = ReviewPRStatusParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        try:
            pr_status = get_pr_review_status(
                team_id=team_id,
                pr_url=params.validated_data["pr_url"],
                requested_at=params.validated_data.get("requested_at"),
                run_mode=params.validated_data["run_mode"],
                head_sha=params.validated_data.get("head_sha"),
            )
        except InvalidPullRequestURLError:
            return Response({"error": _INVALID_PR_URL_ERROR}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ReviewPRStatusSerializer(_pr_status_payload(pr_status)).data)

    @extend_schema(
        parameters=[
            # The viewset has no queryset, so the path parameter does not get its type from the model.
            OpenApiParameter(
                "id",
                OpenApiTypes.UUID,
                OpenApiParameter.PATH,
                description="A UUID string identifying this review report.",
            ),
            ReviewDetailParamsSerializer,
        ],
        responses={
            200: OpenApiResponse(
                response=ReviewDetailSerializer,
                description="The review's detail: findings (valid and dismissed) and the published body.",
            ),
            404: OpenApiResponse(description="No such review on this project, or no such completed turn."),
        },
        summary="Retrieve one review's detail",
        description="One completed code review on this project, with one turn's validated findings, "
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
        params = ReviewDetailParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        try:
            detail = get_review_detail(self._root_team_id(), report_uuid, params.validated_data.get("run_index"))
        except ReviewTurnNotFoundError:
            raise NotFound("No completed review turn with that run_index.")
        except ReviewNotFoundError:
            raise NotFound("Review not found.")
        # The detail serializer extends the list row, so the row's fields sit next to the detail's own.
        data = dataclasses.asdict(detail)
        data.update(data.pop("review"))
        return Response(ReviewDetailSerializer(data).data)
