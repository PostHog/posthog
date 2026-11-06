import posthoganalytics
from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import get_request_analytics_properties, groups

from products.error_tracking.backend.facade import (
    api as error_tracking_api,
    contracts,
)


class ErrorTrackingBuiltInFilterSerializer(serializers.Serializer):
    key = serializers.CharField(
        read_only=True, help_text="Stable identifier of the built-in filter, for example `web_crawlers`."
    )
    name = serializers.CharField(read_only=True, help_text="Display name of the built-in filter.")
    description = serializers.CharField(read_only=True, help_text="One sentence on which exceptions the filter drops.")
    evaluation = serializers.ChoiceField(
        read_only=True,
        choices=contracts.BuiltInFilterEvaluation.choices,
        help_text=(
            "Where the filter runs. `client` filters also run in the web SDK, which drops matching exceptions "
            "before it sends them. `server` filters run only during ingestion."
        ),
    )
    enabled = serializers.BooleanField(
        read_only=True, help_text="Whether the filter drops exceptions for this project."
    )
    disabled_reason = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Set when ingestion turned the filter off because it failed on an event. "
            "Turning the filter on again resets it."
        ),
    )


class ErrorTrackingBuiltInFilterUpdateRequestSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(
        help_text="`true` drops matching exceptions for this project. `false` stops dropping them."
    )


class ErrorTrackingBuiltInFilterViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["partial_update"]
    # Each rule drops events for the whole project, so a grant on one error tracking object is not enough.
    requires_resource_level_access = True
    lookup_field = "key"
    lookup_value_regex = "[a-z0-9_]+"

    @validated_request(responses={200: OpenApiResponse(response=ErrorTrackingBuiltInFilterSerializer(many=True))})
    def list(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        filters = error_tracking_api.list_built_in_filters(self.team.id)
        return Response(ErrorTrackingBuiltInFilterSerializer(filters, many=True).data)

    @validated_request(
        request_serializer=ErrorTrackingBuiltInFilterUpdateRequestSerializer,
        responses={200: OpenApiResponse(response=ErrorTrackingBuiltInFilterSerializer)},
    )
    def partial_update(self, request: ValidatedRequest, *args, key: str, **kwargs) -> Response:
        enabled: bool = request.validated_data["enabled"]
        try:
            built_in_filter = error_tracking_api.set_built_in_filter_enabled(self.team.id, key, enabled=enabled)
        except error_tracking_api.UnknownBuiltInFilterError as err:
            raise NotFound() from err
        posthoganalytics.capture(
            "error_tracking_built_in_filter_toggled",
            distinct_id=request.user.pk,
            properties={
                **get_request_analytics_properties(request),
                "built_in_filter_key": key,
                "enabled": enabled,
            },
            groups=groups(self.team.organization, self.team),
        )
        return Response(ErrorTrackingBuiltInFilterSerializer(built_in_filter).data)
