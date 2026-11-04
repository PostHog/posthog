from django.db.models import Model

from posthog.admin.admins.team_admin import TeamAdmin
from posthog.admin.console.bridge import AdminViewBridge
from posthog.admin.console.panels import Fact, Operation, OperationField, Owner, Panel, Tone
from posthog.admin.console.registry import console
from posthog.models.team.team import Team

from products.workflows.backend.facade.api import get_email_sending_state

WORKFLOWS = Owner(name="Workflows", crest="workflows")


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
            facts.append(Fact(label="Tier", value=f"{state.tier}{' (pinned)' if state.tier_pinned else ''}"))
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
                fields=(
                    OperationField(
                        name="reason",
                        label="Reason",
                        help_text="The team sees this reason in their notification.",
                        multiline=True,
                    ),
                ),
            )
        ]
