from typing import Any

from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

from posthog.cloud_utils import is_cloud, is_dev_mode

from .models import LegalDocument


class LegalDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "document_type",
        "company_name",
        "organization_link",
        "status",
        "pandadoc_link",
        "created_at",
    )
    list_display_links = ("id",)
    list_filter = ("document_type", "status", "created_at")
    search_fields = (
        "id",
        "company_name",
        "representative_email",
        "organization__name",
    )
    ordering = ("-created_at",)
    show_full_result_count = False
    list_select_related = ("organization", "created_by")

    # Only the signed URL is editable by admins. Everything else is read-only so
    # customer-submitted content can't be quietly rewritten.
    readonly_fields = (
        "id",
        "organization",
        "document_type",
        "company_name",
        "company_address",
        "representative_email",
        "status",
        "pandadoc_link",
        "created_by",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Document",
            {
                "fields": (
                    "id",
                    "organization",
                    "document_type",
                    "status",
                    "pandadoc_link",
                )
            },
        ),
        (
            "Customer details",
            {
                "fields": (
                    "company_name",
                    "company_address",
                    "representative_email",
                )
            },
        ),
        (
            "Audit",
            {"fields": ("created_by", "created_at", "updated_at")},
        ),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: LegalDocument | None = None) -> bool:
        return False

    def changelist_view(self, request: HttpRequest, extra_context: dict[str, Any] | None = None) -> HttpResponse:
        if not (is_cloud() or is_dev_mode()):
            messages.warning(
                request,
                "Legal documents are only generated on PostHog Cloud. On self-hosted "
                "deployments, listed rows (if any) are read-only historical records and "
                "the PandaDoc / Slack integrations are disabled.",
            )
        return super().changelist_view(request, extra_context=extra_context)

    def change_view(
        self, request: HttpRequest, object_id: str, form_url: str = "", extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        if not (is_cloud() or is_dev_mode()):
            messages.warning(
                request,
                "Legal documents are only generated on PostHog Cloud. On self-hosted "
                "deployments, listed rows (if any) are read-only historical records and "
                "the PandaDoc / Slack integrations are disabled.",
            )
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    @admin.display(description="Organization", ordering="organization__name")
    def organization_link(self, document: LegalDocument) -> SafeString:
        url = reverse("admin:posthog_organization_change", args=[document.organization_id])
        return format_html('<a href="{}">{}</a>', url, document.organization.name)

    @admin.display(description="PandaDoc", ordering="pandadoc_document_id")
    def pandadoc_link(self, document: LegalDocument) -> str | SafeString:
        if not document.pandadoc_document_id:
            return "—"
        return format_html(
            '<a href="https://app.pandadoc.com/a/#/documents/{id}" target="_blank" rel="noopener">{id}</a>',
            id=document.pandadoc_document_id,
        )
