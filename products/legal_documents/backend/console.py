from uuid import UUID

from django import forms
from django.contrib import messages
from django.contrib.admin.utils import unquote
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
)
from products.legal_documents.backend.facade.contracts import StaffLegalDocument
from products.legal_documents.backend.facade.enums import LegalDocumentStatus, StaffRefetchOutcome, StaffResendOutcome

GROWTH = Owner(name="Growth", crest="growth")

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
    operation_keys = frozenset({"refetch-pdf", "resend-signing-email", "delete"})

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
        operations: list[Operation] = []
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
                    "settings. Staff can upload a signed PDF again in Django admin.",
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
