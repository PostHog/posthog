import logging
from collections.abc import Mapping
from typing import Literal

from django.conf import settings

from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.otel_metrics import OtelInstrumentFactory

from products.review_hog.backend.automatic_review_rules import (
    AddedRepositoryNames,
    AutomaticReviewMode,
    AutomaticReviewReason,
    decide_automatic_review,
    find_repository,
)

logger = logging.getLogger(__name__)
_otel = OtelInstrumentFactory("review_hog")

AuthoredPRReviewOutcome = Literal[
    "no_team",
    "installation_mismatch",
    "repository_not_added",
    "author_unmapped",
    "bot_excluded",
    "not_opted_in",
    "full_not_supported",
    "started",
]

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


def _repository_name(value: object) -> str | None:
    full_name = _mapping(value).get("full_name")
    return full_name if isinstance(full_name, str) and full_name.strip() else None


def is_active_member(*, team_id: int, user_id: int) -> bool:
    return OrganizationMembership.objects.filter(
        organization__team__id=team_id, user_id=user_id, user__is_active=True
    ).exists()


def automatic_flash_allowed(*, team_id: int, repository: str, user_id: int, author_login: str) -> bool:
    """Whether the repository rules still give this author an automatic Flash review.

    The workflow calls this again when the run starts, because settings and lists can change while
    the task waits in the queue.
    """
    if not is_active_member(team_id=team_id, user_id=user_id):
        return False
    row = find_repository(team_id, repository)
    if row is None:
        return False
    decision = decide_automatic_review(row, author_user_id=user_id, author_login=author_login)
    return decision.mode == AutomaticReviewMode.FLASH


@frozen
class AuthoredPRReview:
    installation_id: str
    repository: str
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
        # The PR must come from a branch of the same repository, because a fork's head cannot be
        # trusted.
        names = [_repository_name(repo) for repo in (payload.get("repository"), head.get("repo"), base.get("repo"))]
        repository = names[0]
        if repository is None or any(name is None or name.lower() != repository.lower() for name in names):
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
            repository=repository,
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
        # The webhook handler drops repositories nobody added with a cached prefilter, so this
        # branch counts only a repository removed while the task waited, or a stale cache. It runs
        # before the installation check, so "installation_mismatch" still means a misconfigured
        # deploy. The counter carries the signal, so this branch stays out of the logs.
        repository = find_repository(team_id, self.repository)
        if repository is None:
            _observe_dispatch("repository_not_added")
            return
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
        # An inactive user cannot act: every user-scoped sandbox credential of the run would fail.
        if author is None or not is_active_member(team_id=team_id, user_id=author.id):
            logger.info(
                "PR author '%s' is not an active PostHog org user on team %s; skipping automatic review of PR #%s",
                self.author_login,
                team_id,
                self.pr_number,
            )
            _observe_dispatch("author_unmapped")
            return
        decision = decide_automatic_review(repository, author_user_id=author.id, author_login=self.author_login)
        if decision.mode == AutomaticReviewMode.NONE:
            # Most authors on a repository get no automatic review, so this branch stays out of the
            # logs too.
            excluded_bot = decision.reason == AutomaticReviewReason.BOT_EXCLUDED
            _observe_dispatch("bot_excluded" if excluded_bot else "not_opted_in")
            return
        if decision.mode == AutomaticReviewMode.FULL:
            # No automatic Full dispatch exists yet: when a Full review must run (every push or ready
            # for review) is not decided. Flash in its place would post a review the author did not choose.
            _observe_dispatch("full_not_supported")
            return
        start_review_pr_workflow(
            pr_url=f"https://github.com/{self.repository}/pull/{self.pr_number}",
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


def _repository_may_be_added(repository: str) -> bool:
    if not settings.REVIEWHOG_TEAM_IDS:
        return False
    try:
        added = AddedRepositoryNames.get(settings.REVIEWHOG_TEAM_IDS[0])
    except Exception:
        # Fail open: the task checks the repository again, and a Redis blip must not stop reviews.
        logger.warning("Could not read the added ReviewHog repositories; queueing the event", exc_info=True)
        return True
    return repository.lower() in added


def enqueue_authored_pr_review(payload: Mapping[str, object]) -> None:
    review = AuthoredPRReview.from_payload(payload)
    if review is None or not _repository_may_be_added(review.repository):
        return
    from products.review_hog.backend.tasks import (  # noqa: PLC0415 - keeps Celery off the registry import path
        process_authored_pr_event,
    )

    process_authored_pr_event.delay(
        installation_id=review.installation_id,
        repository=review.repository,
        author_login=review.author_login,
        pr_number=review.pr_number,
        head_sha=review.head_sha,
    )
