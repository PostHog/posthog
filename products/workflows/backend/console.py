from datetime import UTC, datetime

from django import forms
from django.db.models import Model
from django.http import HttpRequest
from django.urls import reverse

from posthog.admin.admins.team_admin import TeamAdmin
from posthog.admin.console.bridge import AdminViewBridge
from posthog.admin.console.panels import Fact, Operation, Owner, Panel, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Page, Row, Table
from posthog.models.team.team import Team

from products.workflows.backend.facade.api import get_email_sending_state, max_email_sending_tier
from products.workflows.backend.facade.contracts import SesEventsDlqMessage, SesEventsDlqState
from products.workflows.backend.facade.ses_events_dlq import inspect_ses_events_dlqs

WORKFLOWS = Owner(name="Workflows", crest="workflows")


class SuspendEmailSendingForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), help_text="The team sees this reason in their notification."
    )


@console.register_panel
class EmailSendingPanel(Panel):
    record = "team"
    key = "email-sending"
    title = "Email sending"
    owner = WORKFLOWS

    def facts(self, obj: Model) -> list[Fact]:
        state = get_email_sending_state(obj.pk)
        if state is None or state.suspended_at is None:
            status = Fact(label="Status", value="Sending enabled", tone=Tone.SUCCESS)
        else:
            status = Fact(label="Status", value="Suspended", tone=Tone.DESTRUCTIVE)
        facts = [status]
        if state is not None and state.suspended_at is not None:
            facts.append(Fact(label="Suspended at", value=state.suspended_at.strftime("%b %-d, %Y %H:%M UTC")))
            facts.append(Fact(label="Reason", value=state.suspension_reason or "No reason recorded"))
        if state is not None:
            facts.append(
                Fact(
                    label="Sending limit tier",
                    value=f"Tier {state.tier} of {max_email_sending_tier()}{', pinned by staff' if state.tier_pinned else ''}",
                )
            )
        return facts

    def operations(self, obj: Model) -> list[Operation]:
        state = get_email_sending_state(obj.pk)
        if state is not None and state.suspended_at is not None:
            return [
                Operation(
                    key="unsuspend",
                    label="Re-enable sending",
                    handler=AdminViewBridge(Team, TeamAdmin.unsuspend_email_sending_view),
                    description="Workers pick this up within a few minutes. The team gets an email and a notification.",
                )
            ]
        return [
            Operation(
                key="suspend",
                label="Suspend sending",
                handler=AdminViewBridge(Team, TeamAdmin.suspend_email_sending_view),
                danger=True,
                description="Stops workflow email for this team. The team gets an email and a notification.",
                form_class=SuspendEmailSendingForm,
                undo_hint="To undo, use Re-enable sending in the Email sending panel.",
            )
        ]


REPLAY_NOTICE = (
    "These are SES delivery, bounce, complaint, open and click events that the CDP webhook failed to process. "
    "To post them to the webhook again, run python manage.py replay_ses_events_dlq --queue <name> --dry-run "
    "from a toolbox shell, then run it again without --dry-run. An event leaves its queue only when the webhook "
    "accepts it."
)
NO_QUEUES_NOTICE = "No dead-letter queue is configured for this region. Set SES_EVENTS_DLQ_URLS to show them here."
SAMPLE_NOTICE = "Up to 10 waiting events from each queue. Each team comes from the event's tracking code."
MISSING = Cell(text="-", muted=True)


def _age(since: datetime | None) -> Cell:
    if since is None:
        return MISSING
    minutes = int((datetime.now(UTC) - since).total_seconds() // 60)
    return Cell(text=f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min")


def _queue_row(state: SesEventsDlqState) -> Row:
    if state.error is not None:
        return Row(
            cells=(
                Cell(text=state.queue_name, mono=True),
                Cell(text=f"Could not read the queue: {state.error}", tone=Tone.DESTRUCTIVE),
                MISSING,
                MISSING,
            )
        )
    return Row(
        cells=(
            Cell(text=state.queue_name, mono=True),
            Cell(text=f"{state.waiting:,}", tone=Tone.WARNING if state.waiting else None),
            Cell(text=f"{state.in_flight:,}"),
            _age(state.oldest_sampled_at),
        )
    )


def _team(team_id: int | None) -> Cell:
    if team_id is None:
        return MISSING
    return Cell(text=str(team_id), href=reverse("admin_console_team", kwargs={"team_id": team_id}))


def _sample_row(queue_name: str, message: SesEventsDlqMessage) -> Row:
    return Row(
        cells=(
            Cell(text=queue_name, mono=True),
            Cell(text=message.event_type),
            _team(message.team_id),
            Cell(text=message.masked_recipient) if message.masked_recipient else MISSING,
            _age(message.dead_lettered_at),
            Cell(text="Yes") if message.replayable else Cell(text="No, not a signed SNS notification", muted=True),
        )
    )


@console.register_tool
class SesEventsDlqTool(ConsoleTool):
    key = "ses-events-dlq"
    title = "SES events dead-letter queues"
    owner = WORKFLOWS
    group = "Data"
    description = "SES events that the CDP webhook failed to process, and how to post them again."

    def page(self, request: HttpRequest) -> Page:
        states = inspect_ses_events_dlqs()
        if not states:
            return Page(blocks=(Notice(text=NO_QUEUES_NOTICE),))
        return Page(
            blocks=(
                Notice(text=REPLAY_NOTICE),
                Table(
                    columns=("Queue", "Waiting", "In flight", "Oldest in sample"),
                    rows=tuple(_queue_row(state) for state in states),
                ),
                Notice(text=SAMPLE_NOTICE),
                Table(
                    columns=("Queue", "Event", "Team", "Recipient", "Waiting for", "Replayable"),
                    rows=tuple(_sample_row(state.queue_name, message) for state in states for message in state.sample),
                    empty_text="No event is waiting in any queue.",
                ),
            )
        )
