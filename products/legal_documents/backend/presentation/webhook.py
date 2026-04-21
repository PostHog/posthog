import hmac

from django.core.exceptions import ValidationError as DjangoValidationError

import structlog
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.rate_limit import IPThrottle

from ..models import LegalDocument

logger = structlog.get_logger(__name__)


class LegalDocumentSignedWebhookBurstThrottle(IPThrottle):
    scope = "legal_document_signed_webhook_burst"
    rate = "5/minute"


class LegalDocumentSignedWebhookSustainedThrottle(IPThrottle):
    scope = "legal_document_signed_webhook_sustained"
    rate = "30/hour"


class LegalDocumentSignedWebhookSerializer(serializers.Serializer):
    secret = serializers.CharField(write_only=True, max_length=128)
    signed_document_url = serializers.URLField(max_length=2048)

    def validate_signed_document_url(self, value: str) -> str:
        if not value.lower().startswith(("http://", "https://")):
            raise serializers.ValidationError("Must be an absolute URL.")
        return value


@extend_schema(
    tags=["legal_documents"],
    operation_id="legal_document_signed_webhook",
    request=LegalDocumentSignedWebhookSerializer,
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT},
    description=(
        "Public webhook hit by Zapier/PandaDoc after a customer signs a legal document. "
        "Requires a pre-shared `secret` (generated at submission time and echoed through "
        "the PostHog event) that matches the document's stored `webhook_secret`. "
        "On success, flips the document status to `signed` and stores the download URL."
    ),
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@throttle_classes([LegalDocumentSignedWebhookBurstThrottle, LegalDocumentSignedWebhookSustainedThrottle])
def legal_document_signed_webhook(request: Request, document_id: str) -> Response:
    serializer = LegalDocumentSignedWebhookSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        document = LegalDocument.objects.get(id=document_id)
    except (LegalDocument.DoesNotExist, ValueError, DjangoValidationError):
        # 404 for missing and malformed IDs so we never signal which IDs exist.
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    if not hmac.compare_digest(serializer.validated_data["secret"], document.webhook_secret):
        logger.warning(
            "Legal document signed webhook rejected — secret mismatch",
            document_id=str(document.id),
        )
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    document.signed_document_url = serializer.validated_data["signed_document_url"]
    document.status = LegalDocument.Status.SIGNED
    document.save(update_fields=["signed_document_url", "status", "updated_at"])

    return Response({"status": document.status}, status=status.HTTP_200_OK)
