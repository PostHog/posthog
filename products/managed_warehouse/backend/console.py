import re
from typing import cast
from uuid import UUID

from django import forms
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse

from posthog.admin.console.panels import Fact, Operation, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, Notice, Page, Row, Secret, Table
from posthog.models.user import User

from products.managed_warehouse.backend.facade.contracts import StaffActionOutcome, ViewTranslationSummary
from products.managed_warehouse.backend.facade.staff import (
    deprovision_for_staff,
    get_duckgres_server_summary,
    get_view_translation_summary,
    is_control_plane_configured,
    onboard_team_for_staff,
    preview_provision_for_staff,
    provision_for_staff,
    retry_view_translation_for_staff,
    start_trino_compile_check,
    start_view_translation_for_staff,
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


def _parse_view_ids(raw: str) -> list[UUID]:
    tokens = re.split(r"[\s,]+", raw.strip()) if raw.strip() else []
    try:
        return list(dict.fromkeys(UUID(token) for token in tokens))
    except ValueError:
        raise forms.ValidationError("Enter valid view IDs separated by commas or new lines.") from None


class StartViewTranslationForm(forms.Form):
    saved_query_ids = forms.CharField(
        label="View IDs",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="One saved view ID per line. Leave empty to translate every view in the organization.",
    )

    def clean_saved_query_ids(self) -> list[UUID]:
        return _parse_view_ids(self.cleaned_data["saved_query_ids"])


class RetryViewTranslationForm(forms.Form):
    job_id = forms.UUIDField(label="Job ID", help_text="The translation job whose failed or stale views to retry.")
    saved_query_ids = forms.CharField(
        label="View IDs",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="One saved view ID per line. Leave empty to retry every failed or stale view of the job.",
    )

    def clean_saved_query_ids(self) -> list[UUID]:
        return _parse_view_ids(self.cleaned_data["saved_query_ids"])


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


def start_view_translation(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    outcome = start_view_translation_for_staff(
        obj.pk, form.cleaned_data["saved_query_ids"], actor_user_id=cast(User, request.user).pk
    )
    return _report(request, outcome)


def retry_view_translation(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    outcome = retry_view_translation_for_staff(
        obj.pk,
        form.cleaned_data["job_id"],
        form.cleaned_data["saved_query_ids"],
        actor_user_id=cast(User, request.user).pk,
    )
    return _report(request, outcome)


def _view_translation_operations(translation: ViewTranslationSummary | None) -> list[Operation]:
    if translation is not None and translation.active:
        return []
    operations = [
        Operation(
            key="start-view-translation",
            label="Start view translation",
            handler=start_view_translation,
            form_class=StartViewTranslationForm,
            description=(
                "Starts a job that translates the organization's saved views for the managed warehouse and records "
                "a result for each view. The views themselves do not change."
            ),
        )
    ]
    if translation is not None and translation.retry_job_id is not None:
        operations.append(
            Operation(
                key="retry-view-translation",
                label="Retry failed view translations",
                handler=retry_view_translation,
                form_class=RetryViewTranslationForm,
                form_initial={"job_id": translation.retry_job_id},
                description="Starts a job that translates the failed or stale views of an earlier job again.",
            )
        )
    return operations


def deprovision(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    user = cast(User, request.user)
    outcome = deprovision_for_staff(obj.pk, actor_email=user.email, actor_distinct_id=str(user.distinct_id))
    return _report(request, outcome)


class CheckTrinoCompileForm(forms.Form):
    explain = forms.BooleanField(required=False, label="Also plan each query on Trino")
    limit = forms.IntegerField(
        required=False, min_value=1, help_text="Check at most this many saved queries. Leave empty to check all."
    )


def check_trino_compile(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    run_id = start_trino_compile_check(obj.pk, explain=form.cleaned_data["explain"], limit=form.cleaned_data["limit"])
    messages.success(
        request,
        f"Started Trino compile check {run_id}. Filter the trino_compile_check_result "
        f"and trino_compile_check_completed events on run_id = '{run_id}'.",
    )
    return None


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
            self._view_translation_fact(get_view_translation_summary(obj.pk)),
        ]

    @staticmethod
    def _view_translation_fact(translation: ViewTranslationSummary | None) -> Fact:
        if translation is None:
            return Fact(label="View translation", value="Never run")
        counts = (
            f"{translation.compiled_count} of {translation.total_count} compiled, "
            f"{translation.failed_count} failed, {translation.stale_count} stale"
        )
        tone = Tone.WARNING if translation.failed_count or translation.stale_count else None
        return Fact(label="View translation", value=f"{translation.latest_status}: {counts}", tone=tone)

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
        # After teardown staff can provision again, for example to change internal testing mode, and can retry a
        # deprovision whose SQL connection cleanup failed.
        if server.deprovisioned:
            return [provision_operation, deprovision_operation]
        return [
            provision_operation,
            *_view_translation_operations(get_view_translation_summary(obj.pk)),
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


@console.register_panel
class TrinoCompileCheckPanel(Panel):
    record = "team"
    key = "trino-compile-check"
    title = "Trino compile check"
    owner = MANAGED_WAREHOUSE

    def facts(self, obj: Model) -> list[Fact]:
        if is_control_plane_configured():
            return [Fact(label="Managed warehouse control plane", value="Configured", tone=Tone.SUCCESS)]
        return [Fact(label="Managed warehouse control plane", value="Not configured on this host", tone=Tone.WARNING)]

    def operations(self, obj: Model) -> list[Operation]:
        return [
            Operation(
                key="start",
                label="Start Trino compile check",
                handler=check_trino_compile,
                description="Compiles the team's saved queries to Trino SQL in a background task. "
                "The team sees nothing.",
                form_class=CheckTrinoCompileForm,
            )
        ]
