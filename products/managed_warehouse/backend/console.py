from typing import cast

from django import forms
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse

from posthog.admin.console.panels import Fact, Operation, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.models.user import User

from products.managed_warehouse.backend.facade.contracts import StaffActionOutcome
from products.managed_warehouse.backend.facade.staff import (
    deprovision_for_staff,
    get_duckgres_server_summary,
    onboard_team_for_staff,
)

MANAGED_WAREHOUSE = Owner(name="Managed warehouse", crest="managed-warehouse")


class EnableBackfillForm(forms.Form):
    team_id = forms.IntegerField(label="Team ID", min_value=1, help_text="The team must belong to this organization.")
    schema_name = forms.CharField(
        help_text=(
            "Lowercase letters, numbers and underscores. Must be unique within the organization's warehouse. "
            "The schema name cannot be changed later."
        )
    )
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")


def _report(request: HttpRequest, outcome: StaffActionOutcome) -> HttpResponse | None:
    if outcome.ok:
        messages.success(request, outcome.message)
        return None
    messages.error(request, outcome.message)
    return HttpResponse(status=outcome.status_code if outcome.status_code >= 400 else 502)


def enable_backfill(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    user = cast(User, request.user)
    outcome = onboard_team_for_staff(
        obj.pk,
        form.cleaned_data["team_id"],
        form.cleaned_data["schema_name"].strip(),
        actor_email=user.email,
        actor_distinct_id=str(user.distinct_id),
    )
    return _report(request, outcome)


def deprovision(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    user = cast(User, request.user)
    outcome = deprovision_for_staff(obj.pk, actor_email=user.email, actor_distinct_id=str(user.distinct_id))
    return _report(request, outcome)


@console.register_panel
class ManagedWarehousePanel(Panel):
    record = "organization"
    key = "managed-warehouse"
    title = "Managed warehouse"
    owner = MANAGED_WAREHOUSE

    def facts(self, obj: Model) -> list[Fact]:
        server = get_duckgres_server_summary(obj.pk)
        if server is None:
            return [Fact(label="Status", value="Not provisioned")]
        if server.deprovisioned:
            status = Fact(label="Status", value="Deprovisioned", tone=Tone.WARNING)
        else:
            status = Fact(label="Status", value="Provisioned", tone=Tone.SUCCESS)
        return [
            status,
            Fact(label="Server", value=server.host, mono=True),
            Fact(label="Bucket", value=server.bucket or "Not recorded yet", mono=bool(server.bucket)),
            Fact(label="Internal testing", value="Yes" if server.internal_testing else "No"),
        ]

    def operations(self, obj: Model) -> list[Operation]:
        server = get_duckgres_server_summary(obj.pk)
        if server is None:
            return []
        deprovision_operation = Operation(
            key="deprovision",
            label="Deprovision warehouse",
            handler=deprovision,
            danger=True,
            form_class=ReasonForm,
            description=(
                f"Calls the control plane to tear down this organization's managed warehouse on {server.host}. "
                "The control plane team rows are removed."
            ),
            undo_hint="This cannot be undone. The connection record stays in Django admin. Delete it there if needed.",
        )
        # Deprovision stays on offer after teardown so staff can retry a run whose SQL connection cleanup failed.
        if server.deprovisioned:
            return [deprovision_operation]
        return [
            Operation(
                key="enable-backfill",
                label="Enable backfill for a team",
                handler=enable_backfill,
                danger=True,
                form_class=EnableBackfillForm,
                description=(
                    "Onboards another team onto this organization's warehouse with its own schema and enables "
                    "backfill for it, like the in-product onboarding. The organization's feature flag is not "
                    "required."
                ),
                undo_hint="This cannot be undone here. The team keeps its schema, and the schema name is permanent.",
            ),
            deprovision_operation,
        ]
