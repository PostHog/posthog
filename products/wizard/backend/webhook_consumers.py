"""Wizard's consumer on the customer-facing GitHub App endpoint.

The registry imports this module on the first delivery, so it stays cheap: the handler defers
the task import, which drags Celery and the Django models in.
"""

from typing import Any, cast

from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery

from products.wizard.backend.facade.config import WIZARD_PULL_REQUEST_BRANCH_PREFIX


def _record_pull_request_state(delivery: WebhookDelivery) -> None:
    head_ref = ((delivery.payload.get("pull_request") or {}).get("head") or {}).get("ref")
    if not isinstance(head_ref, str) or not head_ref.startswith(WIZARD_PULL_REQUEST_BRANCH_PREFIX):
        return
    from products.wizard.backend.facade.tasks import (  # noqa: PLC0415 - keeps Celery and the Django models off the registry's import path
        process_wizard_pull_request_event,
    )

    cast(Any, process_wizard_pull_request_event).delay(payload=dict(delivery.payload))


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="wizard_pull_request_state",
        provider="github",
        app="posthog",
        event_types=frozenset({"pull_request"}),
        handler=_record_pull_request_state,
    ),
)
