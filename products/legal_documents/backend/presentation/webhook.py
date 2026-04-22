import json

from django.conf import settings

import structlog
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.cloud_utils import is_cloud, is_dev_mode
from posthog.exceptions_capture import capture_exception
from posthog.rate_limit import IPThrottle

from ..facade import api

logger = structlog.get_logger(__name__)


class PandaDocWebhookBurstThrottle(IPThrottle):
    scope = "legal_document_pandadoc_webhook_burst"
    rate = "5/minute"


class PandaDocWebhookSustainedThrottle(IPThrottle):
    scope = "legal_document_pandadoc_webhook_sustained"
    rate = "30/hour"


# PandaDoc state-change events we care about. Everything else is ignored.
_PANDADOC_STATE_CHANGED_EVENT = "document_state_changed"

# `draft` fires once PandaDoc has finished processing the template and the
# envelope is ready to be sent to the signer — this is our cue to dispatch
# the signing email.
_PANDADOC_DRAFT_STATUS = "document.draft"
# `completed` fires once every recipient has signed.
_PANDADOC_COMPLETED_STATUS = "document.completed"


@extend_schema(
    tags=["legal_documents"],
    operation_id="legal_document_pandadoc_webhook",
    request=OpenApiTypes.OBJECT,
    responses={200: OpenApiTypes.OBJECT, 204: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT},
    description=(
        "PandaDoc webhook receiver. Authenticates via HMAC-SHA256 over the raw "
        "body. Handles two `document_state_changed` events: `document.draft` "
        "dispatches the signing email + Slack ping, and `document.completed` "
        "flips the row to signed. Returns 200 when an event applied, 204 when "
        "the request is valid but the document doesn't live on this cloud "
        "instance (PandaDoc fans the webhook out to every instance, only one "
        "of which owns the row), 404 on a bad signature, 400 on an "
        "unparseable body."
    ),
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@throttle_classes([PandaDocWebhookBurstThrottle, PandaDocWebhookSustainedThrottle])
def legal_document_pandadoc_webhook(request: Request) -> Response:
    if not (is_cloud() or is_dev_mode()):
        # Self-hosted deployments don't run the PandaDoc integration — never
        # leak that this endpoint exists. Dev mode keeps it on for local testing.
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    raw_body = request.body or b""
    signature = request.headers.get("X-PandaDoc-Signature") or request.query_params.get("signature") or ""
    if not api.verify_pandadoc_webhook_signature(
        secret=settings.PANDADOC_WEBHOOK_SECRET, body=raw_body, signature=signature
    ):
        # Return 404 (not 403) so an attacker can't distinguish "wrong secret"
        # from "unknown route" via timing or status code.
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    try:
        events = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        logger.warning("pandadoc_webhook_invalid_body", error=str(exc))
        capture_exception(exc)
        return Response({"detail": "Invalid body."}, status=status.HTTP_400_BAD_REQUEST)

    # PandaDoc batches multiple events in a single webhook delivery.
    if not isinstance(events, list):
        events = [events]

    processed_any = False
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("event") != _PANDADOC_STATE_CHANGED_EVENT:
            continue
        data = event.get("data") or {}
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            continue

        event_status = data.get("status")
        pandadoc_document_id = data.get("id") or ""
        template_id = (data.get("template") or {}).get("id") if isinstance(data.get("template"), dict) else ""

        if not pandadoc_document_id:
            logger.warning("pandadoc_webhook_event_missing_id", status=event_status)
            continue

        if event_status == _PANDADOC_DRAFT_STATUS:
            # Envelope just finished template processing — dispatch the send.
            dto = api.mark_envelope_ready_by_pandadoc_document_id(
                pandadoc_document_id=pandadoc_document_id,
                template_id=template_id or "",
            )
            if dto is None:
                logger.info("pandadoc_webhook_no_matching_document", pandadoc_document_id=pandadoc_document_id)
                continue
            processed_any = True
            continue

        if event_status == _PANDADOC_COMPLETED_STATUS:
            # PandaDoc's completed payload carries the signed-PDF link under
            # `download_link`. Fall back to the hosted `public_url` so the
            # customer always has somewhere to click.
            signed_url = data.get("download_link") or data.get("public_url") or ""
            if not signed_url:
                logger.warning(
                    "pandadoc_webhook_event_missing_fields",
                    has_id=bool(pandadoc_document_id),
                    has_signed_url=False,
                )
                continue
            dto = api.mark_signed_by_pandadoc_document_id(
                pandadoc_document_id=pandadoc_document_id,
                signed_document_url=signed_url,
                template_id=template_id or "",
            )
            if dto is None:
                logger.info("pandadoc_webhook_no_matching_document", pandadoc_document_id=pandadoc_document_id)
                continue
            processed_any = True
            continue

        # Other states (document.sent, document.viewed, …) — nothing to do.

    if processed_any:
        return Response({"status": "ok"}, status=status.HTTP_200_OK)
    # Nothing applied to this instance — 2xx so PandaDoc doesn't retry, since
    # the sibling instance that owns the row will handle its own copy.
    return Response(status=status.HTTP_204_NO_CONTENT)
