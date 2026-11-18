"""Visual Review's consumer on the customer-facing GitHub App endpoint.

Every product shares the endpoint, and every default-branch push of every repository the App
sees reaches this handler. So the handler drops what is not such a push from the payload alone,
before any database read or product import.
"""

from collections.abc import Mapping
from typing import Any

from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _default_branch_push_repo_id(payload: Mapping[str, Any]) -> int | None:
    """The GitHub repository id of a push of commits to the default branch, or None for any other push."""
    if payload.get("deleted") is True:
        return None
    repository = payload.get("repository")
    if not isinstance(repository, Mapping):
        return None
    default_branch = repository.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        return None
    if payload.get("ref") != f"refs/heads/{default_branch}":
        return None
    repo_id = repository.get("id")
    # A JSON `true` decodes to a bool, which is an int in Python.
    if not isinstance(repo_id, int) or isinstance(repo_id, bool):
        return None
    return repo_id


def _advance_baseline_ledgers(delivery: WebhookDelivery) -> None:
    github_repo_id = _default_branch_push_repo_id(delivery.payload)
    if github_repo_id is None:
        return
    from products.visual_review.backend.facade.api import (  # noqa: PLC0415 - keeps product models off the registry import path
        advance_baseline_ledgers_after_push,
    )

    advance_baseline_ledgers_after_push(github_repo_id)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="visual_review_default_branch_push",
        provider="github",
        app="posthog",
        event_types=frozenset({"push"}),
        handler=_advance_baseline_ledgers,
    ),
)
