from uuid import UUID

from django import forms
from django.contrib import messages
from django.contrib.admin.utils import unquote
from django.core.files.uploadedfile import UploadedFile
from django.core.validators import FileExtensionValidator
from django.db.models import Model
from django.http import HttpRequest, HttpResponse

from posthog.admin.console.moved import MovedRecord
from posthog.admin.console.panels import Fact, Operation, Owner, Panel, Tone
from posthog.admin.console.registry import console
from posthog.cloud_utils import is_cloud, is_dev_mode

from products.legal_documents.backend.facade.api import (
    can_refetch_signed_pdf,
    can_resend_signing_email,
    delete_as_staff,
    get_organization_id_for_staff,
    list_for_staff,
    refetch_signed_pdf,
    resend_signing_email,
    upload_signed_document_as_staff,
    uploadable_document_types,
)
from products.legal_documents.backend.facade.contracts import StaffLegalDocument, StaffSignedDocumentUpload
from products.legal_documents.backend.facade.enums import (
    LegalDocumentStatus,
    StaffRefetchOutcome,
    StaffResendOutcome,
    StaffUploadOutcome,
)

GROWTH = Owner(name="Growth", crest="growth")

# PandaDoc PDFs are far smaller. A file above this is almost certainly the wrong one.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

DELETE_DESCRIPTION = (
    "Removes the PostHog record. For a document that is out for signature, this voids its PandaDoc envelope, so the "
    "signer's link stops working. For a signed document, this also removes the stored PDF, and PandaDoc keeps its "
    "copy, because PandaDoc cannot void a completed document. Delete or archive it in PandaDoc yourself. For a BAA, "
    "the organization keeps AI data processing and AI training turned off after the delete."
)


def _status_text(document: StaffLegalDocument) -> str:
    if document.status != LegalDocumentStatus.SIGNED:
        return "Out for signature" if document.has_pandadoc_envelope else "Out for signature, no PandaDoc envelope"
    if document.signed_pdf_stored:
        return "Signed, PDF stored"
    return "Signed, PDF not stored yet"


def _document_label(document: StaffLegalDocument) -> str:
    return f"{document.document_type} from {document.created_at:%b %-d, %Y}"


def _document_form(documents: list[StaffLegalDocument], *, with_reason: bool) -> type[forms.Form]:
    choices = [(str(document.id), _document_label(document)) for document in documents]

    class DocumentForm(forms.Form):
        document = forms.ChoiceField(choices=choices)

    if not with_reason:
        return DocumentForm

    class DocumentWithReasonForm(DocumentForm):
        reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")

    return DocumentWithReasonForm


def _upload_form(document_types: list[str]) -> type[forms.Form]:
    class UploadSignedDocumentForm(forms.Form):
        document_type = forms.ChoiceField(choices=[(document_type, document_type) for document_type in document_types])
        company_name = forms.CharField(max_length=255)
        company_address = forms.CharField(max_length=512)
        representative_email = forms.EmailField()
        signed_pdf = forms.FileField(
            label="Signed PDF",
            widget=forms.FileInput(attrs={"accept": ".pdf"}),
            validators=[FileExtensionValidator(allowed_extensions=["pdf"])],
            help_text="The counter-signed PDF, at most 25 MB.",
        )

        def clean_signed_pdf(self) -> UploadedFile:
            pdf: UploadedFile = self.cleaned_data["signed_pdf"]
            if pdf.size and pdf.size > MAX_UPLOAD_BYTES:
                raise forms.ValidationError("The file is larger than 25 MB. Check that it is the signed PDF.")
            # The browser sets the content type from the upload. The extension check above is the main one,
            # so this only refuses an obvious mismatch.
            if pdf.content_type and pdf.content_type != "application/pdf":
                raise forms.ValidationError("The file is not a PDF. Upload the signed PDF.")
            return pdf

    return UploadSignedDocumentForm


def _selected_document(form: forms.Form | None) -> UUID:
    assert form is not None
    return UUID(form.cleaned_data["document"])


