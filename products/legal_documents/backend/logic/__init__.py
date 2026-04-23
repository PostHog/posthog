"""
Business logic for legal_documents.

ORM queries, validation, calculations, business rules.
Called by facade/api.py — do not call from outside this module.
"""

from uuid import UUID

from django.conf import settings

import structlog
import posthoganalytics

from posthog.cloud_utils import get_cached_instance_license
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization
from posthog.storage import object_storage

from ee.billing.billing_manager import BillingManager

from ..facade.enums import DocumentType
from ..models import LegalDocument
from . import (
    pandadoc as pandadoc_client,
    slack as slack_notifier,
)

logger = structlog.get_logger(__name__)

# Addon types that entitle an organization to a BAA.
BAA_ADDON_TYPES = frozenset({"boost", "scale", "enterprise"})

# PostHog-side CC on every signing envelope. Lives here rather than on the
# PandaDoc client so the client stays generic and reusable.
POSTHOG_SIGNING_CC_EMAIL = "sales@posthog.com"


def _pandadoc_template_id_for(document_type: str) -> str:
    """
    Resolve the PandaDoc template id for a given document type. One template
    per type, configured via env. Returns an empty string if the matching env
    var isn't set, which surfaces as a clear PandaDocError at send time.
    """
    if document_type == DocumentType.BAA:
        return settings.PANDADOC_BAA_TEMPLATE_ID
    if document_type == DocumentType.DPA:
        return settings.PANDADOC_DPA_TEMPLATE_ID
    return ""


def template_id_matches_document(document: LegalDocument, template_id: str) -> bool:
    """
    Used by the inbound webhook to double-check the event belongs to the row we
    looked up. Defends against misconfigured templates (e.g., somebody pointing
    the BAA webhook at a DPA row) so we don't mark the wrong document signed.
    """
    expected = _pandadoc_template_id_for(document.document_type)
    # If the env var isn't configured we skip the check rather than block every
    # webhook — verify_webhook_signature already proves provenance.
    return not expected or expected == template_id


def has_qualifying_baa_addon(organization: Organization) -> bool:
    billing = BillingManager(get_cached_instance_license()).get_billing(organization)
    for product in billing.get("products") or []:
        for addon in product.get("addons") or []:
            if addon.get("type") in BAA_ADDON_TYPES and addon.get("subscribed"):
                return True
    return False


def exists_for_organization_and_type(organization_id: UUID, document_type: str) -> bool:
    return LegalDocument.objects.filter(organization_id=organization_id, document_type=document_type).exists()


def list_for_organization(organization_id: UUID):
    return (
        LegalDocument.objects.select_related("created_by")
        .filter(organization_id=organization_id)
        .order_by("-created_at")
    )


def get_for_organization(document_id: UUID, organization_id: UUID) -> LegalDocument | None:
    try:
        return LegalDocument.objects.select_related("created_by").get(id=document_id, organization_id=organization_id)
    except LegalDocument.DoesNotExist:
        return None


def get_by_pandadoc_document_id(pandadoc_document_id: str) -> LegalDocument | None:
    if not pandadoc_document_id:
        return None
    try:
        return LegalDocument.objects.get(pandadoc_document_id=pandadoc_document_id)
    except LegalDocument.DoesNotExist:
        return None


def create_document(
    organization_id: UUID,
    created_by_id: int,
    document_type: str,
    company_name: str,
    company_address: str,
    representative_email: str,
) -> LegalDocument:
    return LegalDocument.objects.create(
        organization_id=organization_id,
        created_by_id=created_by_id,
        document_type=document_type,
        company_name=company_name,
        company_address=company_address,
        representative_email=representative_email,
    )


def mark_document_signed(document: LegalDocument) -> LegalDocument:
    document.status = LegalDocument.Status.SIGNED
    document.save(update_fields=["status", "updated_at"])
    return document


def signed_pdf_storage_key(document: LegalDocument) -> str:
    """
    Canonical key under which the signed PDF lives in object storage. The
    document uuid is the natural identifier and never changes, so admins
    regenerating the envelope for the same row just overwrite the old object.
    """
    return f"{settings.OBJECT_STORAGE_LEGAL_DOCUMENTS_FOLDER}/{document.id}.pdf"


# Short-enough that leaked URLs stop working on a human timescale, long enough
# that slow network conditions or a distracted user can still complete the
# download without the presigned URL expiring mid-stream.
_SIGNED_PDF_PRESIGNED_URL_EXPIRATION_SECONDS = 60


