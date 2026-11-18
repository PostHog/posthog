from typing import Any

from django.contrib import admin
from django.contrib.admin import ActionLocation
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

from posthog.admin.console.moved import MovedToConsole
from posthog.admin.inline_registry import register_admin_inline
from posthog.models.organization import Organization

from .models import LegalDocument


@admin.register(LegalDocument)
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

    # Customer-submitted content stays read-only, so it can't be quietly rewritten.
    readonly_fields = (
        "id",
        "organization",
        "document_type",
        "company_name",
        "company_address",
        "representative_email",
        "status",
        "pandadoc_link",
        "download_link",
        "staff_operations",
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
                    "download_link",
                    "staff_operations",
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
        # Staff upload a document signed outside PandaDoc with the Upload signed document operation in
        # PostHog Admin, which stores the PDF with the row. The old add URL redirects there.
        return False

    def has_delete_permission(self, request: HttpRequest, obj: LegalDocument | None = None) -> bool:
        # A delete must also remove PandaDoc's copy of a signed document and the AI opt-outs of a BAA, which the
        # Delete document operation in PostHog Admin does. The old <id>/delete/ URL redirects there, and this keeps
        # the raw delete view closed when that redirect is missing. A Django admin delete of an organization that
        # has documents is refused too, because the cascade would skip the same cleanup.
        return False

    def get_actions(
        self, request: HttpRequest, action_location: ActionLocation = ActionLocation.CHANGE_LIST
    ) -> dict[str, Any]:
        actions = super().get_actions(request, action_location=action_location)
        actions.pop("delete_selected", None)
        return actions

    @admin.display(description="Staff operations")
    def staff_operations(self, document: LegalDocument) -> SafeString:
        return MovedToConsole.action(
            "organization",
            document.organization,
            "legal-documents",
            "Upload, refetch PDF, re-send signing email, delete",
        )

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

    @admin.display(description="Signed PDF")
    def download_link(self, document: LegalDocument) -> str | SafeString:
        # The PDF only exists once the archive job has stored it. A row can be
        # `signed` a beat before that lands, so gate on the stored flag, not on
        # status, or the link would 404.
        if not document.signed_pdf_stored:
            return "—"
        url = f"/api/organizations/{document.organization_id}/legal_documents/{document.id}/download"
        return format_html('<a href="{}" target="_blank" rel="noopener">Download PDF</a>', url)


class LegalDocumentInline(admin.TabularInline):
    """List of an organization's legal documents on the Organization admin."""

    model = LegalDocument
    extra = 0
    show_change_link = True

    fields = (
        "document_type",
        "company_name",
        "status",
        "pandadoc_link",
        "download_link",
        "created_at",
    )
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request: HttpRequest, obj: Organization | None = None) -> bool:
        return False

    @admin.display(description="PandaDoc")
    def pandadoc_link(self, document: LegalDocument) -> str | SafeString:
        if not document.pandadoc_document_id:
            return "—"
        return format_html(
            '<a href="https://app.pandadoc.com/a/#/documents/{id}" target="_blank" rel="noopener">{id}</a>',
            id=document.pandadoc_document_id,
        )

    @admin.display(description="Signed PDF")
    def download_link(self, document: LegalDocument) -> str | SafeString:
        # Gate on the stored flag: a row can be `signed` before the archive job
        # lands the PDF, and the link would 404 until then.
        if not document.signed_pdf_stored:
            return "—"
        url = f"/api/organizations/{document.organization_id}/legal_documents/{document.id}/download"
        return format_html('<a href="{}" target="_blank" rel="noopener">Download PDF</a>', url)


# Surface this inline on core's Organization admin page without core importing the product.
# OrganizationAdmin pulls it in via get_inlines() — see posthog.admin.inline_registry.
register_admin_inline(Organization, LegalDocumentInline)
