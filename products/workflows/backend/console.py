from typing import Any, cast

from django import forms
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

import structlog

from posthog.admin.console.panels import Fact, Operation, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Page, Row, Table
from posthog.helpers.impersonation import is_impersonated
from posthog.models.user import User

from products.workflows.backend.facade.activity import (
    EMAIL_SENDING_SUSPENDED_ACTIVITY,
    EMAIL_SENDING_TIER_BACKFILL_JOB_TYPE,
    EMAIL_SENDING_TIER_SWEEP_JOB_TYPE,
    EMAIL_SENDING_UNSUSPENDED_ACTIVITY,
    list_email_sending_history,
)
from products.workflows.backend.facade.api import (
    ensure_workflows_config,
    get_email_sending_state,
    get_email_sending_tier_limits,
    max_email_sending_tier,
    recompute_email_sending_tier,
    set_email_sending_tier,
    suspend_email_sending,
    unsuspend_email_sending,
)
from products.workflows.backend.facade.contracts import EmailSendingHistoryEntry

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
        staff_note=form.cleaned_data["reason"],
        user_id=cast(User, request.user).pk,
        was_impersonated=is_impersonated(request),
    )
    pin_note = " and pinned it there" if pinned else " (unpinned, so it can move automatically)"
    messages.success(request, f"Set the email sending tier to {tier}{pin_note}.")
    return None


