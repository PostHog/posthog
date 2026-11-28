from typing import Any

from products.messaging.backend.facade.transactional_email import DeliveryUnavailable, EmailNotQueued, QueuedEmail


def batch_outcome(result: QueuedEmail | EmailNotQueued) -> dict[str, Any]:
    if isinstance(result, QueuedEmail):
        return {"outcome": "replayed" if result.replayed else "queued"}
    if isinstance(result.error, DeliveryUnavailable):
        return {"outcome": "unavailable"}
    return {"outcome": "rejected", "error_code": result.error.code}
