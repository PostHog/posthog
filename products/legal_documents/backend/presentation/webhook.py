from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.rate_limit import IPThrottle

from ..facade import api
from .serializers import LegalDocumentSignedWebhookSerializer


class LegalDocumentSignedWebhookBurstThrottle(IPThrottle):
    scope = "legal_document_signed_webhook_burst"
    rate = "5/minute"


class LegalDocumentSignedWebhookSustainedThrottle(IPThrottle):
    scope = "legal_document_signed_webhook_sustained"
    rate = "30/hour"


@extend_schema(
    tags=["legal_documents"],
    operation_id="legal_document_signed_webhook",
    request=LegalDocumentSignedWebhookSerializer,
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT},
    description=(
        "Public webhook hit by Zapier/PandaDoc after a customer signs a legal document. "
        "The request is authenticated by a per-document `secret` (generated at submission "
        "time and echoed through the PostHog event) — we look the document up by that "
        "secret, so a mismatch simply results in a 404. On success, flips the document "
        "status to `signed` and stores the download URL."
    ),
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@throttle_classes([LegalDocumentSignedWebhookBurstThrottle, LegalDocumentSignedWebhookSustainedThrottle])
def legal_document_signed_webhook(request: Request) -> Response:
    serializer = LegalDocumentSignedWebhookSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    # The secret is 256 bits of entropy (secrets.token_urlsafe(32)) and is the sole
    # auth factor for this public webhook — looking up by it is equivalent to
    # authenticating, and avoids the IDOR surface of accepting an id from the caller.
    dto = api.mark_signed_by_secret(
        secret=serializer.validated_data["secret"],
        signed_document_url=serializer.validated_data["signed_document_url"],
    )
    if dto is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response({"status": dto.status}, status=status.HTTP_200_OK)
