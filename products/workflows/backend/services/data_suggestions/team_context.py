"""What the team already has: events, workflows, integrations and saved email templates."""

from django.db.models import F, Q

from posthog.models import EventDefinition, Team
from posthog.models.integration import Integration

from products.messaging.backend.facade.api import EmailTemplateContent, list_email_templates
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.data_suggestions.builder import EmailSender
from products.workflows.backend.services.data_suggestions.planner import Channel

EVENT_DEFINITIONS_LIMIT = 300
_TEMPLATES_LIMIT = 20
# PostHog's own events that mark a real moment, unlike the generic `$` events the planner must skip.
_ALLOWED_POSTHOG_EVENTS = frozenset({"$conversation_ticket_created"})


def recent_event_names(team: Team, *, exclude: set[str]) -> list[str]:
    # Filtered before the limit, so a project whose newest definitions are all `$` events still gets its own events.
    return list(
        EventDefinition.objects.filter(team_id=team.id)
        .filter(~Q(name__startswith="$") | Q(name__in=_ALLOWED_POSTHOG_EVENTS))
        .exclude(name__in=exclude)
        .order_by(F("last_seen_at").desc(nulls_last=True))
        .values_list("name", flat=True)[:EVENT_DEFINITIONS_LIMIT]
    )


def used_trigger_events(team: Team) -> set[str]:
    used: set[str] = set()
    for trigger in HogFlow.objects.filter(team_id=team.id).exclude(status="archived").values_list("trigger", flat=True):
        filters = (trigger or {}).get("filters") or {}
        for event in filters.get("events") or []:
            if isinstance(event, dict) and isinstance(event.get("id"), str):
                used.add(event["id"])
    return used


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
    for integration in Integration.objects.filter(team_id=team.id, kind="email").order_by("created_at"):
        config = integration.config or {}
        if config.get("verified") is True and config.get("email"):
            return EmailSender(
                integration_id=integration.id, email=str(config["email"]), name=str(config.get("name") or "")
            )
    return None


def email_templates(team: Team) -> tuple[EmailTemplateContent, ...]:
    return tuple(list_email_templates(team.id, limit=_TEMPLATES_LIMIT))
