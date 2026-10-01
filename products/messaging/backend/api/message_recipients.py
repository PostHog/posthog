from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.messaging.backend.models.message_preferences import PreferenceStatus
from products.messaging.backend.models.message_suppression import SuppressionSource
from products.messaging.backend.services.recipients import RecipientQuery, list_recipients


class RecipientListQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        required=False, default=50, min_value=1, max_value=200, help_text="Page size, 1-200. Defaults to 50."
    )


class RecipientSuppressionSerializer(serializers.Serializer):
    source = serializers.ChoiceField(
        choices=SuppressionSource.choices,
        help_text="Why the address is suppressed: `BOUNCE` (repeated soft bounces), `COMPLAINT` (marked as spam) or `MANUAL` (added by a user).",
    )
    reason = serializers.CharField(allow_null=True, help_text="Free-text reason recorded with the suppression.")
    suppressed_at = serializers.DateTimeField(allow_null=True, help_text="When the address became suppressed.")


class RecipientPersonSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(help_text="UUID of a person whose `email` property is this address.")
    distinct_id = serializers.CharField(help_text="One of the person's distinct IDs.")
    name = serializers.CharField(allow_null=True, help_text="The person's `name` property, if set.")


class RecipientSerializer(serializers.Serializer):
    email = serializers.CharField(help_text="Lower-cased, trimmed email address. One row per address.")
    all_marketing = serializers.ChoiceField(
        choices=PreferenceStatus.choices,
        help_text="Status for all marketing messages. `NO_PREFERENCE` means marketing is sent.",
    )
    topics = serializers.DictField(
        child=serializers.ChoiceField(choices=[PreferenceStatus.OPTED_IN, PreferenceStatus.OPTED_OUT]),
        help_text="Explicit topic statuses keyed by topic key. A topic with no preference is left out. "
        "When preferences exist under several casings of the address, `OPTED_OUT` wins per topic.",
    )
    suppression = RecipientSuppressionSerializer(
        allow_null=True, help_text="Active suppression of the address, or null when sends are not blocked."
    )
    persons = RecipientPersonSerializer(
        many=True, help_text="Up to three persons whose `email` property is this address."
    )
    person_count = serializers.IntegerField(help_text="Number of persons whose `email` property is this address.")
    last_sent_at = serializers.DateTimeField(
        allow_null=True, help_text="When an email was last sent to the address, within the last 30 days."
    )
    preferences_updated_at = serializers.DateTimeField(
        allow_null=True, help_text="When the address's preferences last changed, or null when none were recorded."
    )


class RecipientPageSerializer(serializers.Serializer):
    results = RecipientSerializer(many=True, help_text="Recipients on this page, ordered by address.")


class MessageRecipientsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "hog_flow"
    serializer_class = _FallbackSerializer

    @validated_request(
        query_serializer=RecipientListQuerySerializer,
        responses={200: OpenApiResponse(response=RecipientPageSerializer)},
        summary="List every email address the team can send to",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        if not self.user_access_control.check_access_level_for_resource("hog_flow", "viewer"):
            raise PermissionDenied("You need hog_flow viewer access to view recipients.")
        query = RecipientQuery(limit=request.validated_query_data["limit"])
        page = list_recipients(self.team, request.user, query)
        return Response(RecipientPageSerializer(page).data)