def refetch_pdf(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    outcome = refetch_signed_pdf(_selected_document(form), obj.pk)
    if outcome == StaffRefetchOutcome.STORED:
        messages.success(request, "Refetched the PDF from PandaDoc. The stored copy now matches PandaDoc.")
        return None
    if outcome == StaffRefetchOutcome.FAILED:
        messages.error(
            request,
            "Could not refetch the PDF from PandaDoc. PandaDoc may be unreachable, or object storage may be "
            "unavailable. The stored copy is unchanged. Check the logs and try again.",
        )
        return HttpResponse(status=502)
    messages.error(request, "PandaDoc has no final PDF for this document. Only a signed PandaDoc document has one.")
    return HttpResponse(status=409)


def resend_email(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    outcome = resend_signing_email(_selected_document(form), obj.pk)
    if outcome == StaffResendOutcome.SENT:
        messages.success(request, "Re-sent the signing email.")
        return None
    if outcome == StaffResendOutcome.FAILED:
        messages.error(
            request,
            "Could not re-send the signing email. PandaDoc may still be processing the template, or the envelope "
            "can no longer be sent. Check the logs and try again shortly.",
        )
        return HttpResponse(status=502)
    messages.error(request, "This document is signed or has no PandaDoc envelope, so there is no email to send.")
    return HttpResponse(status=409)


def upload_signed_document(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    # The console runs behind admin_view, so the user is a signed-in staff member with a primary key.
    user_id = request.user.pk
    assert user_id is not None
    document_type = form.cleaned_data["document_type"]
    upload = StaffSignedDocumentUpload(
        organization_id=obj.pk,
        created_by_id=user_id,
        document_type=document_type,
        company_name=form.cleaned_data["company_name"],
        company_address=form.cleaned_data["company_address"],
        representative_email=form.cleaned_data["representative_email"],
    )
    outcome = upload_signed_document_as_staff(upload, form.cleaned_data["signed_pdf"])
    if outcome == StaffUploadOutcome.STORED:
        messages.success(request, f"Uploaded the signed {document_type}. The customer can download it now.")
        return None
    if outcome == StaffUploadOutcome.ALREADY_EXISTS:
        messages.error(
            request, f"This organization already has a {document_type}. Delete it first, then upload the new one."
        )
        return HttpResponse(status=409)
    messages.error(
        request,
        "Could not store the PDF. Object storage may be unavailable. Nothing was saved. Check the logs and try again.",
    )
    return HttpResponse(status=502)


def delete_document(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    if not delete_as_staff(_selected_document(form), obj.pk):
        messages.error(request, "This document no longer exists.")
        return HttpResponse(status=404)
    messages.success(request, "Deleted the legal document.")
    return None


@console.register_panel
class LegalDocumentsPanel(Panel):
    record = "organization"
    key = "legal-documents"
    title = "Legal documents"
    owner = GROWTH
    operation_keys = frozenset({"upload-signed-document", "refetch-pdf", "resend-signing-email", "delete"})

    def facts(self, obj: Model) -> list[Fact]:
        documents = list_for_staff(obj.pk)
        facts: list[Fact] = []
        if not (is_cloud() or is_dev_mode()):
            facts.append(
                Fact(label="PandaDoc", value="Off, legal documents are only generated on Cloud", tone=Tone.WARNING)
            )
        if not documents:
            facts.append(Fact(label="Documents", value="None"))
        for document in documents:
            tone = Tone.SUCCESS if document.signed_pdf_stored else None
            facts.append(Fact(label=_document_label(document), value=_status_text(document), tone=tone))
        return facts

    def operations(self, obj: Model) -> list[Operation]:
        documents = list_for_staff(obj.pk)
        refetchable = [document for document in documents if can_refetch_signed_pdf(document)]
        sendable = [document for document in documents if can_resend_signing_email(document)]
        uploadable = uploadable_document_types(documents)
        operations: list[Operation] = []
        if uploadable:
            operations.append(
                Operation(
                    key="upload-signed-document",
                    label="Upload signed document",
                    handler=upload_signed_document,
                    form_class=_upload_form(uploadable),
                    description="For a document signed outside PandaDoc, such as a counter-signed MSA. Saves it as "
                    "signed, and the customer can download the PDF.",
                )
            )
        if refetchable:
            operations.append(
                Operation(
                    key="refetch-pdf",
                    label="Refetch PDF from PandaDoc",
                    handler=refetch_pdf,
                    danger=True,
                    form_class=_document_form(refetchable, with_reason=True),
                    description="Replaces the stored PDF with the one PandaDoc serves now. The customer downloads "
                    "the new copy.",
                    undo_hint="The old stored copy cannot be restored. Refetch again, or upload the right PDF.",
                )
            )
        if sendable:
            operations.append(
                Operation(
                    key="resend-signing-email",
                    label="Re-send signing email",
                    handler=resend_email,
                    form_class=_document_form(sendable, with_reason=False),
                    description="PandaDoc emails the signer the signing link again.",
                )
            )
        if documents:
            operations.append(
                Operation(
                    key="delete",
                    label="Delete document",
                    handler=delete_document,
                    danger=True,
                    form_class=_document_form(documents, with_reason=True),
                    description=DELETE_DESCRIPTION,
                    undo_hint="This cannot be undone. The customer can request a BAA or DPA again in organization "
                    "settings. Staff can upload a signed PDF again with Upload signed document.",
                )
            )
        return operations


def find_document_organization(object_id: str) -> MovedRecord | None:
    # Django admin unquotes the object ID and reads it as any spelling of a UUID (uppercase, without hyphens),
    # so this does the same, and no spelling of a document ID reaches the admin delete view.
    try:
        document_id = UUID(unquote(object_id))
    except ValueError:
        return None
    # The old document URLs carry only the document ID, so the organization is looked up to find the panel.
    organization_id = get_organization_id_for_staff(document_id)
    if organization_id is None:
        return None
    # The console form lists every document of the organization, so the ID preselects the one staff picked.
    return MovedRecord(pk=organization_id, query={"document": str(document_id)})


console.register_moved_action(
    old_path="admin/legal_documents/legaldocument/<path:object_id>/refetch-pdf/",
    record="organization",
    target="#panel-legal-documents",
    resolver=find_document_organization,
)
# The Delete button of the Django admin change page leads to the console operation, which says what a delete
# leaves behind: PandaDoc's copy of a signed document, and the AI opt-outs of a BAA. The pattern matches every
# object ID the admin delete route does, so a document is never deleted without that cleanup.
console.register_moved_action(
    old_path="admin/legal_documents/legaldocument/<path:object_id>/delete/",
    record="organization",
    target="legal-documents/delete/",
    resolver=find_document_organization,
)

# Staff added a signed document on the Django admin add page, which the organization page linked to with
# ?organization=<id>. That ID sits in the query, which a moved action cannot read, so the page leads home.
console.register_moved_page(
    old_path="admin/legal_documents/legaldocument/add/",
    title="Uploading a signed legal document",
    url="/admin/console/",
    note="Open the organization and use Upload signed document under Legal documents.",
)
