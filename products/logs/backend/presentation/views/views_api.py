from typing import Any, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission

from products.logs.backend.facade import api, contracts

_FILTERS_HELP = (
    "Filter criteria — subset of LogsViewerFilters. May contain severityLevels, "
    "serviceNames, searchTerm, filterGroup, dateRange, and other keys."
)


class LogsViewSerializer(DataclassSerializer):
    filters = serializers.DictField(help_text=_FILTERS_HELP)

    class Meta:
        dataclass = contracts.LogsView


class LogsViewInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=400, help_text="User-visible name for the saved view.")
    filters = serializers.DictField(required=False, default=dict, help_text=_FILTERS_HELP)
    pinned = serializers.BooleanField(
        required=False, default=False, help_text="Whether the view is pinned in the saved-views list."
    )


class LogsViewViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "logs"
    lookup_field = "short_id"
    posthog_feature_flag = "logs-saved-views"
    permission_classes = [PostHogFeatureFlagPermission]

    def _track(self, event: str, view: contracts.LogsView) -> None:
        report_user_action(
            self.request.user,
            event,
            {
                "id": str(view.id),
                "short_id": view.short_id,
                "name": view.name,
                "pinned": view.pinned,
                "has_filters": bool(view.filters),
            },
            team=self.team,
            request=self.request,
        )

    @extend_schema(responses={200: LogsViewSerializer(many=True)})
    def list(self, request: Request, **kwargs: Any) -> Response:
        queryset = api.logs_views_queryset(self.team_id)
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(LogsViewSerializer(api.map_logs_views(page), many=True).data)
        return Response(LogsViewSerializer(api.map_logs_views(queryset), many=True).data)

    @extend_schema(
        parameters=[OpenApiParameter("short_id", OpenApiTypes.STR, OpenApiParameter.PATH)],
        responses={200: LogsViewSerializer},
    )
    def retrieve(self, request: Request, short_id: str, **kwargs: Any) -> Response:
        try:
            view = api.get_logs_view(self.team_id, short_id)
        except api.LogsViewNotFoundError:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(LogsViewSerializer(view).data)

    @extend_schema(request=LogsViewInputSerializer, responses={201: LogsViewSerializer})
    def create(self, request: Request, **kwargs: Any) -> Response:
        serializer = LogsViewInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        view = api.create_logs_view(
            team_id=self.team_id,
            created_by=cast(User, self.request.user),
            name=data["name"],
            filters=data["filters"],
            pinned=data["pinned"],
        )
        self._track("logs view created", view)
        return Response(LogsViewSerializer(view).data, status=status.HTTP_201_CREATED)

    def _update(self, request: Request, short_id: str, *, partial: bool) -> Response:
        serializer = LogsViewInputSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            view = api.update_logs_view(self.team_id, short_id, **serializer.validated_data)
        except api.LogsViewNotFoundError:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        self._track("logs view updated", view)
        return Response(LogsViewSerializer(view).data)

    @extend_schema(
        parameters=[OpenApiParameter("short_id", OpenApiTypes.STR, OpenApiParameter.PATH)],
        request=LogsViewInputSerializer,
        responses={200: LogsViewSerializer},
    )
    def update(self, request: Request, short_id: str, **kwargs: Any) -> Response:
        return self._update(request, short_id, partial=False)

    @extend_schema(
        parameters=[OpenApiParameter("short_id", OpenApiTypes.STR, OpenApiParameter.PATH)],
        request=LogsViewInputSerializer,
        responses={200: LogsViewSerializer},
    )
    def partial_update(self, request: Request, short_id: str, **kwargs: Any) -> Response:
        return self._update(request, short_id, partial=True)

    @extend_schema(
        parameters=[OpenApiParameter("short_id", OpenApiTypes.STR, OpenApiParameter.PATH)],
        responses={204: None},
    )
    def destroy(self, request: Request, short_id: str, **kwargs: Any) -> Response:
        try:
            view = api.delete_logs_view(self.team_id, short_id)
        except api.LogsViewNotFoundError:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        self._track("logs view deleted", view)
        return Response(status=status.HTTP_204_NO_CONTENT)
