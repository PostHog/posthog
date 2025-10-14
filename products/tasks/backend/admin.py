from django.contrib import admin
from django.utils.html import format_html

from products.tasks.backend.models import SandboxSnapshot


class SandboxSnapshotAdmin(admin.ModelAdmin):
    list_display = ("external_id", "status", "integration_link", "created_at", "updated_at")
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

    def integration_link(self, obj: SandboxSnapshot) -> str:
        if obj.integration:
            return format_html(
                '<a href="/admin/posthog/integration/{}/change/">{}</a>',
                obj.integration.pk,
                obj.integration.kind,
            )
        return "-"
