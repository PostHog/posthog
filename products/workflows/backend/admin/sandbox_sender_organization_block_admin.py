from typing import cast

from django.contrib import admin
from django.forms import ModelForm
from django.http import HttpRequest

from posthog.models.user import User

from products.workflows.backend.models import SandboxSenderOrganizationBlock


@admin.register(SandboxSenderOrganizationBlock)
class SandboxSenderOrganizationBlockAdmin(admin.ModelAdmin):
    list_display = ("organization", "reason", "created_by", "created_at")
    fields = ("organization", "reason", "created_by", "created_at")
    readonly_fields = ("created_by", "created_at")
    raw_id_fields = ("organization",)
    search_fields = ("organization__id", "organization__name", "reason")
    list_select_related = ("organization", "created_by")
    ordering = ("-created_at",)

    def save_model(
        self,
        request: HttpRequest,
        obj: SandboxSenderOrganizationBlock,
        form: ModelForm | None,
        change: bool,
    ) -> None:
        if not change:
            obj.created_by = cast(User, request.user)
        super().save_model(request, obj, form, change)
