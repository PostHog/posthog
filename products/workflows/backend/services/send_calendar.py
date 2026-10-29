"""The send calendar's read: a team's active, scheduled email workflows that are not transactional, with
only the fields a calendar card shows and the runs inside the shown range."""

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Final, cast
from uuid import UUID

from django.db import models
from django.db.models import F, Q, Value
from django.db.models.functions import Coalesce

from products.workflows.backend.facade.contracts import SendCalendarBatchJob, SendCalendarFlow, WorkflowSchedule
from products.workflows.backend.facade.enums import HogFlowBatchJobState, HogFlowScheduleStatus
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.models.hog_flow_schedule import SCHEDULED_TRIGGER_TYPES, HogFlowSchedule
from products.workflows.backend.services.hog_flow_schedules import list_open_schedules

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

# A project with more workflows on the calendar shows the most recently updated ones.
SEND_CALENDAR_FLOW_LIMIT: Final = 500
# A month grid shows at most six weeks. The cap bounds how many runs one request reads.
SEND_CALENDAR_MAX_RANGE_DAYS: Final = 92

TRANSACTIONAL_CATEGORY_TYPE: Final = "transactional"


def _json_text(source: str, *path: str) -> models.Func:
    return models.Func(
        F(source), *(Value(key) for key in path), function="jsonb_extract_path_text", output_field=models.TextField()
    )


def list_send_calendar_flows(
    *,
    team_id: int,
    start: datetime,
    end: datetime,
    user_access_control: "UserAccessControl | None",
) -> list[SendCalendarFlow]:
    """The workflows with an open schedule or a run in [start, end) that the reader may see. Pass None for
    `user_access_control` to skip the access filter, as a service credential does."""
    open_schedules = HogFlowSchedule.objects.filter(team_id=team_id).exclude(status=HogFlowScheduleStatus.COMPLETED)
    runs_in_range = HogFlowBatchJob.objects.filter(team_id=team_id, created_at__gte=start, created_at__lt=end)
    queryset = (
        HogFlow.objects.filter(
            team_id=team_id, status=HogFlow.State.ACTIVE, trigger__type__in=list(SCHEDULED_TRIGGER_TYPES)
        )
        .exclude(origin_product=HogFlow.OriginProduct.TRANSACTIONAL_EMAILS)
        .filter(Q(id__in=open_schedules.values("hog_flow_id")) | Q(id__in=runs_in_range.values("hog_flow_id")))
        # The card reads a few keys of the first email step and the trigger. Postgres extracts them, so the
        # full step configuration, which holds the email body, never leaves the database.
        .alias(
            _email_step=models.Func(
                F("actions"),
                models.Func(
                    Value('$[*] ? (@.type == "function_email")'),
                    template="%(expressions)s::jsonpath",
                    output_field=models.TextField(),
                ),
                function="jsonb_path_query_first",
                output_field=models.JSONField(),
            )
        )
        .filter(_email_step__isnull=False)
        .annotate(
            _category_type=Coalesce(
                _json_text("_email_step", "config", "message_category_type"),
                Value(""),
                output_field=models.TextField(),
            ),
            _category_id=_json_text("_email_step", "config", "message_category_id"),
            _email_to=_json_text("_email_step", "config", "inputs", "email", "value", "to", "email"),
            _trigger_type=_json_text("trigger", "type"),
            _audience_type=_json_text("trigger", "filters", "audience_type"),
            _audience_properties=models.Func(
                F("trigger"),
                Value("filters"),
                Value("properties"),
                function="jsonb_extract_path",
                output_field=models.JSONField(),
            ),
        )
        .exclude(_category_type=TRANSACTIONAL_CATEGORY_TYPE)
        .select_related("created_by")
        .only("id", "team_id", "name", "origin_product", "created_by")
        .order_by("-updated_at", "-id")
    )
    if user_access_control is not None:
        queryset = user_access_control.filter_queryset_by_access_level(queryset)
    flows = list(queryset[:SEND_CALENDAR_FLOW_LIMIT])
    if not flows:
        return []
    if user_access_control is not None:
        user_access_control.preload_object_access_controls(cast("list[models.Model]", flows))

    flow_ids = [flow.id for flow in flows]
    schedules_by_flow: defaultdict[UUID, list[WorkflowSchedule]] = defaultdict(list)
    for schedule in list_open_schedules(team_id=team_id, hog_flow_ids=flow_ids):
        schedules_by_flow[schedule.hog_flow_id].append(schedule)
    runs_by_flow: defaultdict[UUID, list[SendCalendarBatchJob]] = defaultdict(list)
    for run in (
        runs_in_range.filter(hog_flow_id__in=flow_ids)
        .only("id", "hog_flow_id", "status", "created_at")
        .order_by("created_at", "id")
    ):
        runs_by_flow[run.hog_flow_id].append(
            SendCalendarBatchJob(id=run.id, status=HogFlowBatchJobState(run.status), created_at=run.created_at)
        )

    return [_to_send_calendar_flow(flow, user_access_control, schedules_by_flow, runs_by_flow) for flow in flows]


def _to_send_calendar_flow(
    flow: HogFlow,
    user_access_control: "UserAccessControl | None",
    schedules_by_flow: Mapping[UUID, list[WorkflowSchedule]],
    runs_by_flow: Mapping[UUID, list[SendCalendarBatchJob]],
) -> SendCalendarFlow:
    audience_properties = getattr(flow, "_audience_properties", None)
    return SendCalendarFlow(
        id=flow.id,
        name=flow.name,
        origin_product=flow.origin_product,
        created_by=flow.created_by,
        user_access_level=user_access_control.get_user_access_level(flow) if user_access_control is not None else None,
        trigger_type=getattr(flow, "_trigger_type", None) or "",
        audience_properties=audience_properties if isinstance(audience_properties, list) else [],
        audience_type=getattr(flow, "_audience_type", None),
        email_to=getattr(flow, "_email_to", None) or None,
        message_category_id=getattr(flow, "_category_id", None) or None,
        schedules=tuple(schedules_by_flow.get(flow.id, [])),
        batch_jobs=tuple(runs_by_flow.get(flow.id, [])),
    )
