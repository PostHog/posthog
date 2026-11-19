import logging
from dataclasses import replace
from datetime import timedelta
from typing import Literal

from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager
from posthog.otel_metrics import OtelInstrumentFactory

from products.review_hog.backend.automatic_review_rules import AutomaticReviewReason, decide_automatic_review
from products.review_hog.backend.models import ReviewReport, ReviewRepository, ReviewUserSettings
from products.review_hog.backend.ownership import RepositoryOwner, RepositoryOwnership, RepositoryRef
from products.review_hog.backend.pr_owner import is_active_member
from products.review_hog.backend.review_request_rules import full_review_published
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH, REVIEW_MODE_FULL
from products.review_hog.backend.reviewer.progress import turn_recorded_in_mode
from products.stamphog.backend.facade.api import check_approval_gates
from products.stamphog.backend.facade.tasks import queue_routing_after_external_review

logger = logging.getLogger(__name__)
_otel = OtelInstrumentFactory("review_hog")

AuthoredPRReviewOutcome = Literal[
    "repository_not_added",
    "installation_mismatch",
    "bot_skipped",
    "bot_no_connector",
    "not_opted_in",
    "full_review_published",
    "follow_up_skipped",
    "draft_skipped",
    "label_skipped",
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


def observe_dispatch(outcome: AuthoredPRReviewOutcome) -> None:
    AUTHORED_PR_REVIEW_TOTAL.labels(outcome=outcome).inc()
    _otel.record_counter_twin(AUTHORED_PR_REVIEW_TOTAL, 1, {"outcome": outcome})


AutomaticReviewModeReason = Literal[
    "switch_off",
    "draft",
    "head_already_reviewed",
    "deep_turn_exists",
    "deep_turn_unknown",
    "gates_unknown",
    "gates_pass",
    "needs_human",
]

# One count per started automatic review. "needs_human" is the only reason for a Deep review, so a rise in
# "gates_unknown" next to a fall in "needs_human" shows that the stamphog gate check stopped answering.
AUTOMATIC_REVIEW_MODE_TOTAL = Counter(
    "posthog_review_hog_automatic_review_mode_total",
    "Review mode of the automatic reviews that started, keyed by mode and the reason for it",
    labelnames=["review_mode", "reason"],
)

# The dispatch runs in a Celery task for every push, so a slow queue answer must not hold it.
_QUEUE_QUERY_TIMEOUT = timedelta(seconds=2)


@frozen
class AutomaticReviewMode:
    review_mode: str
    reason: AutomaticReviewModeReason
    failed_gates: tuple[str, ...] = ()


def observe_review_mode(mode: AutomaticReviewMode) -> None:
    labels = {"review_mode": mode.review_mode, "reason": mode.reason}
    AUTOMATIC_REVIEW_MODE_TOTAL.labels(**labels).inc()
    _otel.record_counter_twin(AUTOMATIC_REVIEW_MODE_TOTAL, 1, labels)


def deep_turn_known(team_id: int, repository: str, pr_number: int, report: ReviewReport | None) -> bool | None:
    """Whether the PR has a Deep turn in any state, or None when the review queue does not answer.

    A turn leaves a marker when it starts, and a turn that failed before its marker leaves a failed outcome
    note. A Deep request that waits in the queue, or runs before it writes its marker, exists only in the
    queue. A waiting automatic request does not count, because the next automatic dispatch replaces it.
    """
    # These clients pull in the sandbox runtime; enqueueing a webhook must not load it.
    from products.review_hog.backend.temporal.client import queued_review_modes  # noqa: PLC0415
    from products.review_hog.backend.temporal.types import review_pr_workflow_id  # noqa: PLC0415

    if report is not None and turn_recorded_in_mode(report.team_id, str(report.id), REVIEW_MODE_FULL):
        return True
    owner, _, repo = repository.partition("/")
    workflow_id = review_pr_workflow_id(team_id=team_id, owner=owner, repo=repo, pr_number=pr_number)
    try:
        queued = queued_review_modes(workflow_id, rpc_timeout=_QUEUE_QUERY_TIMEOUT)
    except Exception:
        logger.warning("Could not read the review queue of %s#%s", repository, pr_number, exc_info=True)
        return None
    return any(request.review_mode == REVIEW_MODE_FULL for request in queued.active) or any(
        request.review_mode == REVIEW_MODE_FULL and not request.automatic for request in queued.pending
    )


def choose_automatic_review_mode(
    *,
    team_id: int,
    repository: str,
    pr_number: int,
    head_sha: str,
    draft: bool,
    row: ReviewRepository | None,
    report: ReviewReport | None,
) -> AutomaticReviewMode:
    """Deep when the repository asks for it and stamphog's gates send the head to a person, otherwise Standard.

    A PR gets one automatic Deep review at most. Every doubt keeps the Standard review: a gate check that
    cannot tell, and a queue that does not say whether a Deep review already waits.
    """
    if row is None or not row.deep_review_gated_prs:
        return AutomaticReviewMode(review_mode=REVIEW_MODE_FLASH, reason="switch_off")
    if draft:
        return AutomaticReviewMode(review_mode=REVIEW_MODE_FLASH, reason="draft")
    # The turn skips a head that already had its automatic review, so the gate check would be wasted.
    if report is not None and report.automatic_reviewed_head_sha == head_sha:
        return AutomaticReviewMode(review_mode=REVIEW_MODE_FLASH, reason="head_already_reviewed")
    known = deep_turn_known(team_id, repository, pr_number, report)
    if known is None:
        return AutomaticReviewMode(review_mode=REVIEW_MODE_FLASH, reason="deep_turn_unknown")
    if known:
        return AutomaticReviewMode(review_mode=REVIEW_MODE_FLASH, reason="deep_turn_exists")
    check = check_approval_gates(team_id=team_id, repository=repository, pr_number=pr_number, head_sha=head_sha)
    if check is None:
        return AutomaticReviewMode(review_mode=REVIEW_MODE_FLASH, reason="gates_unknown")
    if not check.needs_human:
        return AutomaticReviewMode(review_mode=REVIEW_MODE_FLASH, reason="gates_pass")
    return AutomaticReviewMode(review_mode=REVIEW_MODE_FULL, reason="needs_human", failed_gates=check.failed_gates)


def connector_user_id(*, team_id: int, installation_id: str) -> int | None:
    """The active member who connected the installation to the project. Bot pull requests run as them."""
    rows = IntegrationManager.github.oauth.list(team_id, external_id=installation_id)
    for creator_id in (row.created_by_id for row in rows if row.created_by_id is not None):
        if is_active_member(team_id=team_id, user_id=creator_id):
            return creator_id
    return None


@frozen
class AutomaticDispatch:
    outcome: AuthoredPRReviewOutcome
    team_id: int | None = None
    # The user the review runs as: the author, or the connector for a bot pull request.
    run_as_user_id: int | None = None
    gates_need_human: bool = False


def drafts_reviewed(team_id: int, row: ReviewRepository | None, *, author_user_id: int | None) -> bool:
    """Whether a draft gets its automatic review: the repository turned draft reviews on, and the author did not
    turn them off for their own pull requests. A bot or an unmapped author follows the repository."""
    if row is None or not row.review_drafts:
        return False
    if author_user_id is None:
        return True
    return ReviewUserSettings.load_preferences(team_id, author_user_id).review_drafts


def plan_automatic_review(
    repository: RepositoryRef, owner: RepositoryOwner | None, *, author_login: str, draft: bool = False
) -> AutomaticDispatch:
    """Whether a push gets an automatic review, in which project, and as which user. The dispatch picks its mode."""
    # These clients pull in the signals product; planning a webhook must not load it at import.
    from products.signals.backend.facade.report_reviewers import org_user_ids_by_github_login  # noqa: PLC0415

    if owner is None:
        return AutomaticDispatch(outcome="repository_not_added")
    team_id = owner.team_id
    has_integration = IntegrationManager.github.oauth.exists(team_id, external_id=owner.installation_id)
    if not has_integration:
        logger.warning(
            "Team %s has no GitHub integration for installation %s; skipping automatic review of %s",
            team_id,
            owner.installation_id,
            repository.full_name,
        )
        return AutomaticDispatch(outcome="installation_mismatch", team_id=team_id)
    author_id = org_user_ids_by_github_login(team_id=team_id, github_logins=[author_login]).get(
        author_login.strip().lower()
    )
    # An inactive user cannot act: every user-scoped sandbox credential of the run would fail. So an
    # inactive author counts as unmapped, and unmapped authors follow the project's bot rule.
    author_user_id = (
        author_id if author_id is not None and is_active_member(team_id=team_id, user_id=author_id) else None
    )
    decision = decide_automatic_review(
        team_id, repository, owner.row, author_user_id=author_user_id, author_login=author_login
    )
    if not decision.flash:
        outcome: AuthoredPRReviewOutcome = (
            "bot_skipped" if decision.reason == AutomaticReviewReason.BOT_SKIPPED else "not_opted_in"
        )
        return AutomaticDispatch(outcome=outcome, team_id=team_id)
    is_bot = decision.reason == AutomaticReviewReason.BOT_REVIEWED
    # Before the bot branch, so a bot's drafts follow the repository too. A bot's mapped user is not its author.
    if draft and not drafts_reviewed(team_id, owner.row, author_user_id=None if is_bot else author_user_id):
        return AutomaticDispatch(outcome="draft_skipped", team_id=team_id)
    if is_bot:
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
    draft: bool = False,
) -> bool:
    """Whether the rules still give this pull request an automatic review run as `user_id`.

    The workflow calls this again when the run starts, because ownership, settings and lists can
    change while the task waits in the queue. The review mode that the dispatch chose is not checked again.
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
    return plan_automatic_review(ref, owner, author_login=author_login, draft=draft).run_as_user_id == user_id


@frozen
class AuthoredPRReview:
    installation_id: str
    repository: str
    author_login: str
    pr_number: int
    head_sha: str
    github_repo_id: int | None = None
    draft: bool = False
    skip_agent_review: bool = False
    action: str | None = None

    @property
    def ref(self) -> RepositoryRef:
        return RepositoryRef(
            installation_id=self.installation_id, github_repo_id=self.github_repo_id, full_name=self.repository
        )

    @property
    def marks_ready(self) -> bool:
        """The event says the PR is ready for review: it was marked ready, or it opened as a non-draft."""
        return self.action == "ready_for_review" or (self.action == "opened" and not self.draft)

    def _dispatch(self) -> AutomaticDispatch:
        """Start the automatic review if the rules allow it. The outcome tells whether a workflow started."""
        # These clients pull in the sandbox runtime; enqueueing a webhook must not load it.
        from products.review_hog.backend.reviewer.push_gate import SKIP_FOLLOW_UPS  # noqa: PLC0415
        from products.review_hog.backend.temporal.client import start_review_pr_workflow  # noqa: PLC0415
        from products.review_hog.backend.temporal.types import TRIGGER_AUTOMATIC  # noqa: PLC0415

        # Only a ready head is reported to stamphog, which needs the project even when no review starts.
        owner = None
        if self.marks_ready or not self.skip_agent_review:
            owner = RepositoryOwnership.find(self.ref, backfill=True)
        if self.skip_agent_review:
            observe_dispatch("label_skipped")
            return AutomaticDispatch(outcome="label_skipped", team_id=None if owner is None else owner.team_id)
        dispatch = plan_automatic_review(self.ref, owner, author_login=self.author_login, draft=self.draft)
        if dispatch.team_id is None or dispatch.run_as_user_id is None:
            # Most pushes get no automatic review, so the counter carries the signal and the logs
            # stay quiet.
            observe_dispatch(dispatch.outcome)
            return dispatch
        report = (
            ReviewReport.objects.for_team(dispatch.team_id)
            .filter(repository__iexact=self.repository, pr_number=self.pr_number)
            .first()
        )
        if full_review_published(report):
            observe_dispatch("full_review_published")
            return AutomaticDispatch(outcome="full_review_published", team_id=dispatch.team_id)
        # One automatic review per PR: a person or an agent asks for the next one. The push gate skips
        # the pushes queued while the first review runs.
        if SKIP_FOLLOW_UPS and report is not None and report.automatic_reviewed_head_sha is not None:
            observe_dispatch("follow_up_skipped")
            return AutomaticDispatch(outcome="follow_up_skipped", team_id=dispatch.team_id)
        mode = choose_automatic_review_mode(
            team_id=dispatch.team_id,
            repository=self.repository,
            pr_number=self.pr_number,
            head_sha=self.head_sha,
            draft=self.draft,
            row=None if owner is None else owner.row,
            report=report,
        )
        if mode.reason not in ("switch_off", "draft"):
            logger.info(
                "Automatic review of %s#%s at %s runs as %s (%s, failed gates: %s)",
                self.repository,
                self.pr_number,
                self.head_sha[:12],
                mode.review_mode,
                mode.reason,
                ", ".join(mode.failed_gates) or "none",
            )
        start_review_pr_workflow(
            pr_url=f"https://github.com/{self.repository}/pull/{self.pr_number}",
            team_id=dispatch.team_id,
            user_id=dispatch.run_as_user_id,
            acting_user_id=dispatch.run_as_user_id,
            publish=True,
            # A Deep review chains into resolution unless this is False, and an automatic review never writes code.
            resolve_comments=False,
            review_mode=mode.review_mode,
            trigger_source=TRIGGER_AUTOMATIC,
            requested_head_sha=self.head_sha,
            trigger_action=self.action,
            marks_ready=self.marks_ready,
            installation_id=self.installation_id,
            github_repo_id=self.github_repo_id,
        )
        # After the start, so a retried task cannot count a dispatch it never made.
        observe_dispatch("started")
        observe_review_mode(mode)
        return replace(dispatch, gates_need_human=mode.reason == "needs_human")

    def start(self) -> None:
        dispatch = self._dispatch()
        if dispatch.team_id is None or not self.marks_ready:
            return
        if dispatch.outcome == "started" and not dispatch.gates_need_human:
            return
        # Stamphog waits for a report on a ready head before it routes reviewers. No turn reviews this head, or a Deep
        # turn does, which never starts a silent stamphog review and can outlast stamphog's routing safety net.
        queue_routing_after_external_review(
            team_id=dispatch.team_id, repository=self.repository, pr_number=self.pr_number, head_sha=self.head_sha
        )
