from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, viewsets
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action

from products.error_tracking.backend.facade import (
    contracts,
    source_links as source_links_facade,
)


class ErrorTrackingSourceLinkResolveRequestSerializer(serializers.Serializer):
    release_id = serializers.UUIDField(
        help_text="ID of the exception event's release, from its `$exception_release` property. Its repository and commit are used for every frame.",
    )
    raw_ids = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        max_length=source_links_facade.MAX_RAW_IDS_PER_REQUEST,
        help_text="Raw frame IDs in 'hash/part' format, as returned by the stack frame endpoints.",
    )


class ErrorTrackingSourceLinkSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.ErrorTrackingSourceLink


class ErrorTrackingSourceLinkResolveResponseSerializer(serializers.Serializer):
    results = ErrorTrackingSourceLinkSerializer(
        many=True,
        help_text="One link per frame that maps to a file in the repository. Frames without a match are omitted.",
    )


class GitProviderFileLinksViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"
    scope_object_read_actions = ["resolve"]

    # Placed above @action: the action decorator resets the function's schema metadata, so a
    # schema declared below it is dropped from the OpenAPI spec.
    @validated_request(
        ErrorTrackingSourceLinkResolveRequestSerializer,
        responses={200: OpenApiResponse(response=ErrorTrackingSourceLinkResolveResponseSerializer)},
        summary="Resolve source links",
        description=(
            "Links resolved stack frames to the matching file in the GitHub or GitLab repository of the "
            "exception event's release, at the release commit."
        ),
    )
    @action(methods=["POST"], detail=False)
    def resolve(self, request: ValidatedRequest, **kwargs) -> Response:
        links = source_links_facade.resolve_source_links(
            self.team.id, str(request.validated_data["release_id"]), request.validated_data["raw_ids"]
        )
        return Response(ErrorTrackingSourceLinkResolveResponseSerializer({"results": links}).data)