def get_signed_pdf_presigned_url(document: LegalDocument) -> str | None:
    """
    Presigned GET URL for the signed PDF. The proxy endpoint redirects to this
    rather than streaming the bytes itself — S3 does the heavy lifting and our
    Django process doesn't have to hold the PDF in memory.
    """
    if not settings.OBJECT_STORAGE_ENABLED:
        return None
    key = signed_pdf_storage_key(document)
    return object_storage.get_presigned_url(
        key,
        expiration=_SIGNED_PDF_PRESIGNED_URL_EXPIRATION_SECONDS,
        content_type="application/pdf",
        content_disposition=f'attachment; filename="PostHog-{document.document_type}-{document.id}.pdf"',
    )


def download_and_store_signed_pdf(document: LegalDocument) -> bool:
    """
    Stream the signed PDF from PandaDoc straight into object storage.

    PandaDoc's `document.completed` webhook doesn't include a download URL, so
    we pull the PDF via the public API and persist it ourselves. The download
    is streamed — bytes flow from the PandaDoc socket directly into the S3
    multipart upload, so peak memory stays flat regardless of PDF size.
    Returns True on success. On any failure (PandaDoc unreachable, S3
    unavailable) we log + report and return False; the caller leaves the row
    unsigned so a replayed webhook (or manual re-trigger) can retry.
    """
    if not document.pandadoc_document_id:
        logger.warning("legal_document_pdf_download_missing_envelope_id", document_id=str(document.id))
        return False
    if not settings.OBJECT_STORAGE_ENABLED:
        logger.warning("legal_document_pdf_download_object_storage_disabled", document_id=str(document.id))
        return False
    client = pandadoc_client.PandaDocClient()
    try:
        with client.stream_document(document_id=document.pandadoc_document_id) as pdf_stream:
            object_storage.write_stream(
                signed_pdf_storage_key(document),
                pdf_stream,
                extras={"ContentType": "application/pdf"},
            )
    except pandadoc_client.PandaDocError as exc:
        logger.exception(
            "legal_document_pandadoc_download_failed",
            document_id=str(document.id),
            pandadoc_document_id=document.pandadoc_document_id,
            error=str(exc),
        )
        capture_exception(exc, additional_properties={"legal_document_id": str(document.id)})
        return False
    except Exception as exc:
        logger.exception(
            "legal_document_signed_pdf_upload_failed",
            document_id=str(document.id),
            error=str(exc),
        )
        capture_exception(exc, additional_properties={"legal_document_id": str(document.id)})
        return False
    return True


def set_pandadoc_document_id(document: LegalDocument, pandadoc_document_id: str) -> LegalDocument:
    document.pandadoc_document_id = pandadoc_document_id
    document.save(update_fields=["pandadoc_document_id", "updated_at"])
    return document


def create_pandadoc_envelope(document: LegalDocument) -> str | None:
    """
    Create the envelope on PandaDoc and persist its uuid on the row.

    The envelope lands in PandaDoc's `document.uploaded` state, which isn't
    dispatchable yet — PandaDoc processes the template asynchronously and
    emits a `document.draft` webhook once it's ready. `send_pandadoc_envelope`
    runs from that webhook. We don't block the user's create call waiting for
    it.

    Returns the PandaDoc document id or None when PandaDoc isn't configured /
    the call failed; the caller stays on the happy path either way so a
    failure just leaves the row without a `pandadoc_document_id` (ops can
    re-trigger later).
    """
    template_id = _pandadoc_template_id_for(document.document_type)
    if not template_id:
        logger.warning(
            "legal_document_pandadoc_template_not_configured",
            document_id=str(document.id),
            document_type=document.document_type,
        )
        return None

    client = pandadoc_client.PandaDocClient()
    try:
        # The client-facing recipient has role "Client"; PandaDoc fills the
        # template's `[Client.Email]` token from the recipient's email. The
        # remaining template tokens (`[Client.Company]`, `[Client.StreetAddress]`)
        # aren't auto-populated — we have to pass them explicitly.
        created = client.create_document_from_template(
            template_id=template_id,
            name=f"PostHog {document.document_type} — {document.company_name}",
            recipients=[
                pandadoc_client.PandaDocRecipient(
                    email=POSTHOG_SIGNING_CC_EMAIL, role=pandadoc_client.PandaDocRole.POSTHOG
                ),
                pandadoc_client.PandaDocRecipient(
                    email=document.representative_email, role=pandadoc_client.PandaDocRole.CLIENT
                ),
            ],
            tokens={
                "Client.Company": document.company_name,
                "Client.StreetAddress": document.company_address,
            },
            metadata={
                "legal_document_id": str(document.id),
                "organization_id": str(document.organization_id),
                "document_type": document.document_type,
            },
        )
        set_pandadoc_document_id(document, created.id)
        return created.id
    except pandadoc_client.PandaDocError as exc:
        logger.exception(
            "legal_document_pandadoc_create_failed",
            document_id=str(document.id),
            error=str(exc),
        )
        capture_exception(exc, additional_properties={"legal_document_id": str(document.id)})
        return None


