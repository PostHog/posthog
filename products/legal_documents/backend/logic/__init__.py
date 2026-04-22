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


def mark_document_signed(document: LegalDocument, signed_document_url: str) -> LegalDocument:
    document.signed_document_url = signed_document_url
    document.status = LegalDocument.Status.SIGNED
    document.save(update_fields=["signed_document_url", "status", "updated_at"])
    return document


def set_pandadoc_document_id(document: LegalDocument, pandadoc_document_id: str) -> LegalDocument:
    document.pandadoc_document_id = pandadoc_document_id
    document.save(update_fields=["pandadoc_document_id", "updated_at"])
    return document


def submit_to_pandadoc(document: LegalDocument) -> str | None:
    """
    Create the envelope on PandaDoc and send the signing email. Returns the
    PandaDoc document id (also persisted on the row), or None if PandaDoc isn't
    configured / the call failed — the caller decides what to do with the miss.

    We never re-raise to the caller: the document is already persisted, the
    customer gets an error-free 201 from the API, and ops sees a Slack + log
    trace when we couldn't reach PandaDoc so they can re-send manually.
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
        # Each PandaDoc template has one recipient with role "Client". PandaDoc
        # fills the Client.Email / Client.Company / Client.StreetAddress fields
        # in the document body directly from that recipient's contact data.
        created = client.create_document_from_template(
            template_id=template_id,
            name=f"PostHog {document.document_type} — {document.company_name}",
            recipients=[
                pandadoc_client.PandaDocSenderPostHog(),
                pandadoc_client.PandaDocRecipient(
                    email=document.representative_email,
                    company=document.company_name,
                    street_address=document.company_address,
                ),
            ],
            metadata={
                "legal_document_id": str(document.id),
                "organization_id": str(document.organization_id),
                "document_type": document.document_type,
            },
        )
        set_pandadoc_document_id(document, created.id)
        client.send_document(
            document_id=created.id,
            subject=f"Please sign: PostHog {document.document_type}",
            message=(
                f"Hi,\n\n"
                f"Please find attached the {document.document_type} for your review and signature. "
                f"You can also forward this document to reassign it if needed.\n\n"
                f"- The PostHog Team"
            ),
        )
        return created.id
    except pandadoc_client.PandaDocError as exc:
        logger.exception(
            "legal_document_pandadoc_submit_failed",
            document_id=str(document.id),
            error=str(exc),
        )
        capture_exception(exc, additional_properties={"legal_document_id": str(document.id)})
        return None


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
