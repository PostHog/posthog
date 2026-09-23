from typing import Any
from uuid import UUID

from django.db.models import F

from posthog.helpers.full_text_search import build_rank
from posthog.ingress.contracts import WebhookDelivery

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.workflows.backend.models import HogFlow


class WorkflowNotFound(Exception):
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
