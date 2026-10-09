import logging
from collections.abc import Mapping
from typing import Literal

from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.otel_metrics import OtelInstrumentFactory

from products.review_hog.backend.automatic_review_rules import AutomaticReviewReason, decide_automatic_review
from products.review_hog.backend.ownership import (
    OwnedRepositoryPrefilter,
    RepositoryOwner,
    RepositoryOwnership,
    RepositoryRef,
)

logger = logging.getLogger(__name__)
_otel = OtelInstrumentFactory("review_hog")

AuthoredPRReviewOutcome = Literal[
    "repository_not_added",
    "installation_mismatch",
    "bot_skipped",
    "bot_no_connector",
    "not_opted_in",
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


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def is_active_member(*, team_id: int, user_id: int) -> bool:
    return OrganizationMembership.objects.filter(
        organization__team__id=team_id, user_id=user_id, user__is_active=True
    ).exists()


def connector_user_id(*, team_id: int, installation_id: str) -> int | None:
    """The active member who connected the installation to the project. Bot pull requests run as them."""
    creator_ids = Integration.objects.filter(
        team_id=team_id, kind="github", integration_id=installation_id, created_by__isnull=False
    ).values_list("created_by_id", flat=True)
    for creator_id in creator_ids:
        if is_active_member(team_id=team_id, user_id=creator_id):
            return creator_id
    return None


@frozen
class AutomaticDispatch:
    outcome: AuthoredPRReviewOutcome
    team_id: int | None = None
    # The user the review runs as: the author, or the connector for a bot pull request.
    run_as_user_id: int | None = None


def plan_automatic_review(
    repository: RepositoryRef, owner: RepositoryOwner | None, *, author_login: str
) -> AutomaticDispatch:
    """Whether a push gets an automatic Flash review, in which project, and as which user."""
    # These clients pull in the signals product; planning a webhook must not load it at import.
    from products.signals.backend.report_generation.resolve_reviewers import (  # noqa: PLC0415
        resolve_org_github_login_to_users,
    )

    if owner is None:
        return AutomaticDispatch(outcome="repository_not_added")
    team_id = owner.team_id
    has_integration = Integration.objects.filter(
        team_id=team_id, kind="github", integration_id=owner.installation_id
    ).exists()
    if not has_integration:
        logger.warning(
            "Team %s has no GitHub integration for installation %s; skipping automatic review of %s",
            team_id,
            owner.installation_id,
            repository.full_name,
        )
        return AutomaticDispatch(outcome="installation_mismatch", team_id=team_id)
    author = resolve_org_github_login_to_users(team_id, [author_login]).get(author_login.strip().lower())
    # An inactive user cannot act: every user-scoped sandbox credential of the run would fail. So an
    # inactive author counts as unmapped, and unmapped authors follow the project's bot rule.
    author_user_id = author.id if author is not None and is_active_member(team_id=team_id, user_id=author.id) else None
    decision = decide_automatic_review(
        team_id, repository, owner.row, author_user_id=author_user_id, author_login=author_login
    )
    if not decision.flash:
        outcome: AuthoredPRReviewOutcome = (
            "bot_skipped" if decision.reason == AutomaticReviewReason.BOT_SKIPPED else "not_opted_in"
        )
        return AutomaticDispatch(outcome=outcome, team_id=team_id)
    if decision.reason == AutomaticReviewReason.BOT_REVIEWED:
        run_as_user_id = connector_user_id(team_id=team_id, installation_id=owner.installation_id)
        if run_as_user_id is None:
            return AutomaticDispatch(outcome="bot_no_connector", team_id=team_id)
        return AutomaticDispatch(outcome="started", team_id=team_id, run_as_user_id=run_as_user_id)
    return AutomaticDispatch(outcome="started", team_id=team_id, run_as_user_id=author_user_id)


def automatic_flash_allowed(*, team_id: int, repository: str, user_id: int, author_login: str) -> bool:
    """Whether the rules still give this pull request an automatic Flash review run as `user_id`.

    The workflow calls this again when the run starts, because ownership, settings and lists can
    change while the task waits in the queue.
    """
    owner = RepositoryOwnership.find_by_name(repository)
    if owner is None or owner.team_id != team_id:
        return False
    ref = RepositoryRef(installation_id=owner.installation_id, github_repo_id=None, full_name=repository)
    return plan_automatic_review(ref, owner, author_login=author_login).run_as_user_id == user_id


@frozen
class AuthoredPRReview:
    installation_id: str
    repository: str
    author_login: str
    pr_number: int
    head_sha: str
    github_repo_id: int | None = None

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

        installation_id = _positive_int(_mapping(payload.get("installation")).get("id"))
        author_login = _mapping(pull_request.get("user")).get("login")
        pr_number = _positive_int(pull_request.get("number"))
        head_sha = head.get("sha")
        if (
            installation_id is None
            or pr_number is None
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
            github_repo_id=_positive_int(_mapping(payload.get("repository")).get("id")),
        )

    @property
    def ref(self) -> RepositoryRef:
        return RepositoryRef(
            installation_id=self.installation_id, github_repo_id=self.github_repo_id, full_name=self.repository
        )

    def start(self) -> None:
        # These clients pull in the sandbox runtime; enqueueing a webhook must not load it.
        from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH  # noqa: PLC0415
        from products.review_hog.backend.temporal.client import start_review_pr_workflow  # noqa: PLC0415
        from products.review_hog.backend.temporal.types import TRIGGER_AUTOMATIC  # noqa: PLC0415

        dispatch = plan_automatic_review(
            self.ref, RepositoryOwnership.find(self.ref, backfill=True), author_login=self.author_login
        )
        if dispatch.team_id is None or dispatch.run_as_user_id is None:
            # Most pushes get no automatic review, so the counter carries the signal and the logs
            # stay quiet.
            _observe_dispatch(dispatch.outcome)
            return
        start_review_pr_workflow(
            pr_url=f"https://github.com/{self.repository}/pull/{self.pr_number}",
            team_id=dispatch.team_id,
            user_id=dispatch.run_as_user_id,
            acting_user_id=dispatch.run_as_user_id,
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
    if review is None or not OwnedRepositoryPrefilter.may_be_owned(review.ref):
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
        github_repo_id=review.github_repo_id,
    )
