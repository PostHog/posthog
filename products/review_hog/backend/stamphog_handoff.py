"""A published human-review verdict can trigger an opted-in repository's automatic Deep review.

The Inbox handoff handles a refusal or escalation on a self-driving pull request. PostHog Review
reviews the head Stamphog judged. The review is Standard, or Deep once the pull request has a published
Deep review.

Stamphog calls the finished-review callback `receivers.py` registers, after the refusal wins its terminal
save. The callback queues a Celery task, and the task starts the review here.

- The review runs in the project that owns the repository (`ownership.py`), found by name. Stamphog's
  project and GitHub App installation play no part.
- It runs as the pull request owner (`pr_owner.py`). Without an owner it runs as the person who
  connected the installation, with default settings and no resolution.
- A head that already has a pending or completed review is not reviewed again.
"""

import logging
from typing import Literal

from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager
from posthog.otel_metrics import OtelInstrumentFactory

from products.review_hog.backend.automatic_reviews import connector_user_id, plan_automatic_review
from products.review_hog.backend.facade.review_status_types import HeadReviewState
from products.review_hog.backend.head_review_status import HeadReviewStatusLookup
from products.review_hog.backend.ownership import RepositoryOwner, RepositoryOwnership, RepositoryRef
from products.review_hog.backend.pr_owner import PullRequestOwnerResolver
from products.review_hog.backend.review_request_rules import trigger_review_mode
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FULL
from products.review_hog.backend.reviewer.persistence import lift_review_tier_for_joined_trigger

logger = logging.getLogger(__name__)
_otel = OtelInstrumentFactory("review_hog")

StamphogHandoffOutcome = Literal[
    "repository_not_added",
    "integration_missing",
    "head_already_reviewed",
    "no_run_user",
    "resolution_running",
    "started",
]

# The handoff answers nobody, so a skipped handoff leaves no trace on the pull request. This
# counter names why handoffs stopped starting reviews.
STAMPHOG_HANDOFF_TOTAL = Counter(
    "posthog_review_hog_stamphog_handoff_total",
    "Stamphog handoff decisions, keyed by outcome",
    labelnames=["outcome"],
)


def _observe(outcome: StamphogHandoffOutcome) -> None:
    STAMPHOG_HANDOFF_TOTAL.labels(outcome=outcome).inc()
    _otel.record_counter_twin(STAMPHOG_HANDOFF_TOTAL, 1, {"outcome": outcome})


@frozen
class StamphogHandoff:
    repository: str
    pr_number: int
    head_sha: str
    author_login: str
    # Stamphog reviews only same-repository pull requests, so the head branch is in the base repository.
    head_branch: str

    def start(self, *, verdict_team_id: int | None = None, inbox_handoff: bool = True) -> None:
        owner = RepositoryOwnership.find_by_name(self.repository)
        if owner is None:
            _observe("repository_not_added")
            return
        # An automatic request can still skip in the worker. Deliver the Inbox handoff before
        # the automatic request can make the head appear pending.
        inbox_mode = self._start_inbox(owner) if inbox_handoff else None
        if (
            inbox_mode != REVIEW_MODE_FULL
            and owner.team_id == verdict_team_id
            and owner.row is not None
            and owner.row.deep_review_gated_prs
        ):
            self._start_deep(owner, github_repo_id=owner.row.github_repo_id)

    def _start_deep(self, owner: RepositoryOwner, *, github_repo_id: int | None) -> None:
        from products.review_hog.backend.temporal.client import start_review_pr_workflow  # noqa: PLC0415
        from products.review_hog.backend.temporal.types import HUMAN_REVIEW_VERDICT, TRIGGER_AUTOMATIC  # noqa: PLC0415

        ref = RepositoryRef(
            installation_id=owner.installation_id, github_repo_id=github_repo_id, full_name=self.repository
        )
        dispatch = plan_automatic_review(ref, owner, author_login=self.author_login)
        if dispatch.run_as_user_id is None:
            return
        start_review_pr_workflow(
            pr_url=f"https://github.com/{self.repository}/pull/{self.pr_number}",
            team_id=owner.team_id,
            user_id=dispatch.run_as_user_id,
            acting_user_id=dispatch.run_as_user_id,
            publish=True,
            resolve_comments=False,
            review_mode=REVIEW_MODE_FULL,
            trigger_source=TRIGGER_AUTOMATIC,
            trigger_action=HUMAN_REVIEW_VERDICT,
            requested_head_sha=self.head_sha,
            installation_id=owner.installation_id,
            github_repo_id=github_repo_id,
        )

    def _start_inbox(self, owner: RepositoryOwner) -> str | None:
        # The temporal package registers the activities, which pull in the sandbox runtime.
        from products.review_hog.backend.temporal.client import (  # noqa: PLC0415
            start_review_pr_workflow,
            workflow_running,
        )
        from products.review_hog.backend.temporal.types import (  # noqa: PLC0415
            TRIGGER_STAMPHOG,
            resolve_pr_workflow_id,
            review_pr_workflow_id,
        )

        team_id = owner.team_id
        if not IntegrationManager.github.oauth.exists(team_id, external_id=owner.installation_id):
            _observe("integration_missing")
            return None
        # A lookup that fails raises, so the task retries instead of reading an outage as "no review".
        status = HeadReviewStatusLookup(team_id, self.repository, self.pr_number, self.head_sha).status()
        if status is not None and status.state in (HeadReviewState.PENDING, HeadReviewState.COMPLETED):
            _observe("head_already_reviewed")
            return None
        pr_owner = PullRequestOwnerResolver.resolve(
            team_id, repository=self.repository, author_login=self.author_login, head_branch=self.head_branch
        )
        run_user_id = pr_owner.user_id or connector_user_id(team_id=team_id, installation_id=owner.installation_id)
        if run_user_id is None:
            _observe("no_run_user")
            return None
        github_owner, _, github_repo = self.repository.partition("/")
        # The busy-guard (CONTEXT.md): a review waits until this PR's resolution run is done.
        if workflow_running(
            resolve_pr_workflow_id(team_id=team_id, owner=github_owner, repo=github_repo, pr_number=self.pr_number)
        ):
            _observe("resolution_running")
            return None
        # Probed before the start: a same-id start joins the running turn, whose inputs keep the
        # original trigger, so the handoff's tier lift has to be written here.
        joins_running_review = workflow_running(
            review_pr_workflow_id(team_id=team_id, owner=github_owner, repo=github_repo, pr_number=self.pr_number)
        )
        review_mode = trigger_review_mode(team_id, self.repository, self.pr_number)
        start_review_pr_workflow(
            pr_url=f"https://github.com/{self.repository}/pull/{self.pr_number}",
            team_id=team_id,
            user_id=run_user_id,
            publish=True,
            trigger_source=TRIGGER_STAMPHOG,
            review_mode=review_mode,
            requested_head_sha=self.head_sha,
        )
        # Standard is excluded for the same reason as on the comment path: the lift rewrites the
        # persisted arm, so the cheaper review must not raise what later turns cost.
        if joins_running_review and review_mode == REVIEW_MODE_FULL:
            lift_review_tier_for_joined_trigger(team_id=team_id, repository=self.repository, pr_number=self.pr_number)
        _observe("started")
        return review_mode
