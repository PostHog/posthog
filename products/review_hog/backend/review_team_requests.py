"""Reviews asked for by requesting the `posthog-review` team as a reviewer on a pull request.

GitHub cannot list a GitHub App as a requested reviewer, so a team with no members stands in for
PostHog Review. `pull_request_events.py` queues the request, and the task runs it here:

1. The review runs in the project that owns the repository (`ownership.py`).
2. GitHub says the requester's account, matched by its numeric id, can write to the repository.
3. `posthog.github.requesters` finds the requester's PostHog account in that project, under the
   same rules as an `@posthog review` comment, and the account needs editor access to PostHog Review.
4. The review is Standard, or Deep once the pull request has a published Deep review, and runs as
   the requester.

Every final outcome replies to the requester, except a started review, and removes the team's
review request, so requesting the team again asks for the next review. GitHub shows its re-request
button only next to reviewers who submitted a review, and a team never does. A failure that will be
retried leaves the request in place; the last failed attempt replies and removes it.

The webhook prefilter drops a request on a repository that ReviewHog does not review, so GitHub
keeps showing the request there. The team needs access only to the repositories ReviewHog reviews.
"""

import logging
from typing import Literal

import requests
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.github.requesters import (
    GITHUB_WRITE_PERMISSIONS,
    Requester,
    members_with_resource_access,
    resolve_requester,
    users_linked_to_github_account,
)
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError
from posthog.otel_metrics import OtelInstrumentFactory

from products.review_hog.backend.facade.contracts import RUN_MODE_FLASH, RUN_MODE_REVIEW
from products.review_hog.backend.facade.enums import PRReviewRequestStatus
from products.review_hog.backend.ownership import RepositoryOwnership, RepositoryRef
from products.review_hog.backend.pull_request_events import REVIEW_TEAM_SLUG
from products.review_hog.backend.review_request_rules import trigger_review_mode
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FULL

logger = logging.getLogger(__name__)
_otel = OtelInstrumentFactory("review_hog")

ReviewTeamRequestOutcome = Literal[
    "repository_not_added",
    "integration_missing",
    "no_write_access",
    "unlinked",
    "account_refused",
    "no_project",
    "access_denied",
    "refused",
    "already_reviewed",
    "started",
    "failed",
]

# Replies and the request removal are best effort, so a failure in either never fails the task and
# never makes it retry.
_GITHUB_CALL_ERRORS = (GitHubIntegrationError, GitHubRateLimitError, requests.RequestException)

REVIEW_TEAM_REQUEST_TOTAL = Counter(
    "posthog_review_hog_review_team_request_total",
    "Review requests for the posthog-review team, keyed by outcome",
    labelnames=["outcome"],
)

UNLINKED_MESSAGE = (
    "Your GitHub account isn't linked to a PostHog account, so PostHog Review can't tell who to run this "
    "review as. Connect GitHub in your PostHog personal settings, then request the review again."
)
ACCOUNT_REFUSED_MESSAGE = "PostHog Review can't run reviews for your PostHog account."
NO_PROJECT_MESSAGE = (
    "You aren't a member of the PostHog project that reviews this repository. "
    "Ask a project admin to add you, then request the review again."
)
ACCESS_DENIED_MESSAGE = (
    "You need editor access to PostHog Review in the project that reviews this repository. "
    "Ask a project admin for access, then request the review again."
)
NO_WRITE_ACCESS_MESSAGE = "You need write access to this repository to request a PostHog Review."
ALREADY_REVIEWED_MESSAGE = "PostHog Review already reviewed the current commit."
FAILED_MESSAGE = "PostHog Review couldn't start this review. Request the review again in a few minutes."


def _observe(outcome: ReviewTeamRequestOutcome) -> None:
    REVIEW_TEAM_REQUEST_TOTAL.labels(outcome=outcome).inc()
    _otel.record_counter_twin(REVIEW_TEAM_REQUEST_TOTAL, 1, {"outcome": outcome})


