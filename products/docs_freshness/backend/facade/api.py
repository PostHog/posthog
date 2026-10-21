from collections.abc import Mapping

from products.docs_freshness.backend.logic import pull_request_events


def accept_pull_request_event(payload: Mapping[str, object]) -> None:
    pull_request_events.accept_pull_request_event(payload)
