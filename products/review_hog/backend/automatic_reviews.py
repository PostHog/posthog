import logging
from typing import Literal

from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.otel_metrics import OtelInstrumentFactory

from products.review_hog.backend.automatic_review_rules import AutomaticReviewReason, decide_automatic_review
from products.review_hog.backend.internal_features import has_internal_features
from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.ownership import RepositoryOwner, RepositoryOwnership, RepositoryRef
from products.review_hog.backend.pr_owner import is_active_member
from products.review_hog.backend.review_request_rules import full_review_published

logger = logging.getLogger(__name__)
_otel = OtelInstrumentFactory("review_hog")

AuthoredPRReviewOutcome = Literal[
    "repository_not_added",
    "internal_features_off",
    "installation_mismatch",
    "bot_skipped",
    "bot_no_connector",
    "not_opted_in",
    "full_review_published",
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
    if not has_internal_features(team_id):
        return AutomaticDispatch(outcome="internal_features_off", team_id=team_id)
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


def automatic_flash_allowed(
    *,
    team_id: int,
    repository: str,
    user_id: int,
    author_login: str,
    installation_id: str | None = None,
    github_repo_id: int | None = None,
) -> bool:
    """Whether the rules still give this pull request an automatic Flash review run as `user_id`.

    The workflow calls this again when the run starts, because ownership, settings and lists can
    change while the task waits in the queue.
    """
    if installation_id:
        # The installation id comes from the signed webhook. The cached account name of the
        # integration can be a placeholder, so a lookup by name can miss an owner the dispatch found.
        owner = RepositoryOwnership.find(
            RepositoryRef(installation_id=installation_id, github_repo_id=github_repo_id, full_name=repository)
        )
    else:
        owner = RepositoryOwnership.find_by_name(repository)
    if owner is None or owner.team_id != team_id:
        return False
    ref = RepositoryRef(installation_id=owner.installation_id, github_repo_id=github_repo_id, full_name=repository)
    return plan_automatic_review(ref, owner, author_login=author_login).run_as_user_id == user_id


@frozen
class AuthoredPRReview:
    installation_id: str
    repository: str
    author_login: str
    pr_number: int
    head_sha: str
    github_repo_id: int | None = None

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
        report = (
            ReviewReport.objects.for_team(dispatch.team_id)
            .filter(repository__iexact=self.repository, pr_number=self.pr_number)
            .first()
        )
        if full_review_published(report):
            _observe_dispatch("full_review_published")
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
            installation_id=self.installation_id,
            github_repo_id=self.github_repo_id,
        )
        # After the start, so a retried task cannot count a dispatch it never made.
        _observe_dispatch("started")
