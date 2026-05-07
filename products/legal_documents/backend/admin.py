from typing import IO, Any, cast

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.core.validators import FileExtensionValidator
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

import structlog

from posthog.cloud_utils import is_cloud, is_dev_mode
from posthog.exceptions_capture import capture_exception
from posthog.storage import object_storage

from . import slack as slack_notifier
from .models import LegalDocument
from .storage import signed_pdf_storage_key

logger = structlog.get_logger(__name__)

# 25 MiB. PandaDoc-signed PDFs are ~100 KiB; counter-signed scans uploaded by sales
# can be larger but rarely come close to this. Anything bigger is almost certainly
# the wrong file.
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class LegalDocumentAdminForm(forms.ModelForm):
    """
    Admin upload form for documents signed outside the PandaDoc flow (sales /
    legal-ops dropping a counter-signed PDF). The PDF lives in object storage
    under the same key the public download endpoint already serves from, so the
    customer can download it via /api/.../legal_documents/{id}/download just
    like a PandaDoc-originated row.
    """

    signed_pdf = forms.FileField(
        required=True,
        validators=[FileExtensionValidator(allowed_extensions=["pdf"])],
        help_text="Counter-signed PDF (max 25 MiB). The row will be created with status='signed'.",
    )

    class Meta:
        model = LegalDocument
        fields = (
            "organization",
            "document_type",
            "company_name",
            "company_address",
            "representative_email",
        )

    def clean_signed_pdf(self) -> UploadedFile:
        pdf: UploadedFile = self.cleaned_data["signed_pdf"]
        if pdf.size and pdf.size > _MAX_UPLOAD_BYTES:
            raise ValidationError(f"PDF is too large ({pdf.size} bytes). Limit is {_MAX_UPLOAD_BYTES} bytes.")

        # Browsers populate content_type from the multipart upload; we only reject
        # obvious mismatches. The .pdf extension validator above is the primary check.
        if pdf.content_type and pdf.content_type != "application/pdf":
            raise ValidationError(f"File must be a PDF (got content-type {pdf.content_type!r}).")

        return pdf


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

    # Change view stays read-only — customer-submitted content can't be quietly
    # rewritten. The add view uses LegalDocumentAdminForm fields directly.
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

    add_fieldsets = (
        (
            "Upload signed document",
            {
                "description": (
                    "Use this form when a document was signed outside the PandaDoc flow "
                    "(e.g., counter-signed offline, DocuSign, or an MSA negotiated by sales). "
                    "The row is saved as 'signed' and the PDF goes to object storage at the "
                    "same key the customer-facing download endpoint reads from."
                ),
                "fields": (
                    "organization",
                    "document_type",
                    "company_name",
                    "company_address",
                    "representative_email",
                    "signed_pdf",
                ),
            },
        ),
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

    def get_fieldsets(self, request: HttpRequest, obj: LegalDocument | None = None) -> Any:
        if obj is None:
            return self.add_fieldsets
        return self.fieldsets

    def get_form(
        self, request: HttpRequest, obj: LegalDocument | None = None, change: bool = False, **kwargs: Any
    ) -> Any:
        # Add view uses LegalDocumentAdminForm (with the required signed_pdf
        # FileField). The change view falls back to Django's default ModelForm
        # for the model — `signed_pdf` is a non-model class attribute, so it
        # would otherwise be inherited by modelform_factory's subclass and
        # block "Save" with a "This field is required" error even though the
        # change view renders no upload widget.
        if obj is None:
            kwargs["form"] = LegalDocumentAdminForm
        return super().get_form(request, obj, change, **kwargs)

    def get_readonly_fields(
        self, request: HttpRequest, obj: LegalDocument | None = None
    ) -> tuple[str, ...] | list[str]:
        # On the change view every customer-submitted field is read-only so it
        # can't be quietly rewritten. On the add view (obj is None) the upload
        # form needs the fields to be editable so return an empty tuple.
        if obj is None:
            return ()
        return self.readonly_fields

    def has_add_permission(self, request: HttpRequest) -> bool:
        return bool(request.user and request.user.is_staff)

    def has_delete_permission(self, request: HttpRequest, obj: LegalDocument | None = None) -> bool:
        # Needed so admins can clear an existing row (the unique-per-org-per-type
        # constraint blocks re-uploads otherwise). Best-effort S3 cleanup runs
        # alongside the row delete.
        return bool(request.user and request.user.is_staff)

    def save_model(self, request: HttpRequest, obj: LegalDocument, form: Any, change: bool) -> None:
        if change:
            super().save_model(request, obj, form, change)
            return

        # Add path: row + S3 upload happen together so we never leave a row
        # pointing at a missing PDF (and never leave a PDF without a row).
        obj.status = LegalDocument.Status.SIGNED
        obj.created_by = request.user if request.user.is_authenticated else None
        try:
            with transaction.atomic():
                obj.save()
                pdf: UploadedFile = form.cleaned_data["signed_pdf"]
                try:
                    object_storage.write_stream(
                        signed_pdf_storage_key(obj),
                        cast(IO[bytes], pdf),
                        extras={"ContentType": "application/pdf"},
                    )
                except Exception as exc:
                    logger.exception(
                        "legal_document_admin_upload_failed",
                        document_id=str(obj.id),
                        error=str(exc),
                    )
                    raise ValidationError(f"Failed to upload PDF to object storage: {exc}") from exc
        except IntegrityError as exc:
            # Surface the unique-per-org-per-type constraint as a form error
            # instead of a 500.
            raise ValidationError(
                f"This organization already has a {obj.document_type}. Delete the existing row first."
            ) from exc

        try:
            # AnonymousUser has no .email attribute; staff-only gating means we
            # always have an authenticated User here, but mypy can't narrow
            # request.user across has_add_permission, so use getattr.
            slack_notifier.notify_admin_uploaded(
                document_type=obj.document_type,
                company_name=obj.company_name,
                uploaded_by_email=getattr(request.user, "email", "") or "",
            )
        except Exception as exc:
            # Slack errors must never break the admin save — the row + PDF are
            # already persisted at this point.
            logger.exception("legal_document_slack_admin_upload_notify_failed", error=str(exc))
            capture_exception(exc, additional_properties={"legal_document_id": str(obj.id)})

    def delete_model(self, request: HttpRequest, obj: LegalDocument) -> None:
        self._delete_signed_pdf(obj)
        super().delete_model(request, obj)

    def delete_queryset(self, request: HttpRequest, queryset: Any) -> None:
        for obj in queryset:
            self._delete_signed_pdf(obj)
        super().delete_queryset(request, queryset)

    @staticmethod
    def _delete_signed_pdf(obj: LegalDocument) -> None:
        try:
            object_storage.delete(signed_pdf_storage_key(obj))
        except Exception as exc:
            # Best effort — the row is going away regardless. Worst case a stale
            # PDF lingers in S3 with no row referencing it.
            logger.warning(
                "legal_document_admin_pdf_delete_failed",
                document_id=str(obj.id),
                error=str(exc),
            )

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
