from typing import cast

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.safestring import SafeString

from posthog.admin.console.moved import MovedToConsole
from posthog.models import User

from products.managed_warehouse.backend.logic.staff_actions import StaffActions
from products.managed_warehouse.backend.models import DuckgresServer


class DuckgresServerAdminForm(forms.ModelForm):
    new_trino_password = forms.CharField(
        label="New Trino password",
        help_text="Leave blank to keep the current Trino password.",
        widget=forms.PasswordInput(render_value=False),
        required=False,
        strip=False,
    )

    class Meta:
        model = DuckgresServer
        exclude = ("trino_password",)

    def save(self, commit: bool = True) -> DuckgresServer:
        server = super().save(commit=False)
        if password := self.cleaned_data.get("new_trino_password"):
            server.trino_password = password
        if commit:
            server.save()
        return server


@admin.register(DuckgresServer)
class DuckgresServerAdmin(admin.ModelAdmin):
    form = DuckgresServerAdminForm
    list_display = (
        "id",
        "organization_id",
        "host",
        "port",
        "flight_port",
        "database",
        "bucket",
        "internal_testing",
        "created_at",
        "updated_at",
    )
    search_fields = ("=organization__id", "host", "bucket")
    # bucket / bucket_region are control-plane-owned: provisioning persists them
    # and status_for() self-heals them on every read, so a manual admin edit
    # would just be overwritten. Show them, but read-only.
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "bucket",
        "bucket_region",
        "trino_password_configured",
        "console_actions",
    )
    raw_id_fields = ("organization",)

    # The template adds the provision button.
    change_list_template = "admin/managed_warehouse/duckgres_server/change_list.html"

    change_fieldsets = (
        (
            None,
            {
                "fields": ("id", "organization", "console_actions"),
            },
        ),
        (
            "Connection",
            {
                "fields": ("host", "port", "flight_port", "database", "username"),
            },
        ),
        (
            "DuckLake catalog connection",
            {
                "fields": ("catalog_host", "catalog_port", "catalog_database", "catalog_username"),
            },
        ),
        (
            "Trino connection",
            {
                "fields": ("trino_password_configured", "new_trino_password"),
            },
        ),
        (
            "Storage",
            {
                # The duckling's per-org S3 bucket. Control-plane-owned and
                # read-only: provisioning persists it and status_for() self-heals
                # it from the warehouse status, so it's shown for reference but not
                # editable here.
                "fields": ("bucket", "bucket_region"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "fields": ("organization",),
            },
        ),
        (
            "Connection",
            {
                "fields": ("host", "port", "flight_port", "database", "username", "password"),
            },
        ),
        (
            "DuckLake catalog connection",
            {
                "fields": ("catalog_host", "catalog_port", "catalog_database", "catalog_username", "catalog_password"),
            },
        ),
        (
            "Trino connection",
            {
                "fields": ("new_trino_password",),
            },
        ),
        (
            "Storage",
            {
                "fields": ("bucket", "bucket_region"),
            },
        ),
    )

    @admin.display(boolean=True, description="Trino password configured")
    def trino_password_configured(self, obj: DuckgresServer) -> bool:
        return bool(obj.trino_password)

    @admin.display(description="Actions")
    def console_actions(self, obj: DuckgresServer) -> SafeString:
        return MovedToConsole.action(
            "organization", obj.organization, "managed-warehouse", "Enable backfill and deprovision"
        )

    @admin.display(boolean=True, description="Internal testing")
    def internal_testing(self, obj: DuckgresServer) -> bool:
        from products.managed_warehouse.backend.facade.access import is_internal_warehouse  # noqa: PLC0415

        return is_internal_warehouse(obj.organization_id)

    def get_urls(self):
        custom_urls = [
            path(
                "provision/",
                self.admin_site.admin_view(self.provision_view),
                name="managed_warehouse_duckgresserver_provision",
            ),
        ]
        return custom_urls + super().get_urls()

    def get_fieldsets(self, request: HttpRequest, obj: DuckgresServer | None = None) -> tuple:
        return self.add_fieldsets if obj is None else self.change_fieldsets

    def provision_view(self, request: HttpRequest) -> HttpResponse:
        """Provision a brand-new managed warehouse for an org + its first team.

        Runs the same path as the in-product provision API: the duckgres control-plane
        /provision call (which creates the first team's control-plane row), then the
        DuckgresServer connection record. The org's feature flag is bypassed
        (require_enabled=False) so ops can provision before the org is entitled to the
        in-product UI.
        """
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])

        if not self.has_add_permission(request):
            raise PermissionDenied

        if request.method == "GET":
            return render(
                request,
                "admin/managed_warehouse/duckgres_server/provision_form.html",
                {**self.admin_site.each_context(request), "title": "Provision managed warehouse"},
            )

        actions = self._staff_actions(request)
        actions.track("provision", None)
        organization_id = request.POST.get("organization_id", "").strip()
        team_id = request.POST.get("team_id", "").strip()
        database_name = request.POST.get("database_name", "").strip()
        schema_name = request.POST.get("schema_name", "").strip()

        team = actions.resolve_team(organization_id, team_id)
        if isinstance(team, str):
            messages.error(request, team)
            return redirect(reverse("admin:managed_warehouse_duckgresserver_provision"))

        from products.managed_warehouse.backend.presentation import views as managed_warehouse  # noqa: PLC0415

        resp = managed_warehouse.provision(
            team.organization_id,
            database_name,
            team.id,
            schema_name,
            require_enabled=False,
            triggered_by=actions.audit_principal,
            internal_only=request.POST.get("internal_only") == "on",
        )
        if 200 <= resp.status_code < 300:
            actions.track("provision", resp.status_code)
            # The control plane returns the root password exactly once, in this
            # response; afterwards it's stored only encrypted and can't be read
            # back. Show it once here. It is deliberately kept out of the message
            # framework, which persists to the session/cookie store, and out of the
            # audit log, which records the action and the actor but never the credential.
            body = resp.data if isinstance(resp.data, dict) else {}
            return render(
                request,
                "admin/managed_warehouse/duckgres_server/provision_result.html",
                {
                    **self.admin_site.each_context(request),
                    "title": "Managed warehouse provisioned",
                    "internal_only": request.POST.get("internal_only") == "on",
                    "organization_id": str(team.organization_id),
                    "team_id": team.id,
                    "connection": managed_warehouse._present_connection(
                        {"database": database_name, "username": body.get("username", "root")}
                    ),
                    "password": body.get("password", ""),
                },
            )
        outcome = actions.outcome("provision", resp, f"Provisioned managed warehouse for org {team.organization_id}")
        messages.error(request, outcome.message)
        return redirect(reverse("admin:managed_warehouse_duckgresserver_provision"))

    def _staff_actions(self, request: HttpRequest) -> StaffActions:
        user = cast(User, request.user)
        return StaffActions(actor_email=user.email, actor_distinct_id=str(user.distinct_id))
