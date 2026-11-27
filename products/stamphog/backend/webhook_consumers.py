"""Stamphog's consumers on its own GitHub App endpoint, and on the customer-facing PostHog App's.

The registry imports this module on the first delivery, so it stays cheap: the handler defers
the task import, which drags the GitHub and Temporal clients in.
"""

from collections.abc import Mapping
from typing import Any, cast

from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery

from products.stamphog.backend.facade.enums import (
    BROADCAST_REQUEST_PR_ACTIONS,
    BROADCAST_REQUEST_REVIEW_ACTIONS,
    ROUTING_ACTIONS,
)

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


def _is_base_retarget(payload: Mapping[str, Any]) -> bool:
    return payload.get("action") == "edited" and bool((payload.get("changes") or {}).get("base"))


def _changes_routing(payload: Mapping[str, Any]) -> bool:
    action = payload.get("action")
    if action in ROUTING_ACTIONS or action == "synchronize":
        return True
    # A base retarget, which changes the diff an attestation proved.
    return _is_base_retarget(payload)


def _route_reviewers(delivery: WebhookDelivery) -> None:
    if not _changes_routing(delivery.payload):
        return
    from products.stamphog.backend.facade.tasks import (  # noqa: PLC0415 - keeps the GitHub and Temporal clients off the registry's import path
        route_pull_request_reviewers,
    )

    cast(Any, route_pull_request_reviewers).delay(
        payload=dict(delivery.payload), delivery_id=delivery.delivery_id or ""
    )


def _queue_broadcast_request_refreshes(payload: Mapping[str, Any], installation_id: str) -> None:
    repository = (payload.get("repository") or {}).get("full_name")
    pr_number = (payload.get("pull_request") or {}).get("number")
    if not repository or not isinstance(pr_number, int):
        return
    from products.stamphog.backend.facade.tasks import (  # noqa: PLC0415 - keeps the GitHub and Temporal clients off the registry's import path
        refresh_broadcast_requests_for_pull_request,
    )

    cast(Any, refresh_broadcast_requests_for_pull_request).delay(
        repository=repository, pr_number=pr_number, installation_id=installation_id
    )


def _refresh_broadcast_requests_on_pull_request(delivery: WebhookDelivery) -> None:
    payload = delivery.payload
    if payload.get("action") not in BROADCAST_REQUEST_PR_ACTIONS:
        return
    _queue_broadcast_request_refreshes(payload, delivery.context.get("installation_id", ""))


def _refresh_broadcast_requests_on_review(delivery: WebhookDelivery) -> None:
    payload = delivery.payload
    review = payload.get("review") or {}
    if payload.get("action") not in BROADCAST_REQUEST_REVIEW_ACTIONS or (review.get("user") or {}).get("type") == "Bot":
        return
    if payload.get("action") == "submitted" and review.get("state") == "commented":
        return
    # The PostHog App's installation is not stamphog's, so the task matches on the repository alone.
    _queue_broadcast_request_refreshes(payload, "")


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
    WebhookConsumer(
        name="stamphog_broadcast_request_pull_requests",
        provider="github",
        app="stamphog",
        event_types=frozenset({"pull_request"}),
        handler=_refresh_broadcast_requests_on_pull_request,
    ),
    # The stamphog App gets no review events, so a person's approval or its dismissal arrives
    # through the PostHog App. GitHub delivers it to the region that holds that installation.
    WebhookConsumer(
        name="stamphog_broadcast_request_reviews",
        provider="github",
        app="posthog",
        event_types=frozenset({"pull_request_review"}),
        handler=_refresh_broadcast_requests_on_review,
    ),
)
