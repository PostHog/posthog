from typing import Optional
from uuid import UUID, uuid5

from django.utils import timezone

import requests
from celery import shared_task
from structlog import get_logger

from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.ph_client import ph_scoped_capture
from posthog.plugins.plugin_server_api import reload_hog_flows_on_workers, reschedule_hog_flow_parked_jobs
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue
from posthog.utils import get_instance_region

from products.actions.backend.models.action import Action
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

logger = get_logger(__name__)

# Backstop against a runaway slice loop; at the endpoint's per-slice work budget this is far
# beyond any real parked backlog.
MAX_RESCHEDULE_SLICES = 500

WORKFLOW_CREATED_EVENT = "workflows workflow created"


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def refresh_affected_hog_flows(team_id: Optional[int] = None, action_id: Optional[int] = None) -> int:
    affected_hog_flows: list[HogFlow] = []

    if action_id:
        action = Action.objects.get(id=action_id)
        team_id = action.team_id
        # Find hog flows that reference this action in their trigger filters
        affected_hog_flows = list(
            HogFlow.objects.select_related("team")
            .filter(team_id=action.team_id, status="active")
            .filter(trigger__contains={"actions": [{"id": str(action_id)}]})
        )
    elif team_id:
        # Find hog flows that have test account filters enabled
        affected_hog_flows = list(
            HogFlow.objects.select_related("team")
            .filter(team_id=team_id, status="active")
            .filter(trigger__contains={"filter_test_accounts": True})
        )

    if team_id is None:
        raise Exception("Either team_id or action_id must be provided")

    if not affected_hog_flows:
        return 0

    # Update the updated_at timestamp to trigger a reload
    for hog_flow in affected_hog_flows:
        hog_flow.updated_at = timezone.now()

    updates = HogFlow.objects.bulk_update(affected_hog_flows, ["updated_at"])

    reload_hog_flows_on_workers(team_id=team_id, hog_flow_ids=[str(hog_flow.id) for hog_flow in affected_hog_flows])

    return updates


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(Exception,),
    dont_autoretry_for=(Team.DoesNotExist,),
    max_retries=5,
    retry_backoff=60,
    retry_backoff_max=600,
    retry_jitter=True,
)
@skip_team_scope_audit
def report_workflow_created(
    team_id: int, hog_flow_id: str, created_at: str, origin_product: str | None, actions_count: int
) -> None:
    team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    with ph_scoped_capture(event_region=get_instance_region(), raise_on_error=True) as capture:
        capture(
            distinct_id=str(team.uuid),
            event=WORKFLOW_CREATED_EVENT,
            timestamp=created_at,
            uuid=str(uuid5(UUID(hog_flow_id), WORKFLOW_CREATED_EVENT)),
            properties={
                "workflow_id": hog_flow_id,
                "origin_product": origin_product,
                "actions_count": actions_count,
            },
            groups=groups(team=team),
        )


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    max_retries=5,
    autoretry_for=(requests.RequestException,),
    retry_backoff=True,
)
@skip_team_scope_audit
def reschedule_hog_flow_timing(
    team_id: int,
    hog_flow_id: str,
    action_ids: list[str],
    sweep_floor: Optional[str] = None,
    sweep_until: Optional[str] = None,
    slice_count: int = 0,
) -> None:
    """Drive the plugin server's reschedule sweep for one workflow after a timing edit.

    Each call runs one bounded slice; when the sweep isn't done, the task re-enqueues itself
    with the returned sweep bounds so the spread window stays fixed across slices. Transient
    HTTP failures autoretry with backoff; a retried or re-enqueued slice is safe because the
    sweep is idempotent for fixed bounds.
    """
    if slice_count > MAX_RESCHEDULE_SLICES:
        logger.error(
            "workflows.timing_reschedule.slice_limit_exceeded",
            team_id=team_id,
            hog_flow_id=hog_flow_id,
            slice_count=slice_count,
        )
        return

    # The flow may have been disabled or deleted between slices - its parked runs get
    # cancelled as they wake, so stop sweeping rather than waking them early to cancel.
    if not HogFlow.objects.filter(team_id=team_id, id=hog_flow_id, status="active").exists():
        logger.info(
            "workflows.timing_reschedule.flow_no_longer_active",
            team_id=team_id,
            hog_flow_id=hog_flow_id,
            slice_count=slice_count,
        )
        return

    response = reschedule_hog_flow_parked_jobs(
        team_id=team_id,
        hog_flow_id=hog_flow_id,
        action_ids=action_ids,
        sweep_floor=sweep_floor,
        sweep_until=sweep_until,
    )
    response.raise_for_status()
    result = response.json()

    logger.info(
        "workflows.timing_reschedule.slice_completed",
        team_id=team_id,
        hog_flow_id=hog_flow_id,
        action_ids=action_ids,
        slice_count=slice_count,
        swept=result.get("swept"),
        remaining=result.get("remaining"),
    )

    if not result.get("done"):
        reschedule_hog_flow_timing.apply_async(
            kwargs={
                "team_id": team_id,
                "hog_flow_id": hog_flow_id,
                "action_ids": action_ids,
                "sweep_floor": result.get("sweep_floor"),
                "sweep_until": result.get("sweep_until"),
                "slice_count": slice_count + 1,
            },
            countdown=5,
        )
