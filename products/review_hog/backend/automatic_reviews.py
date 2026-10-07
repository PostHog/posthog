import logging
from collections.abc import Mapping
from typing import Literal

from django.conf import settings

from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.models.user import User
from posthog.otel_metrics import OtelInstrumentFactory

from products.review_hog.backend.models import ReviewUserSettings
from products.review_hog.backend.repository_config import (
    RepositoryConfigError,
    RepositoryReviewConfig,
    SkipReason,
    load_repository_config,
)

logger = logging.getLogger(__name__)
_otel = OtelInstrumentFactory("review_hog")

AuthoredPRReviewOutcome = (
    Literal[
        "event_state_missing",
        "no_team",
        "installation_mismatch",
        "no_config",
        "config_invalid",
        "author_unmapped",
        "not_opted_in",
        "started",
    ]
    | SkipReason
)

# A rejected dispatch returns normally, so Celery records the task as successful and no workflow
# starts to report the skip. Without this counter a misconfigured deploy, a drifted installation
# id, or a broken config file stops every automatic review with no signal: "started" falling to
# zero next to a rise in another outcome names the cause.
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


def _full_name(value: object) -> str | None:
    full_name = _mapping(value).get("full_name")
    return full_name if isinstance(full_name, str) and full_name.count("/") == 1 else None


def _label_names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(name for name in (_mapping(label).get("name") for label in value) if isinstance(name, str))


def automatic_review_allowed(*, team_id: int, user_id: int, require_opt_in: bool = True) -> bool:
    """Whether this author's PRs may be reviewed automatically on `team_id` right now.

    Membership is always required, so a user who left the organization stops being reviewed on
    their next push. The opt-in is the author's own "Review all your PRs in Flash mode" switch,
    which a repository config with `authors: members` waives.
    """
    member = User.objects.filter(
        id=user_id, is_active=True, organization_membership__organization__team__id=team_id
    ).exists()
    if not member:
        return False
    if not require_opt_in:
        return True
    return ReviewUserSettings.objects.for_team(team_id).filter(user_id=user_id, review_authored_prs=True).exists()


