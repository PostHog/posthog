from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.facade import recommendations as recommendations_facade
from products.error_tracking.backend.facade.contracts import MissingSymbolsReason, SymbolsPlatform


class ErrorTrackingRecommendationSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Recommendation UUID.")
    type = serializers.CharField(help_text="Recommendation type identifier (e.g. 'alerts').")
    meta = serializers.JSONField(help_text="Recommendation payload, shape depends on type.")
    completed = serializers.BooleanField(
        help_text="Whether the recommendation's recommended action has been satisfied."
    )
    status = serializers.CharField(help_text="'ready' if meta is fresh, 'computing' if a refresh is in progress.")
    computed_at = serializers.DateTimeField(allow_null=True, help_text="Timestamp meta was last successfully computed.")
    dismissed_at = serializers.DateTimeField(
        allow_null=True, help_text="Timestamp the user dismissed this recommendation, if any."
    )
    created_at = serializers.DateTimeField(help_text="Timestamp the recommendation row was first created.")
    updated_at = serializers.DateTimeField(help_text="Timestamp the recommendation row was last updated.")


class MissingSymbolsExamplesQuerySerializer(serializers.Serializer):
    platform = serializers.ChoiceField(
        choices=SymbolsPlatform.choices,
        help_text="The platform to list examples for: 'javascript', 'java' (Android) or 'native' (iOS and native).",
    )


class MissingSymbolsExampleSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(
        choices=MissingSymbolsReason.choices,
        help_text="Why the frames miss symbols, as a code. Each code maps to one kind of setup gap.",
    )
    location = serializers.CharField(
        allow_null=True,
        help_text="Where the frames come from: the script URL or path, the bundle, or an example class or app image.",
    )
    symbol_id = serializers.CharField(
        allow_null=True,
        help_text="The chunk ID, mapping ID or debug ID that the missing symbols must be uploaded under, when known.",
    )
    http_status = serializers.IntegerField(
        allow_null=True, help_text="The HTTP status the script or source map returned, for 'file_not_reachable'."
    )
    frames = serializers.IntegerField(help_text="How many distinct stack frames in the lookback window this covers.")
    example_function = serializers.CharField(
        allow_null=True, help_text="The function name of one affected frame, as the SDK reported it."
    )


class MissingSymbolsExamplesSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=SymbolsPlatform.choices, help_text="The platform the examples are for.")
    lookback_hours = serializers.IntegerField(help_text="How many hours of recent stack frames the examples cover.")
    results = MissingSymbolsExampleSerializer(
        many=True, help_text="The files and builds with the most frames missing symbols, most frames first."
    )


class ErrorTrackingRecommendationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    scope_object_read_actions = ["list", "retrieve", "source_maps_examples"]
    scope_object_write_actions = ["refresh", "dismiss", "restore"]
    serializer_class = ErrorTrackingRecommendationSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="poll",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description="True reads the current state without scheduling a refresh.",
            )
        ]
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        # When the frontend is polling for status updates we skip the kick
        # so each poll is a cheap read of the current state.
        is_poll = request.query_params.get("poll", "false").lower() == "true"
        if not is_poll:
            recommendations_facade.refresh_team_recommendations(self.team.id)
        recommendations = recommendations_facade.list_recommendations(self.team.id)
        page = self.paginate_queryset(recommendations)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(recommendations, many=True).data)

    @extend_schema(
        request=None,
        responses=ErrorTrackingRecommendationSerializer,
        parameters=[
            OpenApiParameter(
                name="force",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description="False skips the recompute when the current result is still fresh. Defaults to true.",
            )
        ],
    )
    @action(detail=True, methods=["post"])
    def refresh(self, request: Request, *args, pk=None, **kwargs) -> Response:
        force = request.query_params.get("force", "true").lower() != "false"
        try:
            recommendation = recommendations_facade.refresh_recommendation(self.team.id, pk, force=force)
        except recommendations_facade.RecommendationNotFoundError:
            raise NotFound()
        except recommendations_facade.UnknownRecommendationTypeError:
            return Response({"detail": "Unknown recommendation type."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(recommendation).data, status=status.HTTP_200_OK)

    @extend_schema(request=None, responses=ErrorTrackingRecommendationSerializer)
    @action(detail=True, methods=["post"])
    def dismiss(self, request: Request, *args, pk=None, **kwargs) -> Response:
        try:
            recommendation = recommendations_facade.dismiss_recommendation(self.team.id, pk)
        except recommendations_facade.RecommendationNotFoundError:
            raise NotFound()
        return Response(self.get_serializer(recommendation).data, status=status.HTTP_200_OK)

    @extend_schema(request=None, responses=ErrorTrackingRecommendationSerializer)
    @action(detail=True, methods=["post"])
    def restore(self, request: Request, *args, pk=None, **kwargs) -> Response:
        try:
            recommendation = recommendations_facade.restore_recommendation(self.team.id, pk)
        except recommendations_facade.RecommendationNotFoundError:
            raise NotFound()
        return Response(self.get_serializer(recommendation).data, status=status.HTTP_200_OK)

    @validated_request(
        query_serializer=MissingSymbolsExamplesQuerySerializer,
        responses={200: OpenApiResponse(response=MissingSymbolsExamplesSerializer)},
        summary="List frames missing symbols",
        description=(
            "List the files and builds whose recent stack frames miss source maps, mapping files or debug "
            "symbols on one platform, with the reason and how many frames each covers."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def source_maps_examples(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        platform = SymbolsPlatform(request.validated_query_data["platform"])
        examples = recommendations_facade.list_missing_symbols_examples(self.team.id, platform)
        return Response(MissingSymbolsExamplesSerializer(examples).data)
