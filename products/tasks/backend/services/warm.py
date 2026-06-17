"""Generic sandbox warming for products/tasks.

Warming eagerly boots a sandbox + ACP session on an interactive Run that idles
awaiting the first ``user_message``, so first-token latency drops from a cold boot
to roughly model-invocation time. The mechanic plus its guardrails — a per-product
quota gate and a warm-pool concurrency cap — live here so every product warms through
one implementation rather than reimplementing provisioning, quota, and idempotency.

The trigger (when to warm) and Task ownership (birth + linking to the product's own
entity) stay per-product: ``SandboxWarmer`` operates on an *existing* Task. PostHog AI's
prewarm is the only caller today; the registries below are fail-closed, so a product
must opt in with a quota gate before it can warm.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.db import transaction

import structlog
from rest_framework.exceptions import PermissionDenied, Throttled

from posthog.exceptions import QuotaLimitExceeded
from posthog.models.team import Team
from posthog.models.user import User

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.client import execute_task_processing_workflow

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

logger = structlog.get_logger(__name__)


@dataclass
class WarmResult:
    """Outcome of a warm request — the Run to open against, and whether it was just provisioned."""

    run: TaskRun
    just_created: bool


@dataclass(frozen=True)
class WarmPoolCaps:
    per_user: int
    per_org: int


def _ai_credits_checker(team: Team, user: User) -> None:
    if is_team_limited(team.api_token, QuotaResource.AI_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY):
        raise QuotaLimitExceeded(
            "Your organization reached its AI credit usage limit. Increase the limits in Billing settings, "
            "or ask an org admin to do so."
        )


class SandboxWarmer:
    """Idempotently warm a sandbox Run for an existing Task, enforcing the product's quota gate and a
    state-derived warm-pool cap, then dispatching the processing workflow after commit.

    The quota gate and cap are also exposed as classmethods (keyed on team/user, not a Task) so a
    caller can gate *before* it births a Task — an over-quota or over-cap warm must not leave behind a
    runless Task the next message can't continue.
    """

    # A warm Run is non-terminal and idling; these are the statuses it can hold before activation.
    _NON_TERMINAL_STATUSES: frozenset[str] = frozenset({TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS})

    # Each checker returns None or raises a DRF APIException; the in-process caller can't return an HTTP
    # Response, so the contract is exception-based and DRF renders the status from any depth. Fail-closed:
    # a product warms only once it registers a gate here, else it would provision sandboxes with no ceiling.
    ORIGIN_PRODUCT_QUOTA: dict["Task.OriginProduct", Callable[[Team, User], None]] = {
        Task.OriginProduct.POSTHOG_AI: _ai_credits_checker,
    }

    ORIGIN_PRODUCT_CAPS: dict["Task.OriginProduct", WarmPoolCaps] = {
        Task.OriginProduct.POSTHOG_AI: WarmPoolCaps(per_user=2, per_org=10),
    }
    _DEFAULT_CAPS: WarmPoolCaps = WarmPoolCaps(per_user=2, per_org=10)

    def __init__(self, task: "Task", *, user: User) -> None:
        self.task = task
        self.user = user

    @classmethod
    def enforce_quota(cls, origin_product: "Task.OriginProduct", team: Team, user: User) -> None:
        """Raise if ``team`` may not warm a Run for ``origin_product`` (over quota, or product not registered)."""
        checker = cls.ORIGIN_PRODUCT_QUOTA.get(origin_product)
        if checker is None:
            raise PermissionDenied(f"Warming is not enabled for origin product '{origin_product}'.")
        checker(team, user)

    @classmethod
    def at_capacity(cls, origin_product: "Task.OriginProduct", team: Team, user: User) -> bool:
        """True if the user or org already holds the max concurrent *warm* Runs.

        Counts only Runs still awaiting their first message (``state.await_user_message`` set) — so the
        warm-pool budget and the active (AI-credit) budget are disjoint: activating a warm Run clears the
        flag and drops it from this count for free, and a terminal Run drops via the status filter. No
        increment/decrement counter is kept; the count is derived from state. The cross-task count is not
        serialized by the per-Task lock, so it may overshoot slightly under heavy concurrency — acceptable
        for a best-effort resource guard.
        """
        caps = cls.ORIGIN_PRODUCT_CAPS.get(origin_product, cls._DEFAULT_CAPS)
        # `await_user_message` is stored literally (the field is alias-free in PostHogAIRunState); see the
        # comment there before adding an alias, which would silently break this filter and open the cap.
        warm_runs = TaskRun.objects.filter(
            task__origin_product=origin_product,
            status__in=cls._NON_TERMINAL_STATUSES,
            state__await_user_message=True,
        ).exclude(task__deleted=True)

        if warm_runs.filter(task__created_by_id=user.pk).count() >= caps.per_user:
            return True
        return warm_runs.filter(task__team__organization_id=team.organization_id).count() >= caps.per_org

    def warm(self, *, mode: str = "interactive", extra_state: dict[str, Any] | None = None) -> WarmResult:
        """Idempotently ensure the Task has a warm Run, then dispatch the processing workflow after commit.

        - Idempotent: if the Task already has a non-terminal Run, return it without provisioning.
        - Fresh: a Task with no Runs gets a new warm Run; a Task whose latest Run is terminal gets a
          successor that resumes from it (filesystem reuse via ``snapshot_external_id``).
        - ``extra_state`` carries product-specific Run state the generic warmer can't know (e.g. PostHog
          AI's ``systemPrompt``); it is merged into the warm Run's initial state.

        Raises ``QuotaLimitExceeded`` (402) / ``PermissionDenied`` (403) when gated, and ``Throttled``
        (429) when the warm pool is full.
        """
        # Quota is a gateway/cache call — check it before taking the row lock, never while holding it.
        self.enforce_quota(self.task.origin_product, self.task.team, self.user)

        new_run: TaskRun
        with transaction.atomic():
            locked = Task.objects.select_for_update().get(id=self.task.id)
            existing = locked.latest_run
            if existing is not None and not existing.is_terminal:
                # A warm Run already idling, or an active Run in progress — either way, no double-provision.
                return WarmResult(run=existing, just_created=False)

            if self.at_capacity(locked.origin_product, locked.team, self.user):
                raise Throttled(detail="Warm-pool capacity reached. Release an idle warm session and try again.")

            run_state: dict[str, Any] = {
                "await_user_message": True,
                "initial_permission_mode": "default",
                **(extra_state or {}),
            }
            if existing is not None:
                # Latest Run is terminal — resume into a successor so the warm session reuses its filesystem.
                run_state["resume_from_run_id"] = str(existing.id)
                snapshot_external_id = (existing.state or {}).get("snapshot_external_id")
                if snapshot_external_id:
                    run_state["snapshot_external_id"] = snapshot_external_id

            new_run = locked.create_run(mode=mode, extra_state=run_state)

            # Dispatch only after the row commits, so a rollback can't leave an orphaned sandbox.
            task_id, run_id, team_id, user_id = str(locked.id), str(new_run.id), self.task.team_id, self.user.pk
            transaction.on_commit(
                lambda: execute_task_processing_workflow(
                    task_id=task_id,
                    run_id=run_id,
                    team_id=team_id,
                    user_id=user_id,
                    create_pr=False,
                    posthog_mcp_scopes="full",
                )
            )

        logger.info(
            "sandbox_warm_run_provisioned",
            task_id=str(self.task.id),
            run_id=str(new_run.id),
            origin_product=self.task.origin_product,
        )
        return WarmResult(run=new_run, just_created=True)
