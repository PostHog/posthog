import logging
from collections.abc import Mapping
from typing import Literal

from django.conf import settings

from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.otel_metrics import OtelInstrumentFactory

from products.review_hog.backend.models import ReviewUserSettings

AUTOMATIC_REVIEW_REPOSITORY = "PostHog/posthog"

logger = logging.getLogger(__name__)
_otel = OtelInstrumentFactory("review_hog")

AuthoredPRReviewOutcome = Literal["no_team", "installation_mismatch", "author_unmapped", "not_opted_in", "started"]

# A rejected dispatch returns normally, so Celery records the task as successful and no workflow
# starts to report the skip. Without this counter a misconfigured deploy or a drifted installation
# id stops every automatic review with no signal: "started" falling to zero next to a rise in
# another outcome names the cause.
AUTHORED_PR_REVIEW_TOTAL = Counter(
    "posthog_review_hog_authored_pr_review_total",
    "Automatic review dispatch decisions for authored PRs, keyed by outcome",
    labelnames=["outcome"],
)


def _observe_dispatch(outcome: AuthoredPRReviewOutcome) -> None:
    AUTHORED_PR_REVIEW_TOTAL.labels(outcome=outcome).inc()
    _otel.record_counter_twin(AUTHORED_PR_REVIEW_TOTAL, 1, {"outcome": outcome})


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _allowed_repository(value: object) -> bool:
    full_name = _mapping(value).get("full_name")
    return isinstance(full_name, str) and full_name.lower() == AUTOMATIC_REVIEW_REPOSITORY.lower()


def authored_reviews_enabled(*, team_id: int, user_id: int) -> bool:
    return (
        ReviewUserSettings.objects.for_team(team_id)
        .filter(
            user_id=user_id,
            review_authored_prs=True,
            user__is_active=True,
            user__organization_membership__organization__team__id=team_id,
        )
        .exists()
    )


@frozen
class AuthoredPRReview:
    installation_id: str
    author_login: str
    pr_number: int
    head_sha: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "AuthoredPRReview | None":
        if payload.get("action") not in ("opened", "synchronize"):
            return None
        pull_request = _mapping(payload.get("pull_request"))
        if pull_request.get("state") != "open" or pull_request.get("merged"):
            return None
        head = _mapping(pull_request.get("head"))
        base = _mapping(pull_request.get("base"))
        if not all(
            _allowed_repository(repo) for repo in (payload.get("repository"), head.get("repo"), base.get("repo"))
        ):
            return None

        installation_id = _mapping(payload.get("installation")).get("id")
        author_login = _mapping(pull_request.get("user")).get("login")
        pr_number = pull_request.get("number")
        head_sha = head.get("sha")
        if (
            not isinstance(installation_id, int)
            or isinstance(installation_id, bool)
            or installation_id < 1
            or not isinstance(pr_number, int)
            or isinstance(pr_number, bool)
            or pr_number < 1
            or not isinstance(author_login, str)
            or not author_login.strip()
            or not isinstance(head_sha, str)
            or not head_sha.strip()
        ):
            return None
        return cls(
            installation_id=str(installation_id),
            author_login=author_login.strip().lower(),
            pr_number=pr_number,
            head_sha=head_sha,
        )

    def start(self) -> None:
        # These clients pull in the sandbox runtime; enqueueing a webhook must not load it.
        from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH  # noqa: PLC0415
        from products.review_hog.backend.temporal.client import start_review_pr_workflow  # noqa: PLC0415
        from products.review_hog.backend.temporal.types import TRIGGER_AUTOMATIC  # noqa: PLC0415
        from products.signals.backend.report_generation.resolve_reviewers import (  # noqa: PLC0415
            resolve_org_github_login_to_users,
        )

        if not settings.REVIEWHOG_TEAM_IDS:
            logger.warning("No ReviewHog team is configured; skipping automatic review of PR #%s", self.pr_number)
            _observe_dispatch("no_team")
            return
        team_id = settings.REVIEWHOG_TEAM_IDS[0]
        if not Integration.objects.filter(team_id=team_id, kind="github", integration_id=self.installation_id).exists():
            logger.warning(
                "Team %s has no GitHub integration for installation %s; skipping automatic review of PR #%s",
                team_id,
                self.installation_id,
                self.pr_number,
            )
            _observe_dispatch("installation_mismatch")
            return
        author = resolve_org_github_login_to_users(team_id, [self.author_login]).get(self.author_login)
        if author is None:
            logger.info(
                "PR author '%s' is not a PostHog org user on team %s; skipping automatic review of PR #%s",
                self.author_login,
                team_id,
                self.pr_number,
            )
            _observe_dispatch("author_unmapped")
            return
        # The high-volume branch: most authors on the repository have not opted in. The counter
        # carries the signal, so this one stays out of the logs.
        if not authored_reviews_enabled(team_id=team_id, user_id=author.id):
            _observe_dispatch("not_opted_in")
            return
        start_review_pr_workflow(
            pr_url=f"https://github.com/{AUTOMATIC_REVIEW_REPOSITORY}/pull/{self.pr_number}",
            team_id=team_id,
            user_id=author.id,
            acting_user_id=author.id,
            publish=True,
            resolve_comments=False,
            review_mode=REVIEW_MODE_FLASH,
            trigger_source=TRIGGER_AUTOMATIC,
            requested_head_sha=self.head_sha,
        )
        # After the start, so a retried task cannot count a dispatch it never made.
        _observe_dispatch("started")


def enqueue_authored_pr_review(payload: Mapping[str, object]) -> None:
    review = AuthoredPRReview.from_payload(payload)
    if review is None:
        return
    from products.review_hog.backend.tasks import (  # noqa: PLC0415 - keeps Celery off the registry import path
        process_authored_pr_event,
    )

    process_authored_pr_event.delay(
        installation_id=review.installation_id,
        author_login=review.author_login,
        pr_number=review.pr_number,
        head_sha=review.head_sha,
    )
