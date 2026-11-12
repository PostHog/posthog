from typing import Any, cast

from django import forms
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse

import structlog

from posthog.admin.console.panels import Fact, Operation, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.helpers.impersonation import is_impersonated
from posthog.models.user import User

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


@console.register_panel
class EmailSendingPanel(Panel):
    record = "team"
    key = "email-sending"
    title = "Email sending"
    owner = WORKFLOWS
    operation_keys = frozenset({"set-tier", "recompute-tier", "suspend", "unsuspend"})

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
