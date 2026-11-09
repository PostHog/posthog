from typing import cast

from django import forms
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse

from posthog.admin.console.panels import Fact, Operation, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, Notice, Page, Row, Secret, Table
from posthog.models.user import User

from products.managed_warehouse.backend.facade.contracts import StaffActionOutcome
from products.managed_warehouse.backend.facade.staff import (
    deprovision_for_staff,
    get_duckgres_server_summary,
    onboard_team_for_staff,
    preview_provision_for_staff,
    provision_for_staff,
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


class ProvisionForm(forms.Form):
    team_id = forms.IntegerField(
        label="First team ID", min_value=1, help_text="The team must belong to this organization."
    )
    database_name = forms.CharField(
        help_text=(
            "Becomes the subdomain of the connection host. 3 to 63 characters: lowercase letters, numbers and "
            "hyphens, starting with a letter."
        )
    )
    schema_name = forms.CharField(
        help_text=(
            "The team's schema in the warehouse. Lowercase letters, numbers and underscores. The schema name "
            "cannot be changed later."
        )
    )
    internal_only = forms.BooleanField(
        label="Internal testing",
        required=False,
        help_text=(
            "Loads the team's existing data in the background. Keep the managed-warehouse-trino-query flag off "
            "while testing, and turn it on to give the customer access to the loaded warehouse."
        ),
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


def preview_provision(request: HttpRequest, obj: Model, form: forms.Form) -> Page:
    data = form.cleaned_data
    preview = preview_provision_for_staff(obj.pk, data["team_id"], data["database_name"])
    if preview.problem is not None:
        form.add_error("team_id", preview.problem)
        return Page(blocks=())
    return Page(
        blocks=(
            Notice(
                text=(
                    "This calls the control plane to create the warehouse, then saves its connection record and "
                    "the first team's row. Where no control plane is configured, it saves nothing."
                )
            ),
            Table(
                columns=("Setting", "Value"),
                rows=(
                    Row(cells=(Cell(text="First team"), Cell(text=f"{preview.team_name} ({data['team_id']})"))),
                    Row(cells=(Cell(text="Connection host"), Cell(text=preview.host, mono=True))),
                    Row(cells=(Cell(text="Schema name"), Cell(text=data["schema_name"], mono=True))),
                    Row(cells=(Cell(text="Internal testing"), Cell(text="Yes" if data["internal_only"] else "No"))),
                ),
            ),
        )
    )


def provision(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    user = cast(User, request.user)
    data = form.cleaned_data
    outcome = provision_for_staff(
        obj.pk,
        data["team_id"],
        data["database_name"],
        data["schema_name"],
        internal_only=data["internal_only"],
        actor_email=user.email,
        actor_distinct_id=str(user.distinct_id),
    )
    if outcome.login is None:
        return _report(request, outcome)
    login = outcome.login
    blocks: list[Notice | Table | Secret] = [
        Notice(
            text=f"Provisioned a managed warehouse for this organization, with team {data['team_id']} as its first team."
        ),
    ]
    if data["internal_only"]:
        blocks.append(
            Notice(
                text=(
                    "Background loading is on. Data loading starts when the warehouse is ready. Customer access "
                    "follows the managed-warehouse-trino-query flag."
                )
            )
        )
    blocks.append(
        Table(
            columns=("Connection", "Value"),
            rows=tuple(
                Row(cells=(Cell(text=label), Cell(text=value, mono=True)))
                for label, value in (
                    ("Host", login.host),
                    ("Port", str(login.port)),
                    ("Database", login.database),
                    ("Username", login.username),
                )
            ),
        )
    )
    if login.password:
        blocks.append(
            Secret(
                label="Root password",
                value=login.password,
                note=(
                    "Copy it now. The control plane returns it only once and then stores it encrypted, so it cannot "
                    "be shown again. If it is lost, re-provision the warehouse or rotate its credentials."
                ),
            )
        )
    else:
        blocks.append(
            Notice(
                text=(
                    "The control plane did not return a password. Get the credentials through the control plane "
                    "or the 1Password onboarding flow."
                )
            )
        )
    return Page(blocks=tuple(blocks))


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
        return [
            Fact(label="Status", value="Provisioned", tone=Tone.SUCCESS),
            Fact(label="Server", value=server.host, mono=True),
            Fact(label="Bucket", value=server.bucket or "Not recorded yet", mono=bool(server.bucket)),
            Fact(label="Internal testing", value="Yes" if server.internal_testing else "No"),
        ]

    def operations(self, obj: Model) -> list[Operation]:
        provision_operation = Operation(
            key="provision",
            label="Provision warehouse",
            handler=provision,
            danger=True,
            form_class=ProvisionForm,
            preview=preview_provision,
            description=(
                "Calls the control plane to create this organization's managed warehouse with its first team, like "
                "the in-product provision. The organization's feature flag is not required. The result page shows "
                "the root password once."
            ),
            undo_hint=(
                "Deprovision the warehouse to tear it down. The schema name cannot be changed later, and the root "
                "password is shown only on the next page."
            ),
        )
        server = get_duckgres_server_summary(obj.pk)
        if server is None:
            return [provision_operation]
        return [
            provision_operation,
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
            Operation(
                key="deprovision",
                label="Deprovision warehouse",
                handler=deprovision,
                danger=True,
                form_class=ReasonForm,
                description=(
                    f"Calls the control plane to tear down this organization's managed warehouse on {server.host}. "
                    "The control plane team rows are removed."
                ),
                undo_hint=(
                    "This cannot be undone. The connection record stays in Django admin. Delete it there if needed."
                ),
            ),
        ]
