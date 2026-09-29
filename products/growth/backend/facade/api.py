from datetime import timedelta
from typing import Literal

from django.conf import settings

from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.instance_setting import get_instance_setting
from posthog.temporal.common.client import async_connect
from posthog.utils import get_instance_region

from products.growth.backend.models import OrganizationEnrichment
from products.growth.backend.temporal.signup_enrichment.trigger import dispatch_wizard_stamp_rescore

WizardStampRescoreSkipReason = Literal["disabled", "no_enrichment_record", "dispatch_backlog_full", "dispatch_failed"]


@frozen
class WizardStampRescoreOutcome:
    queued: bool
    reason: WizardStampRescoreSkipReason | None = None


def _rescore_enabled() -> bool:
    try:
        return bool(get_instance_setting("GROWTH_SIGNUP_ENRICHMENT_ENABLED"))
    except Exception as e:
        capture_exception(e)
        return False


async def start_account_audit(*, organization_id: str, team_id: int, user_id: int) -> str:
    from products.growth.backend.temporal.account_audit.workflow import (  # noqa: PLC0415 — avoids loading Temporal workflows during Django startup
        AccountAuditWorkflow,
        AccountAuditWorkflowInput,
    )

    workflow_id = AccountAuditWorkflow.workflow_id_for(organization_id)
    client = await async_connect()
    await client.start_workflow(
        AccountAuditWorkflow.run,
        AccountAuditWorkflowInput(organization_id=organization_id, team_id=team_id, user_id=user_id),
        id=workflow_id,
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        run_timeout=timedelta(hours=3),
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
    )
    return workflow_id


def request_wizard_stamp_rescore(organization_id: str) -> WizardStampRescoreOutcome:
    if not _rescore_enabled() or get_instance_region() not in ("US", "EU"):
        return WizardStampRescoreOutcome(queued=False, reason="disabled")

    if not OrganizationEnrichment.objects.filter(organization_id=organization_id).exists():
        return WizardStampRescoreOutcome(queued=False, reason="no_enrichment_record")

    failure = dispatch_wizard_stamp_rescore(organization_id)
    if failure is not None:
        return WizardStampRescoreOutcome(queued=False, reason=failure)
    return WizardStampRescoreOutcome(queued=True)
