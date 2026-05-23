"""
Webhook receiver for social_signals.

A single unauthenticated endpoint that resolves the team via an opaque
``ingest_token`` embedded in the URL. The token is the credential — there's no
HMAC body signature in this iteration. Tokens are generated with
``secrets.token_urlsafe(32)`` and can be rotated via the source viewset.

Pattern reference: ``products/legal_documents/backend/presentation/webhook.py``
(return 404 not 403 on unknown token to avoid enumeration; throttle by IP).
"""

from __future__ import annotations

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.rate_limit import IPThrottle

from ..facade import api
from .serializers import IngestResultSerializer
from .views import _parse_webhook_body

logger = structlog.get_logger(__name__)


class SocialSignalsWebhookBurstThrottle(IPThrottle):
    scope = "social_signals_webhook_burst"
    rate = "30/minute"


class SocialSignalsWebhookSustainedThrottle(IPThrottle):
    scope = "social_signals_webhook_sustained"
    rate = "500/hour"


@extend_schema(
    tags=["social_signals"],
    operation_id="social_signals_ingest_webhook",
    parameters=[
        OpenApiParameter(
            "ingest_token",
            OpenApiTypes.STR,
            OpenApiParameter.PATH,
            description="Opaque per-team token identifying the configured source.",
        )
    ],
    request=OpenApiTypes.OBJECT,
    responses={200: IngestResultSerializer, 404: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    description=(
        "Ingest a webhook delivery for the source identified by the URL token. "
        "Payload shape varies by source kind (see adapter docs). Returns "
        "{accepted, skipped} counts. Repeat deliveries with the same external "
        "ids are dedup'd and counted as skipped. Returns 404 on an unknown / "
        "disabled token (no distinction, to avoid enumeration)."
    ),
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@throttle_classes([SocialSignalsWebhookBurstThrottle, SocialSignalsWebhookSustainedThrottle])
def ingest_webhook(request: Request, ingest_token: str) -> Response:
    payload = _parse_webhook_body(request)

    try:
        result = api.ingest_from_webhook(ingest_token=ingest_token, payload=payload)
    except api.MentionSourceNotFoundError:
        # 404 (not 403) so an attacker can't distinguish "wrong token" from
        # "unknown route" via timing or status code.
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    except api.UnknownAdapterError as exc:
        logger.warning("social_signals.webhook.unknown_adapter", error=str(exc))
        capture_exception(exc)
        return Response({"detail": "Source adapter unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    return Response(IngestResultSerializer(instance=result).data, status=status.HTTP_200_OK)
