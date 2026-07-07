from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.facade import recommendations as recommendations_facade


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


class ErrorTrackingRecommendationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    scope_object_write_actions = ["refresh", "dismiss", "restore"]
    serializer_class = ErrorTrackingRecommendationSerializer

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

    @extend_schema(request=None, responses=ErrorTrackingRecommendationSerializer)
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
