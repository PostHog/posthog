"""Forward GitHub App webhook deliveries onto the internal events topic.

The counterpart to ``products.slack_app.backend.slack_workflow_events``, and deliberately dumb in
the same way: resolve the PostHog projects behind the GitHub installation, then write the delivery
out as-is. A workflow's trigger config decides what it wants, and the CDP consumer evaluates that.

Registered in the GitHub App webhook fan-out (``posthog.urls.github_webhook``), which verifies the
signature, parses the body, and dedupes redeliveries before any handler runs.
"""

import uuid
from typing import Any

from django.conf import settings

import structlog

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.models.instance_setting import get_instance_setting
from posthog.models.integration import Integration

logger = structlog.get_logger(__name__)

GITHUB_EVENT_RECEIVED_EVENT = "$github_event_received"

# Event types a workflow can be triggered by. The fan-out delivers more than these to other
# handlers, so the registration in posthog/urls.py is the real list; this mirrors it for the
# trigger UI's sake.
GITHUB_TRIGGER_EVENT_TYPES = ("issues", "issue_comment", "pull_request", "pull_request_review", "push")

_GITHUB_EVENT_NAMESPACE = uuid.UUID("2c9f5d71-8e4a-4b6d-9f13-7a5e0c2b8d64")

# Associations that mean the actor has, or is granted, write access to the repository. Anyone can
# open an issue on a public repo, so this is what separates a maintainer from a passer-by.
TRUSTED_AUTHOR_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")


def _subject(payload: dict[str, Any]) -> dict[str, Any]:
    """The issue, pull request, comment or review the delivery is about, whichever it carries.

    A pull_request_review delivery carries both `review` and `pull_request`; the review is what
    the actor wrote, so it takes priority the same way a comment does over the issue it's on.
    """
    for key in ("comment", "review", "pull_request", "issue"):
        node = payload.get(key)
        if isinstance(node, dict):
            return node
    return {}


def _actor_has_write_access(event_type: str, subject: dict[str, Any]) -> bool:
    """Whether the actor behind this delivery can write to the repository.

    Anyone can open an issue or comment on a public repository, so the association is what
    separates a maintainer from a passer-by. A push needs write access to happen at all.
    """
    if event_type == "push":
        return True
    return subject.get("author_association") in TRUSTED_AUTHOR_ASSOCIATIONS


def _is_own_app_sender(sender: dict[str, Any]) -> bool:
    """Whether this delivery's sender is PostHog's own GitHub App bot.

    Unlike Slack, where each connected workspace can have its own app identity, one GitHub App
    per environment posts for every installation, so its slug is an instance setting rather than
    something resolved per-integration.
    """
    if sender.get("type") != "Bot":
        return False
    app_slug = get_instance_setting("GITHUB_APP_SLUG")
    return bool(app_slug) and sender.get("login") == f"{app_slug}[bot]"


def _event_properties(event_type: str, payload: dict[str, Any], *, integration_id: int) -> dict[str, Any]:
    repository = payload.get("repository") or {}
    sender = payload.get("sender") or {}
    subject = _subject(payload)
    ref = payload.get("ref") or ""

    return {
        # The PostHog GitHub connection this copy belongs to, so a step can resolve back to it.
        "integration_id": integration_id,
        "event_type": event_type,
        "action": payload.get("action"),
        "repository": repository.get("full_name"),
        "repository_private": repository.get("private"),
        "sender": sender.get("login"),
        # Nullable rather than a boolean, so a filter can use is_set / is_not_set. Comparing a real
        # boolean against a filter's string value never matches.
        "bot_sender": sender.get("login") if sender.get("type") == "Bot" else None,
        # Checked at eligibility rather than baked into a trigger's filters (see the CDP consumer's
        # `isOwnGithubEvent`), so a workflow created through the API or MCP without a matching
        # filter still can't retrigger on PostHog's own write.
        "own_app": _is_own_app_sender(sender),
        "author_association": subject.get("author_association"),
        # Precomputed for the same reason: a property filter compares against a constant, so
        # "trusted, or a push, which is write-gated anyway" is unexpressible from the raw fields.
        "actor_access": "write" if _actor_has_write_access(event_type, subject) else "read",
        "title": subject.get("title"),
        "body": subject.get("body"),
        # Only a pull_request_review delivery carries this: approved, changes_requested or
        # commented. Without it, a workflow can't tell an approval from a block request.
        "review_state": subject.get("state") if event_type == "pull_request_review" else None,
        "number": subject.get("number"),
        "url": subject.get("html_url"),
        "ref": ref,
        # Push events name the ref, everything else names the PR's head branch.
        "branch": ref.removeprefix("refs/heads/") or (payload.get("pull_request") or {}).get("head", {}).get("ref"),
        "installation_id": (payload.get("installation") or {}).get("id"),
        # Anything a step wants that the flat fields above don't cover.
        "github_event": payload,
    }


def emit_github_event(event_type: str, payload: dict[str, Any], delivery_id: str) -> None:
    """Write one internal event per PostHog project connected to this GitHub installation.

    Never raises. This runs inside the webhook fan-out, which owes GitHub a fast response and
    shares the request with the tasks, conversations and loops handlers.
    """
    if not settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED:
        return

    installation_id = (payload.get("installation") or {}).get("id")
    if installation_id is None:
        return

    try:
        integrations = list(
            Integration.objects.filter(kind="github", integration_id=str(installation_id)).values_list("team_id", "id")
        )
    except Exception:
        logger.exception("github_workflow_event_integration_lookup_failed", installation_id=installation_id)
        return

    distinct_id = str((payload.get("sender") or {}).get("login") or f"installation:{installation_id}")

    for team_id, integration_id in integrations:
        try:
            produce_internal_event(
                team_id,
                InternalEventEvent(
                    event=GITHUB_EVENT_RECEIVED_EVENT,
                    distinct_id=distinct_id,
                    properties=_event_properties(event_type, payload, integration_id=integration_id),
                    uuid=str(uuid.uuid5(_GITHUB_EVENT_NAMESPACE, f"{team_id}:{delivery_id or ''}")),
                ),
            )
        except Exception:
            logger.exception(
                "github_workflow_event_produce_failed",
                installation_id=installation_id,
                team_id=team_id,
                delivery_id=delivery_id,
            )
