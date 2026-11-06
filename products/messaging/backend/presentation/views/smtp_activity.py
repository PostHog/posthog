from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.auth import ScopedServiceJWTAuthentication
from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

from products.messaging.backend.facade.smtp import SmtpActivityKind, record_smtp_activity

SMTP_RELAY_ACTIVITY_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.SMTP_RELAY_ACTIVITY,
    settings_name="SMTP_RELAY_ACTIVITY_JWT_SECRETS",
)


class SmtpRelayActivityJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = SMTP_RELAY_ACTIVITY_PURPOSE


class SmtpActivitySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=SmtpActivityKind.choices, help_text="`refused` or `dropped_headers`, what happened to the message."
    )
    reply = serializers.CharField(
        required=False, allow_blank=True, max_length=512, help_text="The reply line the SMTP client got."
    )
    # A malformed address is exactly what a refusal needs to show, so these aren't validated as addresses.
    sender = serializers.CharField(
        required=False, allow_blank=True, max_length=320, help_text="The envelope sender of the message."
    )
    to = serializers.ListField(
        child=serializers.CharField(max_length=320),
        required=False,
        max_length=20,
        help_text="Up to 20 recipients named in the To and Cc headers. Bcc recipients are never listed.",
    )
    message_id = serializers.CharField(
        required=False, allow_blank=True, max_length=128, help_text="ID of the queued send, when one was queued."
    )
    dropped_headers = serializers.ListField(
        child=serializers.CharField(max_length=128),
        required=False,
        max_length=20,
        help_text="Names of the headers PostHog could not forward, up to 20.",
    )

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["from"] = fields.pop("sender")
        return fields


class InternalSmtpActivityView(APIView):
    """Keeps a short per-project list of refused messages and dropped headers, so the SMTP setup page can show why mail
    didn't arrive. Only the SMTP relay holds the key for these tokens, and the route is not exposed publicly."""

    authentication_classes = [SmtpRelayActivityJWTAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(exclude=True)
    def post(self, request: Request, team_id: str, *args: Any, **kwargs: Any) -> Response:
        serializer = SmtpActivitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record_smtp_activity(int(team_id), serializer.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)
