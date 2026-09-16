from uuid import UUID

from posthog.ingress.contracts import WebhookDelivery

from products.workflows.backend.models import HogFlow


class WorkflowNotFound(Exception):
    pass


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