def send_pandadoc_envelope(document: LegalDocument) -> bool:
    """
    Dispatch the signing email for a previously-created PandaDoc envelope.
    Called from the `document.draft` webhook once PandaDoc has finished
    processing the template and the envelope is actually sendable.

    Returns True when the send succeeded, False otherwise. Never re-raises:
    PandaDoc will also reject a second send on a doc that's already past
    `document.draft` (duplicate webhook delivery), which we silently swallow.
    """
    if not document.pandadoc_document_id:
        logger.warning("legal_document_pandadoc_send_missing_envelope_id", document_id=str(document.id))
        return False

    client = pandadoc_client.PandaDocClient()
    try:
        client.send_document(
            document_id=document.pandadoc_document_id,
            subject=f"Please sign: PostHog {document.document_type}",
            message=(
                f"Hi,\n\n"
                f"Please find attached the {document.document_type} for your review and signature. "
                f"You can also forward this document to reassign it if needed.\n\n"
                f"- The PostHog Team"
            ),
        )
        return True
    except pandadoc_client.PandaDocError as exc:
        logger.exception(
            "legal_document_pandadoc_send_failed",
            document_id=str(document.id),
            pandadoc_document_id=document.pandadoc_document_id,
            error=str(exc),
        )
        capture_exception(
            exc,
            additional_properties={
                "legal_document_id": str(document.id),
                "pandadoc_document_id": document.pandadoc_document_id,
            },
        )
        return False


def notify_slack_on_submit(document: LegalDocument) -> None:
    try:
        slack_notifier.notify_submitted(
            document_type=document.document_type,
            company_name=document.company_name,
            representative_email=document.representative_email,
            pandadoc_document_id=document.pandadoc_document_id or None,
        )
    except Exception as exc:
        # Slack errors are already swallowed inside the notifier, but protect
        # the submit path from unexpected import/attr errors too.
        logger.exception("legal_document_slack_submit_notify_failed", error=str(exc))
        capture_exception(exc, additional_properties={"legal_document_id": str(document.id)})


def notify_slack_on_signed(document: LegalDocument) -> None:
    try:
        slack_notifier.notify_signed(
            document_type=document.document_type,
            company_name=document.company_name,
            pandadoc_document_id=document.pandadoc_document_id or None,
        )
    except Exception as exc:
        logger.exception("legal_document_slack_signed_notify_failed", error=str(exc))
        capture_exception(exc, additional_properties={"legal_document_id": str(document.id)})


SUBMITTED_EVENT = "legal document submitted"
SIGNED_EVENT = "legal document signed"


def fire_legal_document_submitted_event(document: LegalDocument, distinct_id: str) -> None:
    """
    Capture the submission to PostHog for analytics. No longer a critical path —
    the customer-facing work (PandaDoc + Slack) is driven directly by the
    submit handler. This event is kept for product analytics on the
    `/legal/new/:type` funnel.
    """
    _capture_lifecycle_event(document, SUBMITTED_EVENT, distinct_id)


def fire_legal_document_signed_event(document: LegalDocument, distinct_id: str | None = None) -> None:
    """Capture the signed milestone to PostHog for the same analytics funnel."""
    _capture_lifecycle_event(document, SIGNED_EVENT, distinct_id)


def _capture_lifecycle_event(document: LegalDocument, event_name: str, distinct_id: str | None) -> None:
    try:
        posthoganalytics.capture(
            event=event_name,
            distinct_id=distinct_id or f"legal_document:{document.id}",
            properties={
                "document_type": document.document_type,
                "company_name": document.company_name,
                "company_address": document.company_address,
                "representative_email": document.representative_email,
                "organization_id": str(document.organization_id),
                "organization_name": document.organization.name,
                "legal_document_id": str(document.id),
                "pandadoc_document_id": document.pandadoc_document_id or None,
                "status": document.status,
            },
            groups=groups(document.organization),
        )
    except Exception as exc:
        logger.exception("legal_document_event_capture_failed", event=event_name, error=str(exc))
        capture_exception(
            exc,
            additional_properties={"legal_document_id": str(document.id), "event_name": event_name},
        )