def recompute_tier(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    # The sweep skips a team without a config row, and a team that only sent through the API may have none yet.
    ensure_workflows_config(obj.pk)
    try:
        decision = recompute_email_sending_tier(
            obj.pk,
            staff_note=form.cleaned_data["reason"],
            user_id=cast(User, request.user).pk,
            was_impersonated=is_impersonated(request),
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


def suspend(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    change = suspend_email_sending(
        obj.pk,
        form.cleaned_data["reason"],
        user_id=cast(User, request.user).pk,
        was_impersonated=is_impersonated(request),
    )
    if change.previously_suspended_at is not None:
        messages.info(
            request, f"Email sending was already suspended, since {change.previously_suspended_at.isoformat()}."
        )
        return None
    if change.notification_failed:
        messages.error(
            request,
            "Suspended email sending, but the email or the notification to the team failed. "
            "Check the logs and tell the team yourself.",
        )
        return HttpResponse(status=500)
    messages.warning(
        request, "Suspended workflow email sending. Workers pick this up within a few minutes. The team was told."
    )
    return None


def unsuspend(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    change = unsuspend_email_sending(
        obj.pk, user_id=cast(User, request.user).pk, was_impersonated=is_impersonated(request)
    )
    if change.changed_at is None:
        messages.info(request, "Email sending is not suspended.")
        return None
    if change.notification_failed:
        messages.error(
            request,
            "Re-enabled email sending, but the email or the notification to the team failed. "
            "Check the logs and tell the team yourself.",
        )
        return HttpResponse(status=500)
    messages.success(request, "Re-enabled workflow email sending. The team was told.")
    return None


HISTORY_LIMIT = 200

TIER_CHANGE_REASONS = {
    "staff_set": "Set by staff",
    "staff_suspension": "Staff suspended sending",
    "clean_and_used": "Sent cleanly and used its allowance",
    "rates_above_threshold": "Bounce or complaint rate over the limit",
    "workflow_auto_paused": "A workflow was paused automatically",
    "ses_reputation_high": "AWS flagged the sender reputation",
    "ses_tenant_paused": "AWS paused sending for this team",
    "inactive": "No email sent for a long time",
}

JOB_NAMES = {
    EMAIL_SENDING_TIER_SWEEP_JOB_TYPE: "Daily tier check",
    EMAIL_SENDING_TIER_BACKFILL_JOB_TYPE: "Tier backfill",
}


def email_sending_history_url(team_id: int) -> str:
    return f"{reverse('admin_console_tool', kwargs={'tool_key': EmailSendingHistoryTool.key})}?team={team_id}"


def _change_cell(entry: EmailSendingHistoryEntry) -> Cell:
    if entry.activity == EMAIL_SENDING_SUSPENDED_ACTIVITY:
        return Cell(text="Suspended sending", tone=Tone.DESTRUCTIVE)
    if entry.activity == EMAIL_SENDING_UNSUSPENDED_ACTIVITY:
        return Cell(text="Re-enabled sending", tone=Tone.SUCCESS)
    parts = []
    tone = None
    if entry.tier_before is not None and entry.tier_after is not None:
        parts.append(f"Tier {entry.tier_before} → {entry.tier_after}")
        tone = Tone.WARNING if entry.tier_after < entry.tier_before else Tone.SUCCESS
    if entry.pinned_after is not None:
        parts.append("Pinned" if entry.pinned_after else "Unpinned")
    return Cell(text=", ".join(parts) or "No change recorded", tone=tone)


def _reason_cell(entry: EmailSendingHistoryEntry) -> Cell:
    return Cell(text=TIER_CHANGE_REASONS.get(entry.reason, entry.reason) or "-", muted=not entry.reason)


def _actor_cell(entry: EmailSendingHistoryEntry) -> Cell:
    if entry.actor_email is not None:
        return Cell(text=f"{entry.actor_email}{' (impersonated)' if entry.was_impersonated else ''}")
    if entry.job_type is not None:
        return Cell(text=JOB_NAMES.get(entry.job_type, entry.job_type), muted=True)
    return Cell(text="Automatic", muted=True)


def _history_row(entry: EmailSendingHistoryEntry) -> Row:
    return Row(
        cells=(
            Cell(text=entry.changed_at.strftime("%b %-d, %Y %H:%M UTC")),
            _change_cell(entry),
            _reason_cell(entry),
            Cell(text=entry.staff_note) if entry.staff_note else Cell(text="-", muted=True),
            _actor_cell(entry),
        )
    )


@console.register_tool
class EmailSendingHistoryTool(ConsoleTool):
    key = "email-sending-history"
    title = "Email sending history"
    owner = WORKFLOWS
    group = "Product data"
    description = "Every tier, pin and suspension change for one team, newest first."

    def page(self, request: HttpRequest) -> Page:
        team_param = request.GET.get("team", "")
        if not (team_param.isascii() and team_param.isdigit()):
            return Page(
                blocks=(
                    Notice(
                        text="Open this page from the Email sending panel on a team page to see that team's changes."
                    ),
                )
            )
        team_id = int(team_param)
        entries = list_email_sending_history(team_id, limit=HISTORY_LIMIT)
        limit_note = f" Showing the {HISTORY_LIMIT} most recent." if len(entries) == HISTORY_LIMIT else ""
        return Page(
            blocks=(
                Notice(
                    text=f"Team {team_id}.{limit_note}",
                    link_text="Back to the team",
                    href=reverse("admin_console_team", kwargs={"pk": team_id}),
                ),
                Table(
                    columns=("When", "Change", "Reason", "Staff note", "By"),
                    rows=tuple(_history_row(entry) for entry in entries),
                    empty_text="No changes recorded for this team yet.",
                ),
            )
        )


@console.register_panel
class EmailSendingPanel(Panel):
    record = "team"
    key = "email-sending"
    title = "Email sending"
    owner = WORKFLOWS
    operation_keys = frozenset({"set-tier", "recompute-tier", "suspend", "unsuspend"})

    def facts(self, obj: Model) -> list[Fact]:
        state = get_email_sending_state(obj.pk)
        if state is not None and state.suspended_at is not None:
            status = Fact(label="Status", value="Suspended", tone=Tone.DESTRUCTIVE)
        elif state is not None and state.provider_paused:
            status = Fact(label="Status", value="Paused by AWS SES", tone=Tone.DESTRUCTIVE)
        else:
            status = Fact(label="Status", value="Sending enabled", tone=Tone.SUCCESS)
        facts = [status]
        if state is not None and state.suspended_at is not None:
            facts.append(Fact(label="Suspended at", value=state.suspended_at.strftime("%b %-d, %Y %H:%M UTC")))
            facts.append(Fact(label="Reason", value=state.suspension_reason or "No reason recorded"))
        if state is not None and state.provider_paused:
            facts.append(
                Fact(
                    label="AWS SES pause",
                    value="AWS paused this team's SES tenant. Re-enabling sending here does not lift it. "
                    "The tenant has to be reinstated in AWS.",
                    tone=Tone.WARNING,
                )
            )
            if state.provider_reputation_impact:
                facts.append(Fact(label="AWS reputation impact", value=state.provider_reputation_impact))
        if state is not None:
            facts.append(
                Fact(
                    label="Sending limit tier",
                    value=f"Tier {state.tier} of {max_email_sending_tier()}{', pinned by staff' if state.tier_pinned else ''}",
                )
            )
        facts.append(Fact(label="History", value="See every change", href=email_sending_history_url(obj.pk)))
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
                    handler=unsuspend,
                    description="Workers pick this up within a few minutes. The team gets an email and a notification.",
                ),
                *tier_operations,
            ]
        return [
            Operation(
                key="suspend",
                label="Suspend sending",
                handler=suspend,
                danger=True,
                description="Stops workflow email for this team. The team gets an email and a notification.",
                form_class=SuspendEmailSendingForm,
                undo_hint="To undo, use Re-enable sending in the Email sending panel.",
            ),
            *tier_operations,
        ]


# Old Django admin URLs of team actions that moved. Staff keep bookmarks to them, query parameters included.
for old, target in {
    "set-email-sending-tier": "email-sending/set-tier/",
    "recompute-email-sending-tier": "#panel-email-sending",
    "suspend-email-sending": "email-sending/suspend/",
    "unsuspend-email-sending": "#panel-email-sending",
}.items():
    console.register_moved_action(old_path=f"admin/posthog/team/<int:pk>/{old}/", record="team", target=target)
