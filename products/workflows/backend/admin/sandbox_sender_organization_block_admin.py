from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from products.workflows.backend.models import SandboxSenderOrganizationBlock


@admin.register(SandboxSenderOrganizationBlock)
class SandboxSenderOrganizationBlockAdmin(admin.ModelAdmin):
    list_display = ("organization", "reason", "created_by", "created_at")
    fields = ("organization", "reason", "created_by", "created_at")
    readonly_fields = ("created_at",)
    raw_id_fields = ("organization", "created_by")
    search_fields = ("organization__id", "organization__name", "reason")
    list_select_related = ("organization", "created_by")
    ordering = ("-created_at",)

    def get_readonly_fields(
        self, request: HttpRequest, obj: SandboxSenderOrganizationBlock | None = None
    ) -> tuple[str, ...]:
        if obj is None:
            return tuple(self.readonly_fields)
        return ("organization", "created_by", *self.readonly_fields)

    def get_changeform_initial_data(self, request: HttpRequest) -> dict[str, Any]:
        return {**super().get_changeform_initial_data(request), "created_by": request.user.pk}