@frozen
class AuthoredPRReview:
    installation_id: str
    repository: str
    author_login: str
    pr_number: int
    head_sha: str
    action: str
    base_ref: str
    draft: bool
    labels: tuple[str, ...]

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "AuthoredPRReview | None":
        action = payload.get("action")
        # Removing a skip label or retargeting the base branch can clear a gate that skipped the
        # PR's earlier events. An `edited` event that changes only the title or body clears nothing.
        if action == "edited":
            if "base" not in _mapping(payload.get("changes")):
                return None
        elif action not in ("opened", "synchronize", "ready_for_review", "unlabeled"):
            return None
        pull_request = _mapping(payload.get("pull_request"))
        if pull_request.get("state") != "open" or pull_request.get("merged"):
            return None
        head = _mapping(pull_request.get("head"))
        base = _mapping(pull_request.get("base"))
        # The head must live in the reviewed repository: a fork's branch is checked out and read
        # by the sandbox, so a stranger's commit must never start a review under the team's budget.
        repository = _full_name(payload.get("repository"))
        if repository is None:
            return None
        for repo in (head.get("repo"), base.get("repo")):
            full_name = _full_name(repo)
            if full_name is None or full_name.lower() != repository.lower():
                return None

        installation_id = _mapping(payload.get("installation")).get("id")
        author_login = _mapping(pull_request.get("user")).get("login")
        pr_number = pull_request.get("number")
        head_sha = head.get("sha")
        base_ref = base.get("ref")
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
            or not isinstance(base_ref, str)
            or not base_ref
        ):
            return None
        return cls(
            installation_id=str(installation_id),
            repository=repository,
            author_login=author_login.strip().lower(),
            pr_number=pr_number,
            head_sha=head_sha,
            action=str(action),
            base_ref=base_ref,
            draft=bool(pull_request.get("draft")),
            labels=_label_names(pull_request.get("labels")),
        )

    @property
    def pr_url(self) -> str:
        return f"https://github.com/{self.repository}/pull/{self.pr_number}"

    def _load_config(self, integration: Integration) -> RepositoryReviewConfig | None:
        """The repository's config on its default branch, or None after recording why no review starts."""
        try:
            config = load_repository_config(integration, self.repository)
        except RepositoryConfigError as e:
            logger.warning("Skipping automatic review of %s: %s", self.pr_url, e)
            _observe_dispatch("config_invalid")
            return None
        if config is None:
            _observe_dispatch("no_config")
            return None
        return config

    def start(self) -> None:
        # These clients pull in the sandbox runtime; enqueueing a webhook must not load it.
        from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH  # noqa: PLC0415
        from products.review_hog.backend.temporal.client import start_review_pr_workflow  # noqa: PLC0415
        from products.review_hog.backend.temporal.types import (  # noqa: PLC0415
            TRIGGER_AUTOMATIC,
            RepositoryReviewPolicy,
        )
        from products.signals.backend.report_generation.resolve_reviewers import (  # noqa: PLC0415
            resolve_org_github_login_to_users,
        )

        if not settings.REVIEWHOG_TEAM_IDS:
            logger.warning("No ReviewHog team is configured; skipping automatic review of %s", self.pr_url)
            _observe_dispatch("no_team")
            return
        team_id = settings.REVIEWHOG_TEAM_IDS[0]
        # The installation is the repository boundary: every repository the team's GitHub App
        # installation covers is eligible, and only a config file in the repository turns it on.
        integration = Integration.objects.filter(
            team_id=team_id, kind="github", integration_id=self.installation_id
        ).first()
        if integration is None:
            logger.warning(
                "Team %s has no GitHub integration for installation %s; skipping automatic review of %s",
                team_id,
                self.installation_id,
                self.pr_url,
            )
            _observe_dispatch("installation_mismatch")
            return
        # Resolved before the config is read: a bot or outside contributor is the common author
        # across the installation, and rejecting one here costs a database query instead of a
        # GitHub API call against the installation's shared budget.
        author = resolve_org_github_login_to_users(team_id, [self.author_login]).get(self.author_login)
        if author is None:
            logger.info(
                "PR author '%s' is not a PostHog org user on team %s; skipping automatic review of %s",
                self.author_login,
                team_id,
                self.pr_url,
            )
            _observe_dispatch("author_unmapped")
            return
        config = self._load_config(integration)
        if config is None:
            return
        skip_reason = config.skip_reason(
            action=self.action,
            draft=self.draft,
            base_ref=self.base_ref,
            labels=self.labels,
            author_login=self.author_login,
        )
        if skip_reason is not None:
            _observe_dispatch(skip_reason)
            return
        # The high-volume branch: most authors on a repository have not opted in. The counter
        # carries the signal, so this one stays out of the logs.
        if not automatic_review_allowed(
            team_id=team_id, user_id=author.id, require_opt_in=config.author_opt_in_required
        ):
            _observe_dispatch("not_opted_in")
            return
        start_review_pr_workflow(
            pr_url=self.pr_url,
            team_id=team_id,
            user_id=author.id,
            acting_user_id=author.id,
            publish=True,
            resolve_comments=False,
            review_mode=REVIEW_MODE_FLASH,
            trigger_source=TRIGGER_AUTOMATIC,
            requested_head_sha=self.head_sha,
            repository_policy=RepositoryReviewPolicy(
                author_opt_in_required=config.author_opt_in_required,
                flash_reasoning_effort=config.flash_reasoning_effort,
                instructions=config.instructions,
            ),
        )
        # After the start, so a retried task cannot count a dispatch it never made.
        _observe_dispatch("started")


def skip_event_without_state(pr_number: int) -> None:
    """Drop a task queued before the event's draft, base branch, and labels travelled with it.

    The config gates need those values, and inventing them could let a draft or a push through a
    gate that skips it. The PR's next eligible event carries them and starts the review.
    """
    logger.info("Skipping automatic review of PR #%s: the queued event predates its draft and label state", pr_number)
    _observe_dispatch("event_state_missing")


def enqueue_authored_pr_review(payload: Mapping[str, object]) -> None:
    review = AuthoredPRReview.from_payload(payload)
    if review is None:
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
        action=review.action,
        base_ref=review.base_ref,
        draft=review.draft,
        labels=list(review.labels),
    )
