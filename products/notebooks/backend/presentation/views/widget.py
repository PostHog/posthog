from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from products.notebooks.backend.presentation.widget_serializers import WidgetCatalogSerializer
from products.notebooks.backend.widgets import list_widgets


class WidgetViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "notebook"
    scope_object_read_actions = ["list"]

    @extend_schema(
        operation_id="notebook_widgets_list",
        responses={200: WidgetCatalogSerializer(many=True)},
        parameters=[
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Filter widgets by name or description.",
            )
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not isinstance(request.user, User):
            raise PermissionDenied("A user is required to view generated widgets.")
        widgets = list_widgets(
            team_id=self.team_id,
            user_id=request.user.id,
            search=request.query_params.get("search", "")[:400],
        )
        page = self.paginate_queryset(widgets)
        if page is not None:
            return self.get_paginated_response(WidgetCatalogSerializer(page, many=True).data)
        return Response(WidgetCatalogSerializer(widgets, many=True).data)
