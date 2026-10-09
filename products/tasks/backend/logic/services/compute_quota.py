import logging
from datetime import datetime
from typing import Literal

from django.conf import settings

from posthog.models import Team, User

from products.tasks.backend.facade.contracts import ComputeQuotaDenialReason
from products.tasks.backend.metrics import observe_compute_quota_check
from products.tasks.backend.models import Task, TaskClientProvenance, TaskRun

COMPUTE_QUOTA_DENIAL_CODE = ComputeQuotaDenialReason.COMPUTE_QUOTA_EXHAUSTED.value
ORGANIZATION_DEACTIVATED_DENIAL_CODE = ComputeQuotaDenialReason.ORGANIZATION_DEACTIVATED.value


logger = logging.getLogger(__name__)


def organization_deactivated(team_id: int) -> bool:
    return Team.objects.filter(id=team_id, organization__is_active=False).exists()


def task_creator_is_staff(task: Task) -> bool:
    return bool(task.created_by_id and User.objects.filter(id=task.created_by_id, is_staff=True).exists())


BillingProduct = Literal["posthog_code", "cloud_agents"]


def compute_pricing_product(origin_product: str | None) -> BillingProduct:
    """The product whose rate card prices a run's compute, whether or not the run is billed."""
    return "cloud_agents" if origin_product == Task.OriginProduct.CLOUD_AGENTS else "posthog_code"


def task_billing_product(task: Task) -> BillingProduct | None:
    source_loop = task.loop if task.loop_id is not None else None
    return billing_product(
        origin_product=task.origin_product,
        client_provenance=task.client_provenance,
        source_loop_id=task.loop_id,
        source_loop_internal=source_loop.internal if source_loop is not None else None,
    )


def is_task_billable_compute(task: Task) -> bool:
    return task_billing_product(task) == "posthog_code"


def billing_product(
    *,
    origin_product: str | None,
    client_provenance: str | None,
    source_loop_id: object | None,
    source_loop_internal: bool | None,
) -> BillingProduct | None:
    """The product that pays for a run's compute. None when the run is not billed."""
    if origin_product == Task.OriginProduct.CLOUD_AGENTS:
        # Every Cloud Agents task is internal, so only the provenance stamp separates a billed run.
        return "cloud_agents" if client_provenance == TaskClientProvenance.CLOUD_AGENTS else None
    if client_provenance != TaskClientProvenance.POSTHOG_DESKTOP:
        return None
    if origin_product in (Task.OriginProduct.USER_CREATED, Task.OriginProduct.SPACE_SETUP):
        return "posthog_code"
    if origin_product == Task.OriginProduct.LOOP and source_loop_id is not None and source_loop_internal is False:
        return "posthog_code"
    return None


def is_billable_compute(
    *,
    origin_product: str | None,
    client_provenance: str | None,
    source_loop_id: object | None,
    source_loop_internal: bool | None,
) -> bool:
    return (
        billing_product(
            origin_product=origin_product,
            client_provenance=client_provenance,
            source_loop_id=source_loop_id,
            source_loop_internal=source_loop_internal,
        )
        == "posthog_code"
    )


def _quota_enforcement_enabled(product: BillingProduct) -> bool:
    # Each product has its own kill switch, so one can be turned off without the other.
    if product == "cloud_agents":
        return bool(getattr(settings, "CLOUD_AGENTS_QUOTA_ENFORCEMENT_ENABLED", True))
    return bool(getattr(settings, "TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED", False))


def get_compute_quota_denial_reason(task: Task) -> ComputeQuotaDenialReason | None:
    if organization_deactivated(task.team_id):
        observe_compute_quota_check("checked_blocked")
        return ComputeQuotaDenialReason.ORGANIZATION_DEACTIVATED
    if task_creator_is_staff(task):
        return None
    product = task_billing_product(task)
    if product is None or not _quota_enforcement_enabled(product):
        return None
    try:
        exhausted = (
            _is_cloud_agents_quota_limited(task.team.api_token)
            if product == "cloud_agents"
            else _is_posthog_code_quota_limited(task.team.api_token)
        )
    except Exception:
        observe_compute_quota_check("fail_open")
        logger.warning(
            "compute_quota: quota state unavailable",
            extra={"team_id": task.team_id, "task_id": str(task.id), "billing_product": product},
            exc_info=True,
        )
        return None
    observe_compute_quota_check("checked_blocked" if exhausted else "checked_allowed")
    return ComputeQuotaDenialReason.COMPUTE_QUOTA_EXHAUSTED if exhausted else None


