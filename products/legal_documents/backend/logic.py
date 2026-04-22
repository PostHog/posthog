"""
Business logic for legal_documents.

ORM queries, validation, calculations, business rules.
Called by facade/api.py — do not call from outside this module.
"""

from uuid import UUID

import structlog
import posthoganalytics

from posthog.cloud_utils import get_cached_instance_license
from posthog.event_usage import groups
from posthog.models.organization import Organization

from ee.billing.billing_manager import BillingManager

from .facade.enums import DocumentType
from .models import LegalDocument

logger = structlog.get_logger(__name__)

# Addon types that entitle an organization to a BAA.
BAA_ADDON_TYPES = frozenset({"boost", "scale", "enterprise"})


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


def get_by_webhook_secret(secret: str) -> LegalDocument | None:
    try:
        return LegalDocument.objects.get(webhook_secret=secret)
    except LegalDocument.DoesNotExist:
        return None


def create_document(
    organization_id: UUID,
    created_by_id: int,
    document_type: str,
    company_name: str,
    company_address: str,
    representative_name: str,
    representative_title: str,
    representative_email: str,
    dpa_mode: str,
) -> LegalDocument:
    return LegalDocument.objects.create(
        organization_id=organization_id,
        created_by_id=created_by_id,
        document_type=document_type,
        company_name=company_name,
        company_address=company_address,
        representative_name=representative_name,
        representative_title=representative_title,
        representative_email=representative_email,
        dpa_mode=dpa_mode,
    )


def mark_document_signed(document: LegalDocument, signed_document_url: str) -> LegalDocument:
    document.signed_document_url = signed_document_url
    document.status = LegalDocument.Status.SIGNED
    document.save(update_fields=["signed_document_url", "status", "updated_at"])
    return document


def fire_legal_document_event(document: LegalDocument, distinct_id: str) -> None:
    """
    We use Zapier to connect with our PandaDoc automation. The webhook secret is included as a
    property so Zapier can pass it through to PandaDoc, which will echo it back to our public
    signed-URL webhook for verification — also via Zapier.
    """
    event_name = "submitted BAA" if document.document_type == DocumentType.BAA else "clicked Request DPA"
    try:
        posthoganalytics.capture(
            event=event_name,
            distinct_id=distinct_id,
            properties={
                "documentType": document.document_type,
                "companyName": document.company_name,
                "companyAddress": document.company_address,
                "yourName": document.representative_name,
                "yourTitle": document.representative_title,
                # posthog.com sent BAAs under `email` and DPAs under `representativeEmail`.
                # Always emit both aliases so existing Zapier field mappings keep working.
                "email": document.representative_email,
                "representativeEmail": document.representative_email,
                "mode": document.dpa_mode,
                "organization_id": str(document.organization_id),
                "organization_name": document.organization.name,
                "legal_document_id": str(document.id),
                # Pre-shared secret for the public signed-URL webhook. Lives only in
                # the backend; Zapier reads it off the event and pipes it to PandaDoc,
                # which posts it back to /api/legal_documents/signed where we look the
                # row up by this secret.
                "legal_document_secret": document.webhook_secret,
            },
            groups=groups(document.organization),
        )
    except Exception as e:
        # Don't fail the user's create just because analytics failed — the document
        # is already persisted and the signed URL webhook still works once Zapier is
        # re-fired manually from the admin.
        logger.exception("Failed to capture legal document submission event", error=str(e))
