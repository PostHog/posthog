from django.contrib import admin
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

from products.warehouse_sources.backend.models import ExternalDataSource

type _FilterChoice = tuple[str, str]

_CREDENTIAL_KIND_CHOICES = (
    ("duckgres_service", "duckgres_service"),
    ("project_reader", "project_reader"),
    ("org_root", "org_root"),
    ("stored_server_login", "stored_server_login"),
)
_KNOWN_CREDENTIAL_KINDS = frozenset(value for value, _label in _CREDENTIAL_KIND_CHOICES)


class CredentialKindFilter(admin.SimpleListFilter):
    title = "credential kind"
    parameter_name = "credential_kind"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin) -> list[_FilterChoice]:
        return list(_CREDENTIAL_KIND_CHOICES)

    def queryset(self, request: HttpRequest, queryset: QuerySet[ExternalDataSource]) -> QuerySet[ExternalDataSource]:
        credential_kind = self.value()
        if credential_kind not in _KNOWN_CREDENTIAL_KINDS:
            return queryset
        return queryset.filter(connection_metadata__credential_kind=credential_kind)


class SystemManagedFilter(admin.SimpleListFilter):
    title = "system managed"
    parameter_name = "system_managed"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin) -> list[_FilterChoice]:
        return [("yes", "Yes"), ("no", "No")]

    def queryset(self, request: HttpRequest, queryset: QuerySet[ExternalDataSource]) -> QuerySet[ExternalDataSource]:
        if self.value() == "yes":
            return queryset.filter(connection_metadata__system_managed=True)
        if self.value() == "no":
            return queryset.filter(
                Q(connection_metadata__system_managed=False) | Q(connection_metadata__system_managed__isnull=True)
            )
        return queryset


@admin.register(ExternalDataSource)
class ExternalDataSourceAdmin(admin.ModelAdmin):
    actions = None
    show_full_result_count = False
    ordering = ("-id",)
    list_display = (
        "id",
        "credential_kind",
        "prefix",
        "source_type",
        "team_link",
        "organization_link",
        "deleted",
        "direct_query_enabled",
        "created_at",
        "updated_at",
    )
    list_display_links = ("id",)
    list_filter = (
        CredentialKindFilter,
        SystemManagedFilter,
        "deleted",
        "direct_query_enabled",
        "source_type",
        "access_method",
    )
    search_fields = (
        "id__exact",
        "source_id",
        "connection_id",
        "team__id__exact",
        "team__name",
        "team__organization__id__exact",
        "team__organization__name",
    )
    readonly_fields = (
        "id",
        "team_link",
        "organization_link",
        "source_id",
        "connection_id",
        "destination_id",
        "source_type",
        "prefix",
        "description",
        "status",
        "access_method",
        "direct_query_enabled",
        "are_tables_created",
        "created_via",
        "credential_kind",
        "system_managed",
        "lifecycle_generation",
        "deleted",
        "deleted_at",
        "created_at",
        "updated_at",
    )
    fields = readonly_fields

    def get_queryset(self, request: HttpRequest) -> QuerySet[ExternalDataSource]:
        return (
            super()
            .get_queryset(request)
            .select_related(None)
            .select_related("team", "team__organization")
            .defer("job_inputs")
        )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: ExternalDataSource | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: ExternalDataSource | None = None) -> bool:
        return False

    @admin.display(description="Credential kind", ordering="connection_metadata__credential_kind")
    def credential_kind(self, obj: ExternalDataSource) -> str:
        metadata = obj.connection_metadata
        value = metadata.get("credential_kind") if isinstance(metadata, dict) else None
        return value if value in _KNOWN_CREDENTIAL_KINDS else "Other"

    @admin.display(boolean=True, description="System managed")
    def system_managed(self, obj: ExternalDataSource) -> bool:
        metadata = obj.connection_metadata
        return isinstance(metadata, dict) and metadata.get("system_managed") is True

    @admin.display(description="Lifecycle generation")
    def lifecycle_generation(self, obj: ExternalDataSource) -> int | None:
        metadata = obj.connection_metadata
        value = metadata.get("lifecycle_generation") if isinstance(metadata, dict) else None
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @admin.display(description="Team")
    def team_link(self, obj: ExternalDataSource) -> SafeString:
        return format_html(
            '<a href="{}">{} ({})</a>',
            reverse("admin:posthog_team_change", args=[obj.team_id]),
            obj.team.name,
            obj.team_id,
        )

    @admin.display(description="Organization")
    def organization_link(self, obj: ExternalDataSource) -> SafeString:
        return format_html(
            '<a href="{}">{} ({})</a>',
            reverse("admin:posthog_organization_change", args=[obj.team.organization_id]),
            obj.team.organization.name,
            obj.team.organization_id,
        )
