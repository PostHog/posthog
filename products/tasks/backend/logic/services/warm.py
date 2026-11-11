"""Generic sandbox warming for products/tasks.

Warming eagerly boots a sandbox + ACP session on an interactive Run that idles
awaiting the first ``user_message``, so first-token latency drops from a cold boot
to roughly model-invocation time. The mechanic plus its guardrails — a per-product
quota gate and a warm-pool concurrency cap — live here so every product warms through
one implementation rather than reimplementing provisioning, quota, and idempotency.

The trigger (when to warm) and Task ownership (birth + linking to the product's own
entity) stay per-product: ``SandboxWarmer`` operates on an *existing* Task behind the
warming facade. The registries below are fail-closed, so a product must opt in with a
quota gate before it can warm.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog
from rest_framework.exceptions import PermissionDenied, Throttled

from posthog.dataclasses import frozen
from posthog.exceptions import QuotaLimitExceeded
from posthog.models.team import Team
from posthog.models.user import User
from posthog.scopes import scopes_not_covered
from posthog.temporal.oauth import resolve_scopes

from products.tasks.backend.access import get_posthog_ai_access_decision
from products.tasks.backend.facade.profiles import TaskProfile, WarmQuota
from products.tasks.backend.logic.services.compute_quota import organization_deactivated
from products.tasks.backend.logic.services.workflow_dispatch import (
    WorkflowDispatchOptions,
    build_create_payload,
    enqueue_or_start_workflow,
)
from products.tasks.backend.metrics import observe_warm_churn_throttled
from products.tasks.backend.models import SandboxSession, Task, TaskRun
from products.tasks.backend.temporal.client import execute_task_processing_workflow
from products.tasks.backend.temporal.oauth import dispatched_run_scopes
from products.tasks.backend.temporal.process_task.utils import parse_run_state

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

if TYPE_CHECKING:
    from posthog.temporal.oauth import PosthogMcpScopes

logger = structlog.get_logger(__name__)


@dataclass
class WarmResult:
    """Outcome of a warm request — the Run to open against, and whether it was just provisioned."""

    run: TaskRun
    just_created: bool


class WarmSourceChanged(Exception):
    pass


@dataclass(frozen=True)
class WarmPoolCaps:
    per_user: int
    per_org: int


@frozen
class ActiveSessionCaps:
    per_user: int
    per_org: int


ActiveSessionCapScope = Literal["user", "org", "task"]

# Client-selectable origins share one cap bucket, so picking a different origin per task gives no fresh allowance.
_CLIENT_ORIGIN_PRODUCTS: frozenset[str] = (
    frozenset(Task.OriginProduct.values)
    - Task.SERVER_ONLY_ORIGIN_PRODUCTS
    - {Task.OriginProduct.POSTHOG_AI, Task.OriginProduct.SIGNAL_REPORT}
)
_CLIENT_ORIGIN_SESSIONS = Q(origin_product__in=_CLIENT_ORIGIN_PRODUCTS) | Q(
    origin_product=Task.OriginProduct.SIGNAL_REPORT, task_run__task__signal_report_id__isnull=True
)


def _session_bucket(origin_product: str, signal_report_id: UUID | str | None) -> Q:
    if origin_product in _CLIENT_ORIGIN_PRODUCTS:
        return _CLIENT_ORIGIN_SESSIONS
    if origin_product == Task.OriginProduct.SIGNAL_REPORT:
        if signal_report_id is None:
            return _CLIENT_ORIGIN_SESSIONS
        return Q(origin_product=origin_product, task_run__task__signal_report_id__isnull=False)
    return Q(origin_product=origin_product)


def _ai_credits_checker(team: Team, user: User) -> None:
    if is_team_limited(team.api_token, QuotaResource.AI_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY):
        raise QuotaLimitExceeded(
            "Your organization reached its AI credit usage limit. Increase the limits in Billing settings, "
            "or ask an org admin to do so."
        )


def _posthog_ai_checker(team: Team, user: User) -> None:
    if not get_posthog_ai_access_decision(user, team.organization).allowed:
        raise PermissionDenied("Warming is not enabled for this user.")
    _ai_credits_checker(team, user)


_CHECKERS_BY_WARM_QUOTA: dict[WarmQuota, Callable[[Team, User], None] | None] = {
    WarmQuota.AI_CREDITS: _ai_credits_checker,
    WarmQuota.POSTHOG_AI: _posthog_ai_checker,
    WarmQuota.NONE: None,
}


class SandboxWarmer:
    """Idempotently warm a sandbox Run for an existing Task, enforcing the product's quota gate and a
    state-derived warm-pool cap, then dispatching the processing workflow after commit.

    The quota gate and cap are also exposed as classmethods (keyed on team/user, not a Task) so a
    caller can gate *before* it births a Task — an over-quota or over-cap warm must not leave behind a
    runless Task the next message can't continue.
    """

    # A warm Run is non-terminal and idling; these are the statuses it can hold before activation.
    _NON_TERMINAL_STATUSES: frozenset[str] = frozenset({TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS})
    # A run's status is client-writable, so a live box counts until its run is terminal, not only while it runs.
    _LIVE_RUN_STATUSES: frozenset[str] = _NON_TERMINAL_STATUSES | {TaskRun.Status.NOT_STARTED}

    # Maps an origin product to its pre-warm quota gate. A checker returns None or raises a DRF
    # APIException (the in-process caller can't return an HTTP Response, so the contract is exception-
    # based and DRF renders the status from any depth). ``None`` means the origin may warm with no
    # billing quota — gated only by enablement + the warm-pool caps (e.g. USER_CREATED, the Code-app
    # origin: gated by the ``tasks-prewarm-sandbox`` flag at the endpoint, not an AI-credit budget).
    # Fail-closed: an origin absent from this registry cannot warm at all.
    ORIGIN_PRODUCT_QUOTA: dict[str, Callable[[Team, User], None] | None] = {
        Task.OriginProduct.POSTHOG_AI: _posthog_ai_checker,
        Task.OriginProduct.USER_CREATED: None,
        Task.OriginProduct.SIGNAL_REPORT: _ai_credits_checker,
    }

    ORIGIN_PRODUCT_CAPS: dict[str, WarmPoolCaps] = {
        Task.OriginProduct.POSTHOG_AI: WarmPoolCaps(per_user=2, per_org=10),
        Task.OriginProduct.USER_CREATED: WarmPoolCaps(per_user=10, per_org=100),
        Task.OriginProduct.SIGNAL_REPORT: WarmPoolCaps(per_user=10, per_org=100),
    }
    _DEFAULT_CAPS: WarmPoolCaps = WarmPoolCaps(per_user=2, per_org=10)

    ORIGIN_ACTIVE_SESSION_CAPS: dict[str, ActiveSessionCaps] = {
        Task.OriginProduct.POSTHOG_AI: ActiveSessionCaps(per_user=6, per_org=30),
        Task.OriginProduct.USER_CREATED: ActiveSessionCaps(per_user=10, per_org=100),
    }

    WARM_CHURN_LIMIT_PER_HOUR: int = 5

    def __init__(self, task: "Task", *, user: User) -> None:
        self.task = task
        self.user = user

    @classmethod
    def enforce_quota(cls, origin_product: str, team: Team, user: User, *, profile: TaskProfile | None = None) -> None:
        """Raise if ``team`` may not warm a Run for ``origin_product`` (over quota, or origin not registered).

        Fail-closed: an origin absent from the registry is denied. A registered origin whose gate is
        ``None`` is allowed with no billing quota (enablement + caps gate it elsewhere). A profile
        answers from its warm policy instead of the origin registry.
        """
        if profile is not None:
            if profile.warm is None:
                raise PermissionDenied(f"Warming is not enabled for origin product '{origin_product}'.")
            checker = _CHECKERS_BY_WARM_QUOTA[profile.warm.quota]
        else:
            if origin_product not in cls.ORIGIN_PRODUCT_QUOTA:
                raise PermissionDenied(f"Warming is not enabled for origin product '{origin_product}'.")
            checker = cls.ORIGIN_PRODUCT_QUOTA[origin_product]
        if organization_deactivated(team.id):
            raise PermissionDenied("Your organization has been deactivated.")
        if checker is not None:
            checker(team, user)

    @classmethod
    def at_capacity(cls, origin_product: str, team: Team, user: User, *, profile: TaskProfile | None = None) -> bool:
        """True if the user or org already holds the max concurrent *warm* Runs.

        Counts only Runs still awaiting their first message (``state.await_user_message`` set) — so the
        warm-pool budget and the active (AI-credit) budget are disjoint: activating a warm Run clears the
        flag and drops it from this count for free, and a terminal Run drops via the status filter. No
        increment/decrement counter is kept; the count is derived from state. The cross-task count is not
        serialized by the per-Task lock, so it may overshoot slightly under heavy concurrency — acceptable
        for a best-effort resource guard.
        """
        if profile is not None and profile.warm is not None:
            caps = WarmPoolCaps(per_user=profile.warm.per_user_cap, per_org=profile.warm.per_org_cap)
        else:
            caps = cls.ORIGIN_PRODUCT_CAPS.get(origin_product, cls._DEFAULT_CAPS)
        # `await_user_message` is stored literally (the field is alias-free in PostHogAIRunState); see the
        # comment there before adding an alias, which would silently break this filter and open the cap.
        warm_runs = TaskRun.objects.filter(
            origin_product=origin_product,
            status__in=cls._NON_TERMINAL_STATUSES,
            state__await_user_message=True,
        ).exclude(task__deleted=True)

        if warm_runs.filter(task__created_by_id=user.pk).count() >= caps.per_user:
            return True
        return warm_runs.filter(team__organization_id=team.organization_id).count() >= caps.per_org

    @classmethod
    def _active_session_caps(cls, origin_product: str, signal_report_id: UUID | str | None) -> ActiveSessionCaps | None:
        # Server-only, but a member starts these from a page, one sandbox per flag, so they are capped like
        # PostHog AI runs.
        if origin_product == Task.OriginProduct.FEATURE_FLAGS:
            return cls.ORIGIN_ACTIVE_SESSION_CAPS[Task.OriginProduct.POSTHOG_AI]
        if origin_product in Task.SERVER_ONLY_ORIGIN_PRODUCTS:
            return None
        # A report-linked task, from the signals batch or a person starting work on a report, is bounded
        # per report by the signals task cap and to one live sandbox per task instead; a batch fans out
        # several tasks from one creator by design. A bare signal_report origin has no report to bound
        # it, so it falls in the client bucket.
        if origin_product == Task.OriginProduct.SIGNAL_REPORT and signal_report_id is not None:
            return None
        if origin_product == Task.OriginProduct.POSTHOG_AI:
            return cls.ORIGIN_ACTIVE_SESSION_CAPS[Task.OriginProduct.POSTHOG_AI]
        return cls.ORIGIN_ACTIVE_SESSION_CAPS[Task.OriginProduct.USER_CREATED]

    @classmethod
    def _live_attributed_sessions(
        cls, origin_product: str, signal_report_id: UUID | str | None, exclude_run_id: str | UUID | None
    ) -> QuerySet[SandboxSession]:
        open_sessions = (
            SandboxSession.objects.unscoped()
            .filter(
                _session_bucket(origin_product, signal_report_id),
                ended_at__isnull=True,
                user_attributed_at__isnull=False,
            )
            .filter(
                # The provider kills a Modal box at its TTL even when the close stamp never lands, so a
                # stale row must not lock anyone out. Hogland's TTL is an idle timeout that proxied
                # requests extend without touching the row, so a hogland row counts while its run is live.
                Q(ttl_expires_at__gt=timezone.now()) | Q(sandbox_backend="hogland"),
                task_run__status__in=cls._LIVE_RUN_STATUSES,
            )
        )
        if exclude_run_id is not None:
            open_sessions = open_sessions.exclude(
                task_run_id=exclude_run_id if isinstance(exclude_run_id, UUID) else UUID(exclude_run_id)
            )
        return open_sessions

    @classmethod
    def active_session_cap_hit(
        cls,
        origin_product: str,
        *,
        organization_id: UUID | str,
        created_by_id: int | None,
        exclude_run_id: str | UUID | None = None,
        signal_report_id: UUID | str | None = None,
        task_id: str | UUID | None = None,
    ) -> ActiveSessionCapScope | None:
        caps = cls._active_session_caps(origin_product, signal_report_id)
        if caps is None:
            report_linked = origin_product == Task.OriginProduct.SIGNAL_REPORT and signal_report_id is not None
            if not report_linked or task_id is None:
                return None
            # The per-report task cap bounds how many report tasks exist; this bounds the runs a caller
            # can stack on one of them, since a run endpoint call on a discussion task is unlimited.
            own_sessions = cls._live_attributed_sessions(origin_product, signal_report_id, exclude_run_id)
            return "task" if own_sessions.filter(task_run__task_id=task_id).exists() else None
        open_sessions = cls._live_attributed_sessions(origin_product, signal_report_id, exclude_run_id)
        if (
            created_by_id is not None
            and open_sessions.filter(task_run__task__created_by_id=created_by_id).count() >= caps.per_user
        ):
            return "user"
        if open_sessions.filter(team__organization_id=organization_id).count() >= caps.per_org:
            return "org"
        return None

    @classmethod
    def active_session_cap_detail(
        cls, origin_product: str, scope: ActiveSessionCapScope, *, signal_report_id: UUID | str | None = None
    ) -> str:
        if scope == "task":
            return (
                "This report task already has a cloud sandbox running. "
                "Wait for it to finish or stop it, then try again."
            )
        caps = cls._active_session_caps(origin_product, signal_report_id)
        if caps is None:
            raise ValueError(f"origin_product '{origin_product}' has no active-session cap")
        if scope == "user":
            return (
                f"You already have {caps.per_user} cloud sandboxes running. "
                "Wait for one to finish or stop one, then try again."
            )
        return (
            f"Your organization already has {caps.per_org} cloud sandboxes running. "
            "Wait for one to finish or stop one, then try again."
        )

    def _warm_churn_exceeded(self) -> bool:
        return (
            SandboxSession.objects.unscoped()
            .filter(
                _session_bucket(self.task.origin_product, self.task.signal_report_id),
                task_run__task__created_by_id=self.user.pk,
                prewarmed=True,
                user_attributed_at__isnull=True,
                ended_at__isnull=False,
                ended_at__gte=timezone.now() - timedelta(hours=1),
            )
            .count()
            >= self.WARM_CHURN_LIMIT_PER_HOUR
        )

    def warm(
        self,
        *,
        mode: str = "interactive",
        extra_state: dict[str, Any] | None = None,
        create_pr: bool = False,
        expected_resume_from_run_id: str | UUID | None = None,
        required_existing_state: dict[str, Any] | None = None,
        posthog_mcp_scopes: "PosthogMcpScopes | None" = None,
    ) -> WarmResult:
        """Idempotently ensure the Task has a warm Run, then dispatch the processing workflow after commit.

        - Idempotent: if the Task already has a non-terminal Run, return it without provisioning.
        - Fresh: a Task with no Runs gets a new warm Run; a Task whose latest Run is terminal gets a
          successor that resumes from it (snapshot reuse via ``snapshot_external_id``).
        - ``extra_state`` carries product-specific Run state the generic warmer can't know (e.g. PostHog
          AI's ``systemPrompt``, or a target ``branch``); it is merged into the warm Run's initial state.
        - ``create_pr`` is forwarded to the processing workflow; it defaults to ``False`` (PostHog AI warm
          runs don't open PRs). The Code-app caller passes ``True`` so the activated run opens a PR.

        Raises ``QuotaLimitExceeded`` (402) / ``PermissionDenied`` (403) when gated, and ``Throttled``
        (429) when the warm pool is full or the user ended too many unclaimed warm sandboxes in the last hour.
        """
        # Quota is a gateway/cache call — check it before taking the row lock, never while holding it.
        origin_product = self.task.origin_product
        profile = self.task.stored_profile
        team = self.task.team
        self.enforce_quota(origin_product, team, self.user, profile=profile)
        churned = self._warm_churn_exceeded()
        pool_full = self.at_capacity(origin_product, team, self.user, profile=profile)

        from products.signals.backend.facade.trial import prepare_task_trial  # noqa: PLC0415 -- Signals imports Tasks

        trial_admission = prepare_task_trial(
            team=team,
            origin=origin_product,
            report_id=self.task.signal_report_source_id,
            mode=mode if self.task.uses_self_driving_billing(mode) else "interactive",
        )
        new_run: TaskRun
        with transaction.atomic():
            if trial_admission is not None:
                trial_admission.lock_report(self.task.signal_report_source_id)
            locked = Task.objects.select_for_update().get(id=self.task.id)
            existing = locked.latest_run
            locked_profile = locked.stored_profile
            scope_ceiling = locked_profile.mcp_scopes if locked_profile is not None else "full"
            scopes = posthog_mcp_scopes
            if scopes is None:
                scopes = dispatched_run_scopes(locked, existing.state) if existing is not None else scope_ceiling
            if scopes_not_covered(resolve_scopes(scope_ceiling), resolve_scopes(scopes)):
                raise PermissionDenied("Warm run scopes exceed the task profile's permissions.")
            if existing is not None and not existing.is_terminal:
                if dispatched_run_scopes(locked, existing.state) != scopes:
                    raise WarmSourceChanged
                if expected_resume_from_run_id is not None:
                    existing_state = existing.state or {}
                    expected_resume_id = str(expected_resume_from_run_id)
                    matches_resume_source = (
                        existing_state.get("await_user_message") is True
                        and existing_state.get("resume_from_run_id") == expected_resume_id
                    )
                    matches_required_state = all(
                        existing_state.get(key) == value for key, value in (required_existing_state or {}).items()
                    )
                    if not matches_resume_source or not matches_required_state:
                        raise WarmSourceChanged
                # A warm Run already idling, or an active Run in progress — either way, no double-provision.
                return WarmResult(run=existing, just_created=False)

            # The Run the successor resumes from. Normally the latest Run is the source itself, but a
            # successor the composer already handed back is terminal and sits in front of it — resume
            # from the source the caller named rather than from that dead successor, whose own
            # `resume_from_run_id` would otherwise be lost and leave the new warm unrecognizable as a
            # successor of the source.
            resume_source = existing
            if expected_resume_from_run_id is not None:
                if existing is None:
                    raise WarmSourceChanged
                if str(existing.id) != str(expected_resume_from_run_id):
                    existing_state = existing.state or {}
                    released_successor = (
                        existing_state.get("prewarmed") is True
                        and existing_state.get("await_user_message") is True
                        and existing_state.get("resume_from_run_id") == str(expected_resume_from_run_id)
                    )
                    if not released_successor:
                        raise WarmSourceChanged
                    resume_source = locked.runs.filter(id=expected_resume_from_run_id).first()
                    if resume_source is None:
                        raise WarmSourceChanged

            if resume_source is not None:
                resume_scopes = dispatched_run_scopes(locked, resume_source.state)
                if posthog_mcp_scopes is not None and scopes != resume_scopes:
                    raise WarmSourceChanged
                if scopes_not_covered(resolve_scopes(scope_ceiling), resolve_scopes(resume_scopes)):
                    raise WarmSourceChanged
                scopes = resume_scopes

            if pool_full:
                raise Throttled(detail="Warm-pool capacity reached. Release an idle warm session and try again.")
            if churned:
                observe_warm_churn_throttled(origin_product)
                raise Throttled(detail="Too many unused warm sandboxes in the last hour. Try again later.")

            run_state: dict[str, Any] = {
                "await_user_message": True,
                "prewarmed": True,
                "initial_permission_mode": "default",
                **(extra_state or {}),
            }
            if resume_source is not None:
                # Latest Run is terminal — resume into a successor so the warm session reuses its filesystem.
                run_state["resume_from_run_id"] = str(resume_source.id)
                run_state.update(parse_run_state(resume_source.state).resume_snapshot_carry_state())

            dispatch_options = WorkflowDispatchOptions(
                user_id=self.user.pk,
                create_pr=create_pr,
                posthog_mcp_scopes=scopes,
                prewarmed=True,
            )
            run_state["pending_dispatch"] = build_create_payload(dispatch_options)
            new_run = locked.create_run(
                mode=mode, extra_state=run_state, branch=run_state.get("branch"), _trial_admission=trial_admission
            )

            # Dispatch only after the row commits, so a rollback can't leave an orphaned sandbox.
            enqueue_or_start_workflow(
                new_run,
                start_workflow=execute_task_processing_workflow,
                options=dispatch_options,
            )

        logger.info(
            "sandbox_warm_run_provisioned",
            task_id=str(self.task.id),
            run_id=str(new_run.id),
            origin_product=self.task.origin_product,
        )
        return WarmResult(run=new_run, just_created=True)
