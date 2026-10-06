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


def accept_ses_event(delivery: WebhookDelivery) -> None:
    """The inbound SES events SNS topic enters workflows here, so its consumer needs no internal import."""
    # Deferred to keep the Celery task and the SNS callback client off the facade import path.
    from products.workflows.backend.services.ses_tenant_events import handle_ses_tenant_event  # noqa: PLC0415

    handle_ses_tenant_event(delivery)
