"""The label trigger: the `reviewhog` label on a pull request starts a Full review.

The PostHog GitHub App's own `labeled` delivery starts it, so the trigger works in every repository the
app is installed on and a project owns (`ownership.py`). One label add is one review: pushes do not
review again, and the workflow removes the label when the run ends.

- A person can add the label, and so can Stamphog, which hands a refused or escalated pull request to
  ReviewHog this way. Another bot's label gets an explaining comment and is removed.
- The review runs in the owning project, which needs the `review-hog-internal` flag.
- It runs as the pull request owner (`pr_owner.py`). Without an owner it runs as the person who
  connected the installation, with default settings and no resolution.
"""

import logging
from typing import Literal

from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, Integration
from posthog.otel_metrics import OtelInstrumentFactory

from products.review_hog.backend.automatic_reviews import connector_user_id
from products.review_hog.backend.internal_features import has_internal_features
from products.review_hog.backend.ownership import RepositoryOwnership, RepositoryRef
from products.review_hog.backend.pr_owner import PullRequestOwnerResolver
from products.review_hog.backend.pull_request_events import REVIEWHOG_LABEL
from products.review_hog.backend.reviewer.persistence import lift_review_tier_for_joined_trigger
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError, github_api_request

logger = logging.getLogger(__name__)
_otel = OtelInstrumentFactory("review_hog")

# Stamphog hands a refused or escalated pull request to ReviewHog with the label.
STAMPHOG_BOT_LOGIN = "stamphog[bot]"

BOT_LABEL_COMMENT = (
    f"ReviewHog reviews start only when a person adds the `{REVIEWHOG_LABEL}` label, so this label from a bot "
    "was removed. Add it again yourself to start a review."
)

LabelReviewOutcome = Literal[
    "repository_not_added",
    "internal_features_off",
    "installation_mismatch",
    "bot_labeler",
    "no_run_user",
    "resolution_running",
    "started",
]

# The label trigger answers nobody, so a skipped label leaves no trace on the pull request. This
# counter names why labels stopped starting reviews.
LABEL_REVIEW_TOTAL = Counter(
    "posthog_review_hog_label_review_total",
    "Label trigger decisions, keyed by outcome",
    labelnames=["outcome"],
)


def _observe(outcome: LabelReviewOutcome) -> None:
    LABEL_REVIEW_TOTAL.labels(outcome=outcome).inc()
    _otel.record_counter_twin(LABEL_REVIEW_TOTAL, 1, {"outcome": outcome})


@frozen
class LabelReview:
    installation_id: str
    repository: str
    github_repo_id: int | None
    pr_number: int
    author_login: str
    # The payload refuses forks, so the head branch is in the base repository.
    head_branch: str
    labeler_login: str
    labeled_by_bot: bool

    @property
    def ref(self) -> RepositoryRef:
        return RepositoryRef(
            installation_id=self.installation_id, github_repo_id=self.github_repo_id, full_name=self.repository
        )

    @property
    def labeler_allowed(self) -> bool:
        return not self.labeled_by_bot or self.labeler_login.lower() == STAMPHOG_BOT_LOGIN

    def _github(self, integration: Integration) -> GitHubIntegration:
        return GitHubIntegration(integration, source="review_hog", priority=Priority.NORMAL)

    def _refuse_bot_label(self, integration: Integration) -> None:
        # The label goes first: a failed call retries the task, and the comment must post only once.
        token = self._github(integration).get_access_token()
        try:
            github_api_request(
                "DELETE",
                f"/repos/{self.repository}/issues/{self.pr_number}/labels/{REVIEWHOG_LABEL}",
                token=token,
                installation_id=self.installation_id,
                endpoint="/repos/{owner}/{repo}/issues/{issue_number}/labels/{name}",
            )
        except GitHubAPIError as error:
            if error.status != 404:
                raise
        github_api_request(
            "POST",
            f"/repos/{self.repository}/issues/{self.pr_number}/comments",
            token=token,
            installation_id=self.installation_id,
            endpoint="/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": BOT_LABEL_COMMENT},
        )

    def start(self) -> None:
        # The temporal package registers the activities, which pull in the sandbox runtime.
        from products.review_hog.backend.temporal.client import (  # noqa: PLC0415
            start_review_pr_workflow,
            workflow_running,
        )
        from products.review_hog.backend.temporal.types import (  # noqa: PLC0415
            TRIGGER_LABEL,
            resolve_pr_workflow_id,
            review_pr_workflow_id,
        )

        owner = RepositoryOwnership.find(self.ref)
        if owner is None:
            _observe("repository_not_added")
            return
        team_id = owner.team_id
        if not has_internal_features(team_id):
            _observe("internal_features_off")
            return
        integration = (
            Integration.objects.filter(team_id=team_id, kind="github", integration_id=self.installation_id)
            .order_by("id")
            .first()
        )
        if integration is None:
            _observe("installation_mismatch")
            return
        if not self.labeler_allowed:
            self._refuse_bot_label(integration)
            _observe("bot_labeler")
            return
        pr_owner = PullRequestOwnerResolver.resolve(
            team_id, repository=self.repository, author_login=self.author_login, head_branch=self.head_branch
        )
        run_user_id = pr_owner.user_id or connector_user_id(team_id=team_id, installation_id=self.installation_id)
        if run_user_id is None:
            _observe("no_run_user")
            return
        github_owner, _, github_repo = self.repository.partition("/")
        # The busy-guard (CONTEXT.md): a review waits until this PR's resolution run is done. The label
        # stays, so a person can add it again once the run ends.
        if workflow_running(
            resolve_pr_workflow_id(team_id=team_id, owner=github_owner, repo=github_repo, pr_number=self.pr_number)
        ):
            _observe("resolution_running")
            return
        # Probed before the start: a same-id start joins the running turn, whose inputs keep the
        # original trigger, so the label's tier lift has to be written here.
        joins_running_review = workflow_running(
            review_pr_workflow_id(team_id=team_id, owner=github_owner, repo=github_repo, pr_number=self.pr_number)
        )
        start_review_pr_workflow(
            pr_url=f"https://github.com/{self.repository}/pull/{self.pr_number}",
            team_id=team_id,
            user_id=run_user_id,
            publish=True,
            trigger_source=TRIGGER_LABEL,
        )
        if joins_running_review:
            lift_review_tier_for_joined_trigger(team_id=team_id, repository=self.repository, pr_number=self.pr_number)
        _observe("started")
