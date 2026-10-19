"""What the team already has: workflows, integrations and saved email templates."""

import re
from typing import Any

from django.db.models import BigIntegerField, F
from django.db.models.functions import Coalesce

from posthog.models import EventProperty, Team
from posthog.models.integration import Integration

from products.messaging.backend.facade.api import EmailTemplateSummary, list_email_templates
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.services.data_suggestions.builder import EmailSender
from products.workflows.backend.services.data_suggestions.planner import Channel

_TEMPLATES_LIMIT = 20
_EVENT_PROPERTIES_LIMIT = 15
# Only plain names, so the email's Liquid variable needs no quoting.
_PLAIN_PROPERTY_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def used_trigger_events(team: Team) -> set[str]:
    used: set[str] = set()
    for trigger in HogFlow.objects.filter(team_id=team.id).exclude(status="archived").values_list("trigger", flat=True):
        filters = (trigger or {}).get("filters") or {}
        for event in filters.get("events") or []:
            if isinstance(event, dict) and isinstance(event.get("id"), str):
                used.add(event["id"])
    return used


def saved_workflow_actions(team: Team, workflow_id: str) -> list[dict[str, Any]] | None:
    """The actions of a draft a build saved, or None when it was deleted or archived. A secret input someone filled
    lives in the encrypted maps instead of the actions, so it comes back as a placeholder, never as its value."""
    row = (
        HogFlow.objects.filter(team_id=team.id, id=workflow_id)
        .exclude(status="archived")
        .values_list("actions", "encrypted_inputs", "draft_encrypted_inputs")
        .first()
    )
    if row is None:
        return None
    actions, *secret_maps = row
    filled: dict[str, set[str]] = {}
    for secrets in secret_maps:
        for action_id, inputs in (secrets or {}).items():
            filled.setdefault(action_id, set()).update(inputs or {})
    return [_with_filled_secrets(action, filled.get(action.get("id"), set())) for action in actions or []]


def _with_filled_secrets(action: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    if not keys:
        return action
    config = action.get("config") or {}
    inputs = {**(config.get("inputs") or {}), **{key: {"value": "<set>"} for key in keys}}
    return {**action, "config": {**config, "inputs": inputs}}


def channels(team: Team) -> frozenset[Channel]:
    kinds = set(Integration.objects.filter(team_id=team.id).values_list("kind", flat=True))
    connected: set[Channel] = set()
    if "twilio" in kinds:
        connected.add("sms")
    if kinds & {"apns", "firebase"}:
        connected.add("push")
    return frozenset(connected)


def slack_integration_id(team: Team) -> int | None:
    return (
        Integration.objects.filter(team_id=team.id, kind="slack")
        .order_by("created_at")
        .values_list("id", flat=True)
        .first()
    )


def email_sender(team: Team) -> EmailSender | None:
    """The project's default sender, or its only verified sender. With several and no default the step stays
    blank, so the team picks one rather than a draft sending from an identity nobody chose."""
    verified = _verified_senders(team)
    default_id = (
        TeamWorkflowsConfig.objects.filter(team_id=team.id)
        .values_list("default_email_integration_id", flat=True)
        .first()
    )
    default = next((sender for sender in verified if sender.integration_id == default_id), None)
    if default is not None:
        return default
    return verified[0] if len(verified) == 1 else None


def has_verified_email_sender(team: Team) -> bool:
    return bool(_verified_senders(team))


def _verified_senders(team: Team) -> list[EmailSender]:
    return [
        EmailSender(integration_id=integration.id, email=str(config["email"]), name=str(config.get("name") or ""))
        for integration in Integration.objects.filter(team_id=team.id, kind="email").order_by("created_at")
        if (config := integration.config or {}).get("verified") is True and config.get("email")
    ]


def email_templates(team: Team) -> tuple[EmailTemplateSummary, ...]:
    return tuple(list_email_templates(team.id, limit=_TEMPLATES_LIMIT))


def event_property_names(team: Team, event: str) -> tuple[str, ...]:
    """The properties the project sends on `event`, except PostHog's own `$` properties."""
    names = (
        # Matches the leading column of the (coalesce(project_id, team_id), event, property) unique index, so the
        # lookup is an index seek.
        EventProperty.objects.alias(
            effective_project_id=Coalesce(F("project_id"), F("team_id"), output_field=BigIntegerField())
        )
        .filter(effective_project_id=team.project_id, event=event)
        .exclude(property__startswith="$")
        .order_by("property")
        .values_list("property", flat=True)[:100]
    )
    return tuple(name for name in names if _PLAIN_PROPERTY_NAME.match(name))[:_EVENT_PROPERTIES_LIMIT]
