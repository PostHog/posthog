from typing import Any

from django import forms
from django.contrib import admin
from django.http import HttpRequest

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

    def get_readonly_fields(
        self, request: HttpRequest, obj: SandboxSenderOrganizationBlock | None = None
    ) -> tuple[str, ...]:
        if obj is None:
            return tuple(self.readonly_fields)
        return ("organization", *self.readonly_fields)

    def get_form(
        self,
        request: HttpRequest,
        obj: SandboxSenderOrganizationBlock | None = None,
        change: bool = False,
        **kwargs: Any,
    ) -> type[forms.ModelForm]:
        form = super().get_form(request, obj, change, **kwargs)
        if obj is not None:
            return form
        author = request.user

        # The author is the signed-in staff user, set on the new row before the form validates,
        # so no posted value can name another user or leave the block without an author.
        class AuthoredBlockForm(form):  # type: ignore[valid-type,misc]
            def __init__(self, *args: Any, **form_kwargs: Any) -> None:
                super().__init__(*args, **form_kwargs)
                self.instance.created_by = author

        return AuthoredBlockForm
