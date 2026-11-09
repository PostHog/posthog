from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from products.workflows.backend.models import SandboxSenderOrganizationBlock


@admin.register(SandboxSenderOrganizationBlock)
class SandboxSenderOrganizationBlockAdmin(admin.ModelAdmin):
    """Staff stop an organization from sending through the sandbox sender by adding a row here."""

    list_display = ("organization", "reason", "created_by", "created_at")
    fields = ("organization", "reason", "created_by", "created_at")
    search_fields = ("organization__id", "organization__name")
    raw_id_fields = ("organization", "created_by")
    list_select_related = ("organization", "created_by")

    def get_readonly_fields(
        self, request: HttpRequest, obj: SandboxSenderOrganizationBlock | None = None
    ) -> tuple[str, ...]:
        # A block names one organization for good. Lifting it is a delete.
        if obj is not None:
            return ("organization", "created_by", "created_at")
        return ("created_at",)

    def get_changeform_initial_data(self, request: HttpRequest) -> dict[str, Any]:
        # The add form prefills the signed-in staff member, so the row records who blocked the
        # organization. A save hook would do the same, but admin pages stay plain CRUD.
        return {**super().get_changeform_initial_data(request), "created_by": request.user.pk}
