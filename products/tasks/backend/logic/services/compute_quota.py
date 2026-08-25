import logging
from enum import StrEnum

from django.conf import settings

from posthog.models import Team, User

from products.tasks.backend.metrics import observe_compute_quota_check
from products.tasks.backend.models import Task, TaskClientProvenance

COMPUTE_QUOTA_DENIAL_CODE = "posthog_code_billing_limit_exceeded"
ORGANIZATION_DEACTIVATED_DENIAL_CODE = "organization_deactivated"


class ComputeQuotaDenialReason(StrEnum):
    COMPUTE_QUOTA_EXHAUSTED = COMPUTE_QUOTA_DENIAL_CODE
    ORGANIZATION_DEACTIVATED = ORGANIZATION_DEACTIVATED_DENIAL_CODE


logger = logging.getLogger(__name__)


def organization_deactivated(team_id: int) -> bool:
    return Team.objects.filter(id=team_id, organization__is_active=False).exists()


def task_creator_is_staff(task: Task) -> bool:
    return bool(task.created_by_id and User.objects.filter(id=task.created_by_id, is_staff=True).exists())


def is_task_billable_compute(task: Task) -> bool:
    source_loop = task.loop if task.loop_id is not None else None
    return is_billable_compute(
        origin_product=task.origin_product,
        client_provenance=task.client_provenance,
        source_loop_id=task.loop_id,
        source_loop_internal=source_loop.internal if source_loop is not None else None,
    )


def is_billable_compute(
    *,
    origin_product: str | None,
    client_provenance: str | None,
    source_loop_id: object | None,
    source_loop_internal: bool | None,
) -> bool:
    if client_provenance != TaskClientProvenance.POSTHOG_DESKTOP:
        return False
    if origin_product == Task.OriginProduct.USER_CREATED:
        return True
    return bool(
        origin_product == Task.OriginProduct.LOOP and source_loop_id is not None and source_loop_internal is False
    )


def get_compute_quota_denial_reason(task: Task) -> ComputeQuotaDenialReason | None:
    if organization_deactivated(task.team_id):
        observe_compute_quota_check("checked_blocked")
        return ComputeQuotaDenialReason.ORGANIZATION_DEACTIVATED
    if task_creator_is_staff(task):
        return None
    if not getattr(settings, "TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED", False):
        return None
    if not is_task_billable_compute(task):
        return None
    try:
        exhausted = _is_posthog_code_quota_limited(task.team.api_token)
    except Exception:
        observe_compute_quota_check("fail_open")
        logger.warning(
            "compute_quota: PostHog Code quota state unavailable",
            extra={"team_id": task.team_id, "task_id": str(task.id)},
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
