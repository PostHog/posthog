from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db.models import F

from posthog.dataclasses import frozen
from posthog.helpers.full_text_search import build_rank
from posthog.ingress.contracts import WebhookDelivery
from posthog.models.team.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.workflows.backend.models import HogFlow, HogFlowSchedule

if TYPE_CHECKING:
    from rest_framework.serializers import BaseSerializer

    from posthog.models.user import User


class WorkflowNotFound(Exception):
    pass


class WorkflowAccessDenied(Exception):
    pass


class WorkflowArchived(Exception):
    pass


class WorkflowInvalid(Exception):
    """The payload failed the validation the workflows API runs; ``detail`` holds the serializer errors."""

    def __init__(self, detail: dict[str, Any] | list[Any] | str) -> None:
        super().__init__(detail)
        self.detail = detail


@frozen
class WorkflowDTO:
    id: str
    name: str
    status: str


@frozen
class WorkflowScheduleDTO:
    id: str
    workflow_id: str
    status: str
    starts_at: datetime
    next_run_at: datetime | None


def search_workflows(
    *,
    project_id: int,
    query: str | None,
    access_control: UserAccessControl,
    limit: int,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    queryset = access_control.filter_queryset_by_access_level(
        HogFlow.objects.filter(
            team__project_id=project_id,
            status__in=(HogFlow.State.DRAFT, HogFlow.State.ACTIVE),
        )
    )

    if query:
        queryset = queryset.annotate(rank=build_rank({"name": "A", "description": "C"}, query, config="simple"))
        queryset = queryset.filter(rank__gt=0.05).order_by("-rank")
    else:
        queryset = queryset.order_by(F("name").asc(nulls_first=True))

    total_count = queryset.count()
    fields = ["id", "name", "description", "status"]
    if query:
        fields.append("rank")

    results: list[dict[str, Any]] = []
    for workflow in queryset[offset : offset + limit].values(*fields):
        result: dict[str, Any] = {
            "type": "hog_flow",
            "result_id": str(workflow["id"]),
            "extra_fields": {
                "name": workflow["name"],
                "description": workflow["description"],
                "status": workflow["status"],
            },
        }
        if query:
            result["rank"] = workflow["rank"]
        results.append(result)

    return results, total_count


def get_workflow_owner_id(*, team_id: int, workflow_id: UUID) -> int | None:
    try:
        return HogFlow.objects.values_list("created_by_id", flat=True).get(team_id=team_id, id=workflow_id)
    except HogFlow.DoesNotExist:
        raise WorkflowNotFound() from None


def accept_github_event(delivery: WebhookDelivery) -> None:
    """The inbound GitHub App webhook enters workflows here, so its consumer needs no internal import."""
    # Deferred to keep the Kafka producer off the facade import path.
    from products.workflows.backend.github_workflow_events import emit_github_event  # noqa: PLC0415

    emit_github_event(delivery.event_type, dict(delivery.payload), delivery.delivery_id or "")


def accept_ses_event(delivery: WebhookDelivery) -> None:
    """The inbound SES events SNS topic enters workflows here, so its consumer needs no internal import."""
    # Deferred to keep the Celery task and the SNS callback client off the facade import path.
    from products.workflows.backend.services.ses_tenant_events import handle_ses_tenant_event  # noqa: PLC0415

    handle_ses_tenant_event(delivery)


def set_workflow_enabled(*, team_id: int, user_id: int, workflow_id: UUID, enabled: bool) -> str:
    """Flip a workflow between ``active`` and ``draft`` as ``user_id`` and return the new status.

    The same transition the lifecycle API tools make (enable is ``active``, disable is
    ``draft``); the scheduler fires only active workflows, so a disabled one stops at its
    next occurrence and keeps its schedule for when it is enabled again. Archived workflows
    are left alone. The user must hold editor access to the workflow, as in the API.
    """
    from posthog.models.user import User  # noqa: PLC0415 — keeps the user model off the facade import path

    from products.workflows.backend.api.hog_flow import HogFlowSerializer  # noqa: PLC0415 - heavy DRF import

    hog_flow = HogFlow.objects.select_related("team").filter(team_id=team_id, id=workflow_id).first()
    if hog_flow is None:
        raise WorkflowNotFound()
    if hog_flow.status == HogFlow.State.ARCHIVED:
        raise WorkflowArchived()
    user = User.objects.get(id=user_id)
    if not UserAccessControl(user=user, team=hog_flow.team).check_access_level_for_object(hog_flow, "editor"):
        raise WorkflowAccessDenied()
    target = HogFlow.State.ACTIVE if enabled else HogFlow.State.DRAFT
    if hog_flow.status != target:
        if enabled:
            serializer = HogFlowSerializer(
                hog_flow,
                data={"status": target},
                partial=True,
                context={"team_id": team_id, "get_team": lambda: hog_flow.team},
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
        else:
            hog_flow.status = target
            hog_flow.save(update_fields=["status", "updated_at"])
    return str(hog_flow.status)


def _get_user(user_id: int) -> "User":
    from posthog.models.user import User  # noqa: PLC0415 - keeps the user model off the facade import path

    return User.objects.get(id=user_id)


def _serializer_context(*, team: Team, user: "User") -> dict[str, Any]:
    """The context the workflows API gives its serializers, built without an HTTP request.

    ``HogFlowSerializer.create`` takes the creator from ``request.user``. A non-web
    ``event_source`` keeps draft validation strict, so a broken workflow is rejected here
    instead of when it is enabled.
    """
    from django.test import RequestFactory  # noqa: PLC0415 - keeps the test client off the facade import path

    from posthog.event_usage import EventSource  # noqa: PLC0415 - keeps the analytics client off the facade import path

    request = RequestFactory().post("/")
    request.user = user
    return {"request": request, "team_id": team.id, "get_team": lambda: team, "event_source": EventSource.API}


def _validate_or_raise(serializer: "BaseSerializer[Any]") -> None:
    from rest_framework.exceptions import ValidationError  # noqa: PLC0415 - heavy DRF import

    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as exc:
        raise WorkflowInvalid(exc.detail) from exc


def _get_workflow_for_editor(*, team_id: int, user_id: int, workflow_id: UUID) -> tuple[HogFlow, "User"]:
    hog_flow = HogFlow.objects.select_related("team").filter(team_id=team_id, id=workflow_id).first()
    if hog_flow is None:
        raise WorkflowNotFound()
    user = _get_user(user_id)
    access = UserAccessControl(user=user, team=hog_flow.team)
    if not access.has_project_access or not access.check_access_level_for_object(hog_flow, "editor"):
        raise WorkflowAccessDenied()
    return hog_flow, user


def _workflow_dto(hog_flow: HogFlow) -> WorkflowDTO:
    return WorkflowDTO(id=str(hog_flow.id), name=hog_flow.name or "", status=str(hog_flow.status))


def _schedule_dto(schedule: HogFlowSchedule) -> WorkflowScheduleDTO:
    return WorkflowScheduleDTO(
        id=str(schedule.id),
        workflow_id=str(schedule.hog_flow_id),
        status=str(schedule.status),
        starts_at=schedule.starts_at,
        next_run_at=schedule.next_run_at,
    )


def create_workflow(*, team_id: int, user_id: int, data: dict[str, Any]) -> WorkflowDTO:
    """Create a workflow as ``user_id`` from a full API payload and return it.

    ``data`` is what a client posts to the workflows API (name, description, status,
    origin_product, exit_condition, variables, actions, edges, trigger_masking...). It goes
    through the same serializer, so every validation the API runs applies, including the
    flag-gated templates. The user needs editor access to workflows in the team, as for a
    create through the API.
    """
    from products.workflows.backend.api.hog_flow import HogFlowSerializer  # noqa: PLC0415 - heavy DRF import

    team = Team.objects.get(id=team_id)
    user = _get_user(user_id)
    access = UserAccessControl(user=user, team=team)
    if not access.has_project_access or not access.check_access_level_for_resource("hog_flow", "editor"):
        raise WorkflowAccessDenied()
    serializer = HogFlowSerializer(data=data, context=_serializer_context(team=team, user=user))
    _validate_or_raise(serializer)
    return _workflow_dto(serializer.save())


def archive_workflow(*, team_id: int, user_id: int, workflow_id: UUID) -> None:
    """Archive the workflow as ``user_id``, the status-only update the API makes.

    Its schedule rows stay as they are, as with the API: the scheduler skips a schedule whose
    workflow is not active, clears its ``next_run_at`` when it comes due, and arms it again
    only once the workflow is active. A workflow that is already archived is left alone.
    """
    from products.workflows.backend.api.hog_flow import HogFlowUpdateSerializer  # noqa: PLC0415 - heavy DRF import

    hog_flow, user = _get_workflow_for_editor(team_id=team_id, user_id=user_id, workflow_id=workflow_id)
    if hog_flow.status == HogFlow.State.ARCHIVED:
        return
    serializer = HogFlowUpdateSerializer(
        hog_flow,
        data={"status": HogFlow.State.ARCHIVED},
        partial=True,
        context=_serializer_context(team=hog_flow.team, user=user),
    )
    _validate_or_raise(serializer)
    serializer.save()


def create_workflow_schedule(
    *,
    team_id: int,
    user_id: int,
    workflow_id: UUID,
    rrule: str,
    starts_at: datetime,
    timezone: str = "UTC",
    variables: dict[str, Any] | None = None,
) -> WorkflowScheduleDTO:
    """Add a recurring schedule to the workflow as ``user_id`` and return it.

    Same validation as the API's schedules endpoint. ``next_run_at`` starts empty: the
    scheduler computes it on its next poll, and only while the workflow is active.
    """
    from products.workflows.backend.api.hog_flow import HogFlowScheduleSerializer  # noqa: PLC0415 - heavy DRF import

    hog_flow, user = _get_workflow_for_editor(team_id=team_id, user_id=user_id, workflow_id=workflow_id)
    if hog_flow.status == HogFlow.State.ARCHIVED:
        raise WorkflowArchived()
    serializer = HogFlowScheduleSerializer(
        data={"rrule": rrule, "starts_at": starts_at, "timezone": timezone, "variables": variables or {}},
        context=_serializer_context(team=hog_flow.team, user=user),
    )
    _validate_or_raise(serializer)
    return _schedule_dto(serializer.save(team=hog_flow.team, hog_flow=hog_flow))


def update_workflow_schedule(
    *,
    team_id: int,
    user_id: int,
    workflow_id: UUID,
    schedule_id: UUID,
    starts_at: datetime | None = None,
    rrule: str | None = None,
    timezone: str | None = None,
) -> WorkflowScheduleDTO:
    """Change a schedule's start, RRULE or timezone as ``user_id``; ``None`` leaves a field as it is.

    The serializer clears ``next_run_at`` when any of the three changes, so the scheduler
    computes the next occurrence again on its next poll.
    """
    from products.workflows.backend.api.hog_flow import HogFlowScheduleSerializer  # noqa: PLC0415 - heavy DRF import

    hog_flow, user = _get_workflow_for_editor(team_id=team_id, user_id=user_id, workflow_id=workflow_id)
    if hog_flow.status == HogFlow.State.ARCHIVED:
        raise WorkflowArchived()
    schedule = HogFlowSchedule.objects.filter(id=schedule_id, hog_flow=hog_flow, team_id=team_id).first()
    if schedule is None:
        raise WorkflowNotFound()
    changes = {"starts_at": starts_at, "rrule": rrule, "timezone": timezone}
    serializer = HogFlowScheduleSerializer(
        schedule,
        data={field: value for field, value in changes.items() if value is not None},
        partial=True,
        context=_serializer_context(team=hog_flow.team, user=user),
    )
    _validate_or_raise(serializer)
    return _schedule_dto(serializer.save())
