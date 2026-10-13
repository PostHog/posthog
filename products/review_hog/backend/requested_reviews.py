"""Start a review of a pull request because a PostHog user asked for it.

The review trigger in the Code review UI and the `@posthog review` pull request command both come
here, so one place decides which requests start a run. The caller has already authenticated the
requester and checked their access to the project.
"""

import logging
from enum import StrEnum

from django.db import models

from posthog.dataclasses import frozen
from posthog.models.integration import GitHubIntegration

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.pr_owner import PullRequestOwnerResolver
from products.review_hog.backend.review_request_rules import ResolutionGate, ReviewRequestRefusal, flash_refusal
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH, REVIEW_MODE_FULL
from products.review_hog.backend.reviewer.persistence import lift_review_tier_for_joined_trigger
from products.review_hog.backend.reviewer.review_state import review_already_published
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError, github_api_request
from products.review_hog.backend.reviewer.tools.github_meta import PRFetcher, PRMetadata
from products.review_hog.backend.temporal.client import (
    start_resolution_workflow,
    start_review_pr_workflow,
    workflow_running,
)
from products.review_hog.backend.temporal.types import TRIGGER_UI, resolve_pr_workflow_id, review_pr_workflow_id

logger = logging.getLogger(__name__)

# What the trigger runs. The default 'review' includes the resolution stage when the pull request
# owner's `resolve_comments` setting is on; the others are the split button's explicit variants.
# Flash never resolves comments because it must not write code.
RUN_MODE_REVIEW = "review"
RUN_MODE_REVIEW_ONLY = "review_only"
RUN_MODE_RESOLVE_ONLY = "resolve_only"
RUN_MODE_FLASH = "flash"
RUN_MODES = (RUN_MODE_REVIEW, RUN_MODE_REVIEW_ONLY, RUN_MODE_RESOLVE_ONLY, RUN_MODE_FLASH)


class PRReviewRequestStatus(StrEnum):
    STARTED = "started"
    JOINED_RUNNING_REVIEW = "joined_running_review"
    ALREADY_REVIEWED = "already_reviewed"
    # The request cannot start a run as asked: the repository, the pull request or its state.
    INVALID = "invalid"
    # The requested mode is not available in this project.
    NOT_ALLOWED = "not_allowed"
    # The pull request's review cycle is busy, so the request is refused rather than queued.
    BUSY = "busy"
    # A review rule refuses the request for this pull request; `refusal` says which.
    REFUSED = "refused"


class ResolveSkipReason(models.TextChoices):
    """Why an accepted request runs no resolution stage."""

    RUN_MODE_EXCLUDES_RESOLVE = "run_mode_excludes_resolve", "The run mode never resolves comments"
    OWNER_NOT_OPTED_IN = "owner_not_opted_in", "The pull request owner has not opted in to resolution"
    ALREADY_REVIEWED = "already_reviewed", "No run starts, because the head already has a review in this mode"


@frozen
class PRReviewRequestOutcome:
    status: PRReviewRequestStatus
    workflow_id: str = ""
    # Written for the requester. Built from the repository name, the PR number and fixed text only.
    error: str = ""
    refusal: ReviewRequestRefusal | None = None
    repository: str = ""
    pr_number: int | None = None
    head_sha: str | None = None
    # None for a resolve-only run, which reviews nothing.
    review_mode: str | None = None
    # None until the first run of the pull request creates the report.
    report_id: str | None = None
    resolve_skip_reason: ResolveSkipReason | None = None

    @property
    def started(self) -> bool:
        return self.status in (
            PRReviewRequestStatus.STARTED,
            PRReviewRequestStatus.JOINED_RUNNING_REVIEW,
            PRReviewRequestStatus.ALREADY_REVIEWED,
        )

    @property
    def resolve_will_run(self) -> bool:
        return self.started and self.resolve_skip_reason is None


def fetch_pr_metadata(github: GitHubIntegration, owner: str, repo: str, pr_number: int) -> PRMetadata:
    """One `GET /pulls/{n}` with the installation token — enough to answer the trigger honestly.

    Raises `GitHubAPIError` (404 for a nonexistent PR); the caller maps it to a clear response.
    """
    token, installation_id = github.get_access_token(), github.github_installation_id
    pr = github_api_request(
        "GET",
        f"/repos/{owner}/{repo}/pulls/{pr_number}",
        token=token,
        installation_id=installation_id,
        endpoint="/repos/{owner}/{repo}/pulls/{pull_number}",
    ).json()
    return PRFetcher(owner=owner, repo=repo, pr_number=pr_number, token=token).fetch_pr_metadata(pr)


