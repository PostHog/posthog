from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from products.workflows.backend.models import SandboxSenderOrganizationBlock


@admin.register(SandboxSenderOrganizationBlock)
class SandboxSenderOrganizationBlockAdmin(admin.ModelAdmin):
    list_display = ("organization", "reason", "created_by", "created_at")
    fields = ("organization", "reason", "created_by", "created_at")
    search_fields = ("organization__id", "organization__name")
    raw_id_fields = ("organization", "created_by")
    list_select_related = ("organization", "created_by")

    def get_readonly_fields(
        self, request: HttpRequest, obj: SandboxSenderOrganizationBlock | None = None
    ) -> tuple[str, ...]:
        if obj is not None:
            return ("organization", "created_by", "created_at")
        return ("created_at",)

    def get_changeform_initial_data(self, request: HttpRequest) -> dict[str, Any]:
        return {**super().get_changeform_initial_data(request), "created_by": request.user.pk}

    def get_form(
        self,
        request: HttpRequest,
        obj: SandboxSenderOrganizationBlock | None = None,
        change: bool = False,
        **kwargs: Any,
    ) -> Any:
        form_class = super().get_form(request, obj, change=change, **kwargs)
        if obj is not None:
            return form_class
        staff_member = request.user

        class AddBlockForm(form_class):  # type: ignore[valid-type,misc]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                self.fields["created_by"].disabled = True

            def clean_created_by(self) -> Any:
                return staff_member

        return AddBlockForm
