from datetime import UTC, datetime
from typing import Any, cast

from django import forms
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

import structlog

from posthog.admin.admins.team_admin import TeamAdmin
from posthog.admin.console.bridge import AdminViewBridge
from posthog.admin.console.panels import Fact, Operation, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Page, Row, Table
from posthog.helpers.impersonation import is_impersonated
from posthog.models.team.team import Team
from posthog.models.user import User

from products.workflows.backend.facade.api import (
    ensure_workflows_config,
    get_email_sending_state,
    get_email_sending_tier_limits,
    max_email_sending_tier,
    recompute_email_sending_tier,
    set_email_sending_tier,
)
from products.workflows.backend.facade.contracts import SesEventsDlqMessage, SesEventsDlqState
from products.workflows.backend.facade.ses_events_dlq import inspect_ses_events_dlqs

logger = structlog.get_logger(__name__)

WORKFLOWS = Owner(name="Workflows", crest="workflows")


class SuspendEmailSendingForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), help_text="The team sees this reason in their notification."
    )


TIER_HOLD_REASONS = {
    "too_soon": "it has not held its current tier for the required number of days yet",
    "tier_not_used_enough": "it has not used enough of its current tier's daily allowance "
    "on enough separate days since the tier was set",
    "demotion_cooldown": "a recent demotion's cooldown is still active",
    "rates_recovering": "its complaint or bounce rate over the promotion window is not clean yet",
    "ses_reputation_not_clean": "AWS currently flags its SES tenant reputation",
    "already_top_tier": "it is already at the top tier",
}


class SetEmailSendingTierForm(forms.Form):
    tier = forms.TypedChoiceField(coerce=int, choices=())
    pinned = forms.BooleanField(required=False, label="Pin the tier, so the daily recompute does not move it")
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        choices = []
        for tier in range(max_email_sending_tier() + 1):
            limits = get_email_sending_tier_limits(tier)
            choices.append((tier, f"Tier {tier}: up to {limits.per_day:,} emails a day"))
        cast(forms.TypedChoiceField, self.fields["tier"]).choices = choices


def set_tier(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    tier = form.cleaned_data["tier"]
    pinned = form.cleaned_data["pinned"]
    set_email_sending_tier(
        obj.pk,
        tier=tier,
        pinned=pinned,
        user_id=cast(User, request.user).pk,
        was_impersonated=is_impersonated(request),
    )
    pin_note = " and pinned it there" if pinned else " (unpinned, so it can move automatically)"
    messages.success(request, f"Set the email sending tier to {tier}{pin_note}.")
    return None


def recompute_tier(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    # The sweep skips a team without a config row, and a team that only sent through the API may have none yet.
    ensure_workflows_config(obj.pk)
    try:
        decision = recompute_email_sending_tier(
            obj.pk, user_id=cast(User, request.user).pk, was_impersonated=is_impersonated(request)
        )
    except Exception:
        logger.exception("admin_console_recompute_email_sending_tier_failed", team_id=obj.pk)
        messages.error(request, "Could not recompute the tier. Check the logs.")
        return HttpResponse(status=500)
    if decision is None:
        messages.info(request, "The team was not evaluated: it is pinned, or its config changed while recomputing.")
    elif not decision.changed:
        explanation = TIER_HOLD_REASONS.get(decision.reason, f"decision reason: {decision.reason}")
        messages.info(request, f"The team keeps tier {decision.previous_tier}: {explanation}.")
    else:
        messages.success(
            request,
            f"The team moved from tier {decision.previous_tier} to tier {decision.new_tier} ({decision.reason}).",
        )
    return None


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
        tier_operations = [
            Operation(
                key="set-tier",
                label="Set sending tier",
                handler=set_tier,
                danger=True,
                description="Changes the team's daily email limit. A lower tier sends less.",
                form_class=SetEmailSendingTierForm,
                undo_hint="To undo, set the previous tier again.",
                form_initial={
                    "tier": state.tier if state is not None else 0,
                    "pinned": state is not None and state.tier_pinned,
                },
            ),
            Operation(
                key="recompute-tier",
                label="Recompute tier",
                handler=recompute_tier,
                danger=True,
                description="Runs the daily tier check now. It can lower the team's limits as well as raise them.",
                form_class=ReasonForm,
                undo_hint="To undo a lower tier, set the tier back with Set sending tier and pin it.",
            ),
        ]
        if state is not None and state.suspended_at is not None:
            return [
                Operation(
                    key="unsuspend",
                    label="Re-enable sending",
                    handler=AdminViewBridge(Team, TeamAdmin.unsuspend_email_sending_view),
                    description="Workers pick this up within a few minutes. The team gets an email and a notification.",
                ),
                *tier_operations,
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
            ),
            *tier_operations,
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
    # The ID comes from an unverified tracking code, and the team route refuses a negative ID, so
    # linking one would fail the whole page.
    if team_id < 1:
        return Cell(text=str(team_id))
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