@frozen
class ReviewTeamRequest:
    installation_id: str
    repository: str
    github_repo_id: int | None
    pr_number: int
    requester_github_id: int
    requester_login: str

    def start(self, *, final_attempt: bool) -> None:
        owner = RepositoryOwnership.find(
            RepositoryRef(
                installation_id=self.installation_id, github_repo_id=self.github_repo_id, full_name=self.repository
            )
        )
        if owner is None:
            _observe("repository_not_added")
            return
        github = GitHubIntegration.first_for_team_repository(
            owner.team_id, self.repository, source="review_hog", priority=Priority.CRITICAL
        )
        if github is None:
            _observe("integration_missing")
            return
        try:
            outcome = self._review(github, owner.team_id)
        except Exception:
            # Each attempt fails before any reply, so a retry cannot mention the requester twice.
            # The request stays until the last attempt, so the pull request never shows it gone
            # while a retry may still start the review.
            if final_attempt:
                self._reply(github, FAILED_MESSAGE)
                self._remove_team_request(github)
                _observe("failed")
            raise
        self._remove_team_request(github)
        _observe(outcome)

    def _review(self, github: GitHubIntegration, team_id: int) -> ReviewTeamRequestOutcome:
        # A failed lookup raises, so the task retries instead of reading an outage as a refusal.
        permission = github.get_collaborator_permission(
            self.repository, self.requester_login, expected_user_id=self.requester_github_id
        )
        if permission not in GITHUB_WRITE_PERMISSIONS:
            self._reply(github, NO_WRITE_ACCESS_MESSAGE)
            return "no_write_access"
        users = users_linked_to_github_account(self.requester_github_id)
        requester = resolve_requester(users, [team_id], call_site="review_team_request")
        if not isinstance(requester, Requester):
            if requester.reason == "refused":
                self._reply(github, ACCOUNT_REFUSED_MESSAGE)
                return "account_refused"
            self._reply(github, UNLINKED_MESSAGE)
            return "unlinked"
        if not requester.members:
            self._reply(github, NO_PROJECT_MESSAGE)
            return "no_project"
        members = members_with_resource_access(requester.members, users, resource="review_hog", level="editor")
        if not members:
            self._reply(github, ACCESS_DENIED_MESSAGE)
            return "access_denied"

        # The Temporal client pulls in the sandbox runtime, which the webhook enqueue must not load.
        from products.review_hog.backend.requested_reviews import request_member_review  # noqa: PLC0415
        from products.review_hog.backend.temporal.types import TRIGGER_REVIEW_REQUEST  # noqa: PLC0415

        review_mode = trigger_review_mode(team_id, self.repository, self.pr_number)
        outcome = request_member_review(
            team_id=members[0].team_id,
            requester_id=members[0].user_id,
            repository=self.repository,
            pr_number=self.pr_number,
            run_mode=RUN_MODE_REVIEW if review_mode == REVIEW_MODE_FULL else RUN_MODE_FLASH,
            trigger_source=TRIGGER_REVIEW_REQUEST,
        )
        if outcome.status == PRReviewRequestStatus.ALREADY_REVIEWED:
            self._reply(github, ALREADY_REVIEWED_MESSAGE)
            return "already_reviewed"
        if outcome.started:
            return "started"
        self._reply(github, outcome.error or "PostHog Review can't review this pull request.")
        return "refused"

    def _reply(self, github: GitHubIntegration, message: str) -> None:
        # The login is GitHub's, so the mention pings only the person who asked.
        body = f"@{self.requester_login} {message}"
        try:
            result = github.comment_on_pull_request(self.repository, self.pr_number, body)
        except _GITHUB_CALL_ERRORS:
            logger.warning("review_hog_review_team_reply_failed", exc_info=True)
            return
        if not result.get("success"):
            logger.warning("review_hog_review_team_reply_failed", extra={"repository": self.repository})

    def _remove_team_request(self, github: GitHubIntegration) -> None:
        try:
            response = github.api_request(
                "DELETE",
                f"/repos/{self.repository}/pulls/{self.pr_number}/requested_reviewers",
                endpoint="/repos/{owner}/{repo}/pulls/{pull_number}/requested_reviewers",
                # GitHub rejects the call without `reviewers`, even when only a team is removed.
                json_body={"reviewers": [], "team_reviewers": [REVIEW_TEAM_SLUG]},
            )
        except _GITHUB_CALL_ERRORS:
            logger.warning("review_hog_review_team_request_removal_failed", exc_info=True)
            return
        if response.status_code != 200:
            logger.warning("review_hog_review_team_request_removal_failed", extra={"status_code": response.status_code})
