from collections.abc import Mapping

from products.docs_freshness.backend.facade import contracts
from products.docs_freshness.backend.logic import impact_check, pull_request_events


def accept_pull_request_event(payload: Mapping[str, object]) -> None:
    pull_request_events.accept_pull_request_event(payload)


def check_pull_request_head(head: contracts.PullRequestHead) -> None:
    impact_check.check_pull_request_head(head)
