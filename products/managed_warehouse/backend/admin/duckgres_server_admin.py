from django import forms
from django.contrib import admin
from django.http import HttpRequest
from django.utils.safestring import SafeString

from posthog.admin.console.moved import MovedToConsole

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

    def get_fieldsets(self, request: HttpRequest, obj: DuckgresServer | None = None) -> tuple:
        return self.add_fieldsets if obj is None else self.change_fieldsets
