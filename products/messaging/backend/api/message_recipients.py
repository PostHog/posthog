from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.messaging.backend.services.recipients import RecipientQuery, list_recipients


class RecipientListQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        required=False, default=50, min_value=1, max_value=200, help_text="Page size, 1-200. Defaults to 50."
    )


class RecipientSerializer(serializers.Serializer):
    email = serializers.CharField(help_text="Lower-cased, trimmed email address. One row per address.")


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