def owner_allows_resolution(team_id: int, repository: str, pr_meta: PRMetadata) -> bool:
    """Whether the pull request owner opted in to resolution. The resolution run checks again before it writes."""
    pull_request_owner = PullRequestOwnerResolver.resolve(
        team_id, repository=repository, author_login=pr_meta.author, head_branch=pr_meta.head_branch
    )
    return ResolutionGate.load(team_id, pull_request_owner.user_id).allows(REVIEW_MODE_FULL)


def accepted_outcome(
    *,
    status: PRReviewRequestStatus,
    workflow_id: str,
    repository: str,
    pr_number: int,
    pr_meta: PRMetadata,
    report: ReviewReport | None,
    review_mode: str | None,
    resolve_skip_reason: ResolveSkipReason | None,
) -> PRReviewRequestOutcome:
    return PRReviewRequestOutcome(
        status=status,
        workflow_id=workflow_id,
        repository=repository,
        pr_number=pr_number,
        head_sha=pr_meta.head_sha,
        review_mode=review_mode,
        report_id=str(report.id) if report is not None else None,
        resolve_skip_reason=resolve_skip_reason,
    )


def request_pr_review(
    *,
    team_id: int,
    requester_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    run_mode: str,
    trigger_source: str = TRIGGER_UI,
) -> PRReviewRequestOutcome:
    """Start the requested run, or say why not.

    The requester is both the run user (sandbox identity) and the acting user, whose perspectives,
    validator, threshold and resolution criteria apply. Every trigger follows the same rules:
    resolution writes only when the pull request owner opted in, and no Flash follows a published
    Full review. Raises `GitHubRateLimitError` when GitHub rate-limits the App's token, so the
    caller can answer with the wait.
    """
    repository = f"{owner}/{repo}"
    # Checked synchronously (one GitHub API call) so an inaccessible repo errors here, in the UI —
    # asynchronously the fetch activity would fail before the report row exists, showing nothing.
    github = GitHubIntegration.first_for_team_repository(team_id, repository)
    if github is None:
        return PRReviewRequestOutcome(
            status=PRReviewRequestStatus.INVALID,
            error=f"PostHog Review's GitHub App can't access {repository}. It reviews repositories covered by this project's GitHub integration.",
        )
    # One PR fetch so the answer is honest: without it a typo'd number or fork dies async (before
    # the report row exists — nothing appears), and an already-reviewed head silently no-ops while
    # the response still claims "started". Fork/closed rejection here is UX; the fetch activity
    # keeps the authoritative fork gate.
    try:
        pr_meta = fetch_pr_metadata(github, owner, repo, pr_number)
    except GitHubAPIError as e:
        if e.status == 404:
            return PRReviewRequestOutcome(
                status=PRReviewRequestStatus.INVALID, error=f"No pull request #{pr_number} found in {repository}"
            )
        raise
    if pr_meta.is_fork:
        return PRReviewRequestOutcome(
            status=PRReviewRequestStatus.INVALID,
            error="PostHog Review doesn't review fork pull requests (a fork's head can't be trusted)",
        )
    if pr_meta.state != "open":
        return PRReviewRequestOutcome(
            status=PRReviewRequestStatus.INVALID,
            error=f"Pull request #{pr_number} is {pr_meta.state}; PostHog Review only reviews open pull requests",
        )
    # The busy-guard (CONTEXT.md): Temporal joins same-id starts on its own, but a review and
    # this PR's resolution run under different workflow ids, so the cross-stage check is
    # explicit — and the answer is a refusal, not a queue.
    if run_mode == RUN_MODE_RESOLVE_ONLY:
        if workflow_running(review_pr_workflow_id(team_id=team_id, owner=owner, repo=repo, pr_number=pr_number)):
            return PRReviewRequestOutcome(
                status=PRReviewRequestStatus.BUSY,
                error="A review is already running on this pull request. It resolves comments when it finishes.",
            )
    elif workflow_running(resolve_pr_workflow_id(team_id=team_id, owner=owner, repo=repo, pr_number=pr_number)):
        return PRReviewRequestOutcome(
            status=PRReviewRequestStatus.BUSY,
            error="Still resolving comments from the last review. Try again when it finishes.",
        )
    # Rebuilt canonical URL: the parser accepts trailing paths (e.g. …/pull/123/files).
    pr_url = f"https://github.com/{owner}/{repo}/pull/{pr_number}"
    # Repository casing can differ per trigger (the report stores whatever its trigger carried).
    report = ReviewReport.objects.for_team(team_id).filter(repository__iexact=repository, pr_number=pr_number).first()

    if run_mode == RUN_MODE_RESOLVE_ONLY:
        # Checked here so the requester sees the answer.
        if not owner_allows_resolution(team_id, repository, pr_meta):
            return PRReviewRequestOutcome(
                status=PRReviewRequestStatus.REFUSED,
                error="Comments are resolved only on pull requests whose owner turned on resolving comments "
                "in their PostHog Review settings.",
                refusal=ReviewRequestRefusal.RESOLUTION_NOT_OPTED_IN,
            )
        # No already-reviewed early-return here: an already-reviewed head is exactly when a
        # standalone resolution run is useful (the threads exist, the review won't re-run).
        workflow_id = start_resolution_workflow(
            pr_url=pr_url,
            team_id=team_id,
            user_id=requester_id,
            acting_user_id=requester_id,
            trigger_source=trigger_source,
        )
        logger.info(
            f"ReviewHog {trigger_source} trigger started resolution {workflow_id} for {pr_url} by user {requester_id}"
        )
        return accepted_outcome(
            status=PRReviewRequestStatus.STARTED,
            workflow_id=workflow_id,
            repository=repository,
            pr_number=pr_number,
            pr_meta=pr_meta,
            report=report,
            review_mode=None,
            resolve_skip_reason=None,
        )

    review_mode = REVIEW_MODE_FLASH if run_mode == RUN_MODE_FLASH else REVIEW_MODE_FULL
    if flash_refusal(report, review_mode) is not None:
        return PRReviewRequestOutcome(
            status=PRReviewRequestStatus.REFUSED,
            error="This pull request already has a Deep review, so it gets no more Standard reviews. "
            "Start a Deep review instead.",
            refusal=ReviewRequestRefusal.FLASH_AFTER_FULL,
        )
    if report is not None and review_already_published(report, pr_meta.head_sha or "", review_mode):
        # The workflow would early-exit before resolving the acting user anyway — say so instead
        # of answering "started" for a run that will do nothing.
        return accepted_outcome(
            status=PRReviewRequestStatus.ALREADY_REVIEWED,
            workflow_id="",
            repository=repository,
            pr_number=pr_number,
            pr_meta=pr_meta,
            report=report,
            review_mode=review_mode,
            resolve_skip_reason=ResolveSkipReason.RUN_MODE_EXCLUDES_RESOLVE
            if run_mode != RUN_MODE_REVIEW
            else ResolveSkipReason.ALREADY_REVIEWED,
        )
    if run_mode != RUN_MODE_REVIEW:
        resolve_skip_reason: ResolveSkipReason | None = ResolveSkipReason.RUN_MODE_EXCLUDES_RESOLVE
    elif owner_allows_resolution(team_id, repository, pr_meta):
        resolve_skip_reason = None
    else:
        resolve_skip_reason = ResolveSkipReason.OWNER_NOT_OPTED_IN
    # Probed before the start: a same-id start joins the running turn, whose inputs keep the
    # original trigger, so the requester's tier lift has to be written here (see the helper).
    joins_running_review = workflow_running(
        review_pr_workflow_id(team_id=team_id, owner=owner, repo=repo, pr_number=pr_number)
    )
    workflow_id = start_review_pr_workflow(
        pr_url=pr_url,
        team_id=team_id,
        user_id=requester_id,
        publish=True,
        acting_user_id=requester_id,
        trigger_source=trigger_source,
        # None = the PR owner's setting decides; review_only and flash pin it off.
        resolve_comments=False if run_mode in (RUN_MODE_REVIEW_ONLY, RUN_MODE_FLASH) else None,
        review_mode=review_mode,
        requested_head_sha=pr_meta.head_sha,
    )
    if joins_running_review:
        # Flash is excluded for the same reason the fetch upsert excludes it: the lift rewrites
        # the persisted arm, so the cheapest request must not raise what later turns cost.
        lifted = run_mode != RUN_MODE_FLASH and lift_review_tier_for_joined_trigger(
            team_id=team_id, repository=repository, pr_number=pr_number
        )
        logger.info(
            f"ReviewHog {trigger_source} trigger joined running workflow {workflow_id} for {pr_url} (tier lifted={lifted})"
        )
        outcome_status = PRReviewRequestStatus.JOINED_RUNNING_REVIEW
    else:
        logger.info(
            f"ReviewHog {trigger_source} trigger started workflow {workflow_id} for {pr_url} by user {requester_id}"
        )
        outcome_status = PRReviewRequestStatus.STARTED
    return accepted_outcome(
        status=outcome_status,
        workflow_id=workflow_id,
        repository=repository,
        pr_number=pr_number,
        pr_meta=pr_meta,
        report=report,
        review_mode=review_mode,
        resolve_skip_reason=resolve_skip_reason,
    )