def is_compute_quota_exhausted(task: Task) -> bool:
    return get_compute_quota_denial_reason(task) is not None


def _is_posthog_code_quota_limited(team_api_token: str) -> bool:
    from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

    return is_team_limited(
        team_api_token,
        QuotaResource.POSTHOG_CODE_CREDITS,
        QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
    )


def _is_cloud_agents_quota_limited(team_api_token: str) -> bool:
    from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

    return is_team_limited(
        team_api_token,
        QuotaResource.CLOUD_AGENTS_CREDITS,
        QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
    )


CloudAgentsQuotaDenial = Literal["quota_exhausted", "organization_deactivated"]

_ACTIVE_RUN_STATUSES = (TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS)


def cloud_agents_quota_denial(*, team_id: int) -> CloudAgentsQuotaDenial | None:
    """Why the team must not start or continue a billed Cloud Agents run, or None.

    A failed quota lookup allows the run, and the quota-check counter records it.
    """
    try:
        row = Team.objects.filter(id=team_id).values_list("api_token", "organization__is_active").first()
        if row is None:
            return None
        api_token, organization_active = row
        if organization_active is False:
            observe_compute_quota_check("checked_blocked")
            return "organization_deactivated"
        if not _quota_enforcement_enabled("cloud_agents"):
            return None
        exhausted = _is_cloud_agents_quota_limited(api_token)
    except Exception:
        observe_compute_quota_check("fail_open")
        logger.warning("compute_quota: Cloud Agents quota state unavailable", extra={"team_id": team_id}, exc_info=True)
        return None
    observe_compute_quota_check("checked_blocked" if exhausted else "checked_allowed")
    return "quota_exhausted" if exhausted else None


def cloud_agents_quota_reset_at(*, team_id: int) -> datetime | None:
    """The end of the team's billing period, when its quota resets. None when it is not known."""
    try:
        team = Team.objects.select_related("organization").get(id=team_id)
        period = team.organization.current_billing_period
    except Exception:
        logger.warning("compute_quota: billing period unavailable", extra={"team_id": team_id}, exc_info=True)
        return None
    return period.end if period else None


def list_teams_over_cloud_agents_quota_with_active_runs() -> list[int]:
    """Teams that have a billed Cloud Agents run in progress and must not have one.

    A deactivated organization always counts. A team over its quota counts while enforcement is on.
    A failed quota lookup returns the deactivated teams only, so a sweep never stops a run on an
    unknown quota state.
    """
    teams = dict(
        Team.objects.filter(
            id__in=TaskRun.objects.filter(
                status__in=_ACTIVE_RUN_STATUSES,
                task__origin_product=Task.OriginProduct.CLOUD_AGENTS,
                task__client_provenance=TaskClientProvenance.CLOUD_AGENTS,
            ).values("team_id")
        ).values_list("id", "organization__is_active")
    )
    over = {team_id for team_id, organization_active in teams.items() if organization_active is False}
    candidates = [team_id for team_id in teams if team_id not in over]
    if candidates and _quota_enforcement_enabled("cloud_agents"):
        try:
            over.update(_cloud_agents_quota_limited_team_ids(candidates))
        except Exception:
            observe_compute_quota_check("fail_open")
            logger.warning("compute_quota: Cloud Agents quota state unavailable", exc_info=True)
    return sorted(over)


def _cloud_agents_quota_limited_team_ids(team_ids: list[int]) -> set[int]:
    from ee.billing.quota_limiting import QuotaResource, get_teams_limited_until

    resource = QuotaResource.CLOUD_AGENTS_CREDITS.value
    tokens = dict(Team.objects.filter(id__in=team_ids).values_list("api_token", "id"))
    limited = get_teams_limited_until(tokens.keys(), [resource])
    return {tokens[token] for token, resources in limited.items() if resource in resources}
