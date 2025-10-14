from django.contrib import admin
from django.utils.html import format_html

from products.tasks.backend.models import SandboxSnapshot


@admin.register(SandboxSnapshot)
class SandboxSnapshotAdmin(admin.ModelAdmin):
    list_display = ("external_id", "status", "repo_count", "integration_link", "created_at", "updated_at")
    list_filter = ("status", "created_at")
    search_fields = ("external_id", "repos")
    readonly_fields = ("id", "external_id", "created_at", "updated_at")
    autocomplete_fields = ("integration",)

    fieldsets = (
        (None, {"fields": ("id", "external_id", "integration", "status")}),
        ("Repository Info", {"fields": ("repos",)}),
        ("Metadata", {"fields": ("metadata",)}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )

    def repo_count(self, obj: SandboxSnapshot) -> int:
        return len(obj.repos)

    repo_count.short_description = "Repositories"

    def integration_link(self, obj: SandboxSnapshot) -> str:
        if obj.integration:
            return format_html(
                '<a href="/admin/posthog/integration/{}/change/">{}</a>',
                obj.integration.pk,
                obj.integration.kind,
            )
        return "-"

    integration_link.short_description = "Integration"
