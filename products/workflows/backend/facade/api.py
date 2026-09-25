from typing import Any
from uuid import UUID

from django.db.models import F

from posthog.helpers.full_text_search import build_rank
from posthog.ingress.contracts import WebhookDelivery

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.workflows.backend.models import HogFlow


class WorkflowNotFound(Exception):
    pass


class WorkflowAccessDenied(Exception):
    pass


class WorkflowArchived(Exception):
    pass


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
