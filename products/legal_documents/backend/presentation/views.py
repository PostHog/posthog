from typing import cast

import structlog
import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, mixins, permissions, viewsets
from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import groups
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from ..models import LegalDocument
from .serializers import LegalDocumentSerializer

logger = structlog.get_logger(__name__)


class IsOrganizationAdminOrOwner(BasePermission):
    """
    Allow access only to organization admins and owners (for every method,
    including reads). Mirrors the gate we apply to the Settings → Legal
    documents entry and the /legal scene in the frontend, so that non-admin
    members can't probe the API directly either.
    """

    message = "Your organization access level is insufficient."

    def has_permission(self, request: Request, view) -> bool:
        organization = getattr(view, "organization", None)
        if organization is None:
            # Mixin hasn't resolved the org yet — defer. TeamAndOrgViewSetMixin
            # calls this after the URL kwarg has been parsed, so this branch is
            # effectively only hit on misconfigured routes.
            raise exceptions.NotFound("Organization not found.")
        try:
            membership = OrganizationMembership.objects.get(user=cast(User, request.user), organization=organization)
        except OrganizationMembership.DoesNotExist:
            raise exceptions.NotFound("Organization not found.")
        return membership.level >= OrganizationMembership.Level.ADMIN


def _fire_event(legal_document: LegalDocument, distinct_id: str) -> None:
    """
    We use Zapier to connect with our PandaDoc automation. The webhook secret is included as a
    property so Zapier can pass it through to PandaDoc, which will echo it back
    to our public signed-URL webhook for verification - also via Zapier.
    """
    event_name = "submitted BAA" if legal_document.document_type == "BAA" else "clicked Request DPA"
    try:
        posthoganalytics.capture(
            event=event_name,
            distinct_id=distinct_id,
            properties={
                "documentType": legal_document.document_type,
                "companyName": legal_document.company_name,
                "companyAddress": legal_document.company_address,
                "yourName": legal_document.representative_name,
                "yourTitle": legal_document.representative_title,
                # posthog.com sent BAAs under `email` and DPAs under `representativeEmail`.
                # Always emit both aliases so existing Zapier field mappings keep working.
                "email": legal_document.representative_email,
                "representativeEmail": legal_document.representative_email,
                "mode": legal_document.dpa_mode,
                "organization_id": str(legal_document.organization_id),
                "organization_name": legal_document.organization.name,
                "legal_document_id": str(legal_document.id),
                # Pre-shared secret for the public signed-URL webhook. Lives only in
                # the backend; Zapier reads it off the event and pipes it to PandaDoc,
                # which posts it back to /api/legal_documents/<id>/signed.
                "legal_document_secret": legal_document.webhook_secret,
            },
            groups=groups(legal_document.organization),
        )
    except Exception as e:
        # Don't fail the user's create just because analytics failed — the document
        # is already persisted and the signed URL webhook still works once Zapier is
        # re-fired manually from the admin.
        logger.exception("Failed to capture legal document submission event", error=str(e))


@extend_schema(tags=["core"])
class LegalDocumentViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "legal_document"
    serializer_class = LegalDocumentSerializer
    permission_classes = [permissions.IsAuthenticated, IsOrganizationAdminOrOwner]
    queryset = LegalDocument.objects.select_related("created_by").all()

    def perform_create(self, serializer) -> None:
        super().perform_create(serializer)
        _fire_event(serializer.instance, distinct_id=str(cast(User, self.request.user).distinct_id))
