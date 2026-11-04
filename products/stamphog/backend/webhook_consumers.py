"""Stamphog's consumer on its own GitHub App endpoint.

The registry imports this module on the first delivery, so it stays cheap: the handler defers
the task import, which drags the GitHub and Temporal clients in.
"""

from typing import Any, cast

from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery

from products.stamphog.backend.facade.enums import ROUTING_ACTIONS

# Installation lifecycle events keep the repo-config rows in step with GitHub (repos added/removed,
# app uninstalled) so newly installed repos appear in the toggle list without a manual re-sync.
_INSTALLATION_EVENTS = frozenset({"installation", "installation_repositories"})


def _run_review(delivery: WebhookDelivery) -> None:
    from products.stamphog.backend.facade.tasks import (  # noqa: PLC0415 - keeps the GitHub and Temporal clients off the registry's import path
        process_installation_event,
        process_pull_request_event,
    )

    task = process_installation_event if delivery.event_type in _INSTALLATION_EVENTS else process_pull_request_event
    cast(Any, task).delay(payload=dict(delivery.payload), delivery_id=delivery.delivery_id or "")


def _route_reviewers(delivery: WebhookDelivery) -> None:
    if delivery.payload.get("action") not in ROUTING_ACTIONS:
        return
    from products.stamphog.backend.facade.tasks import (  # noqa: PLC0415 - keeps the GitHub and Temporal clients off the registry's import path
        route_pull_request_reviewers,
    )

    cast(Any, route_pull_request_reviewers).delay(
        payload=dict(delivery.payload), delivery_id=delivery.delivery_id or ""
    )


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="stamphog_review",
        provider="github",
        app="stamphog",
        event_types=frozenset({"pull_request"}) | _INSTALLATION_EVENTS,
        handler=_run_review,
        # The task resumes its own work off `delivery_id`, so a redelivery is how a run that
        # never finished gets picked up again. An ingress mark would hold that off for 24 h.
        dedup=False,
    ),
    WebhookConsumer(
        name="stamphog_reviewer_routing",
        provider="github",
        app="stamphog",
        event_types=frozenset({"pull_request"}),
        handler=_route_reviewers,
        # The stored routing record already makes a redelivery for the same head and action a
        # no-op, and a redelivery is how a run that used up its retries gets picked up again.
        dedup=False,
    ),
)
