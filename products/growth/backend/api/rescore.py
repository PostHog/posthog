"""Webhook for the wizard-stamp ICP re-score: a PostHog realtime destination on the enrichment
project calls this the instant the setup wizard's AI-SDK stamp lands on an org, so the score
doesn't have to wait on the standing +4h recheck or the daily sweep to catch it.

No PostHog session or personal-API-key auth: the caller is our own destination, authenticated
by a shared secret header instead. See
products/growth/backend/temporal/signup_enrichment/rescore.py for the workflow this dispatches.
"""

import hmac

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.utils import ErrorResponseSerializer
from posthog.exceptions_capture import capture_exception
from posthog.models.instance_setting import get_instance_setting
from posthog.rate_limit import IPThrottle
from posthog.utils import get_instance_region

from products.growth.backend.models import OrganizationEnrichment
from products.growth.backend.temporal.signup_enrichment.trigger import dispatch_wizard_stamp_rescore

WEBHOOK_SECRET_HEADER = "X-PostHog-Webhook-Secret"


class GrowthRescoreWebhookThrottle(IPThrottle):
    """Bounds a misconfigured or runaway destination, on top of the shared-secret gate."""

    scope = "growth_rescore_webhook"
    rate = "300/minute"


class RescoreRequestSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField(
        help_text="Organization to re-score, from the $group_key of the wizard's $groupidentify event."
    )


class RescoreResponseSerializer(serializers.Serializer):
    queued = serializers.BooleanField(help_text="Whether the re-score workflow was dispatched.")
    reason = serializers.ChoiceField(
        choices=["disabled", "no_enrichment_record"],
        required=False,
        help_text="Present, with queued false, when nothing was dispatched.",
    )


def _rescore_enabled() -> bool:
    try:
        return bool(get_instance_setting("GROWTH_SIGNUP_ENRICHMENT_ENABLED"))
    except Exception as e:
        capture_exception(e)
        return False


class GrowthEnrichmentViewSet(viewsets.ViewSet):
    """Unscoped, unauthenticated: see the module docstring for why."""

    authentication_classes = []
    permission_classes = []
    scope_object = "INTERNAL"

    @extend_schema(
        request=RescoreRequestSerializer,
        responses={
            202: OpenApiResponse(response=RescoreResponseSerializer),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Missing or invalid organization_id."),
            401: OpenApiResponse(description="Missing or incorrect webhook secret."),
            503: OpenApiResponse(description="No webhook secret is configured on this instance."),
        },
        summary="Re-score an organization's ICP fit after its wizard AI-SDK stamp lands.",
        description="Called by a PostHog realtime destination, not by API clients. Requires the "
        f"{WEBHOOK_SECRET_HEADER} header to match the GROWTH_RESCORE_WEBHOOK_SECRET instance setting.",
    )
    @action(methods=["POST"], detail=False, throttle_classes=[GrowthRescoreWebhookThrottle])
    def rescore(self, request: Request, **kwargs) -> Response:
        secret = get_instance_setting("GROWTH_RESCORE_WEBHOOK_SECRET")
        if not secret:
            return Response(status=503)
        if not hmac.compare_digest(secret, request.headers.get(WEBHOOK_SECRET_HEADER, "")):
            return Response(status=401)

        serializer = RescoreRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organization_id = str(serializer.validated_data["organization_id"])

        if not _rescore_enabled() or get_instance_region() not in ("US", "EU"):
            return Response({"queued": False, "reason": "disabled"}, status=202)

        if not OrganizationEnrichment.objects.filter(organization_id=organization_id).exists():
            return Response({"queued": False, "reason": "no_enrichment_record"}, status=202)

        dispatch_wizard_stamp_rescore(organization_id)
        return Response({"queued": True}, status=202)
