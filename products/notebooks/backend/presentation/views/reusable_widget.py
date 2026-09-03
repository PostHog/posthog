from uuid import UUID

from django.http import Http404

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models import User

from products.notebooks.backend.facade.widgets import (
    WidgetConflictError,
    WidgetError,
    WidgetRateLimitError,
    get_reusable_widget,
    get_reusable_widget_status,
    is_notebook_widget_enabled,
    list_reusable_widgets,
    read_reusable_widget_demo_frame,
    read_reusable_widget_source,
    start_reusable_widget_generation,
)
from products.notebooks.backend.presentation.reusable_widget_serializers import (
    ReusableWidgetCatalogQuerySerializer,
    ReusableWidgetDetailSerializer,
    ReusableWidgetGenerateRequestSerializer,
    ReusableWidgetPageSerializer,
)
from products.notebooks.backend.presentation.widget_serializers import (
    WidgetErrorSerializer,
    WidgetFrameSerializer,
    WidgetSourceQuerySerializer,
    WidgetSourceSerializer,
    WidgetStatusSerializer,
)


class ReusableWidgetViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "notebook"
    required_scopes = ["notebook:read"]

    def _require_feature(self) -> None:
        if not is_notebook_widget_enabled(self.request.user):
            raise Http404()

    def _widget_id(self) -> UUID:
        try:
            return UUID(self.kwargs["pk"])
        except (KeyError, TypeError, ValueError) as error:
            raise Http404() from error

    def _error_response(self, error: WidgetError) -> Response:
        if isinstance(error, WidgetRateLimitError):
            status = 429
        elif isinstance(error, WidgetConflictError):
            status = 409
        elif error.code in {"widget_not_found", "frame_not_found"}:
            status = 404
        elif error.code == "ai_data_processing_not_approved":
            status = 403
        else:
            status = 400
        return Response(WidgetErrorSerializer({"code": error.code, "detail": error.detail}).data, status=status)

    @extend_schema(
        operation_id="reusable_widgets_list",
        responses={200: ReusableWidgetPageSerializer},
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("offset", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
        ],
    )
    def list(self, request: Request, **kwargs) -> Response:
        self._require_feature()
        query = ReusableWidgetCatalogQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        result = list_reusable_widgets(
            team_id=self.team_id,
            search=query.validated_data["search"],
            offset=query.validated_data["offset"],
            limit=query.validated_data["limit"],
        )
        return Response(ReusableWidgetPageSerializer(result).data)

    @extend_schema(
        operation_id="reusable_widgets_retrieve",
        responses={200: ReusableWidgetDetailSerializer, 404: WidgetErrorSerializer},
    )
    def retrieve(self, request: Request, **kwargs) -> Response:
        self._require_feature()
        try:
            result = get_reusable_widget(team_id=self.team_id, widget_id=self._widget_id())
        except WidgetError as error:
            return self._error_response(error)
        return Response(ReusableWidgetDetailSerializer(result).data)

    @extend_schema(
        operation_id="reusable_widgets_demo_frame",
        responses={200: WidgetFrameSerializer, 404: WidgetErrorSerializer},
        parameters=[
            OpenApiParameter(
                "frame_name",
                OpenApiTypes.STR,
                OpenApiParameter.PATH,
                description="Logical dataframe slot requested by the widget demo.",
            )
        ],
    )
    @action(
        methods=["GET"],
        detail=True,
        url_path="frames/(?P<frame_name>[^/.]+)",
        required_scopes=["notebook:read"],
    )
    def demo_frame(self, request: Request, frame_name: str | None = None, **kwargs) -> Response:
        self._require_feature()
        if frame_name is None:
            raise Http404()
        try:
            result = read_reusable_widget_demo_frame(
                team_id=self.team_id,
                widget_id=self._widget_id(),
                frame_name=frame_name,
            )
        except WidgetError as error:
            return self._error_response(error)
        return Response(WidgetFrameSerializer(result.frame).data)

    @extend_schema(
        operation_id="reusable_widgets_source",
        responses={200: WidgetSourceSerializer, 400: WidgetErrorSerializer, 404: WidgetErrorSerializer},
        parameters=[
            OpenApiParameter(
                "version_id",
                OpenApiTypes.UUID,
                OpenApiParameter.QUERY,
                required=False,
                description="Immutable reusable widget version whose source should be returned.",
            )
        ],
    )
    @action(methods=["GET"], detail=True, required_scopes=["notebook:read"])
    def source(self, request: Request, **kwargs) -> Response:
        self._require_feature()
        query = WidgetSourceQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            source = read_reusable_widget_source(
                team_id=self.team_id,
                widget_id=self._widget_id(),
                version_id=query.validated_data.get("version_id"),
            )
        except WidgetError as error:
            return self._error_response(error)
        return Response(WidgetSourceSerializer({"source": source}).data)

    @extend_schema(
        operation_id="reusable_widgets_generate",
        request=ReusableWidgetGenerateRequestSerializer,
        responses={
            202: WidgetStatusSerializer,
            400: WidgetErrorSerializer,
            403: WidgetErrorSerializer,
            404: WidgetErrorSerializer,
            409: WidgetErrorSerializer,
            429: WidgetErrorSerializer,
        },
    )
    @action(methods=["POST"], detail=True, required_scopes=["notebook:write"])
    def generate(self, request: Request, **kwargs) -> Response:
        self._require_feature()
        user = request.user
        if not isinstance(user, User):
            raise PermissionDenied("A user is required to change a reusable widget.")
        serializer = ReusableWidgetGenerateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["generation_operation"] == "initial":
            return self._error_response(
                WidgetError("Reusable widgets can only be improved or regenerated.", "operation_invalid")
            )
        expected_current_version_id = serializer.validated_data.get("expected_current_version_id")
        if expected_current_version_id is None:
            return self._error_response(
                WidgetError("Reload the reusable widget before updating it.", "generation_conflict")
            )
        try:
            result = start_reusable_widget_generation(
                team_id=self.team_id,
                widget_id=self._widget_id(),
                prompt=serializer.validated_data["prompt"],
                model=serializer.validated_data["model"],
                generation_id=serializer.validated_data["generation_id"],
                operation=serializer.validated_data["generation_operation"],
                expected_current_version_id=expected_current_version_id,
                user_id=user.id,
            )
        except WidgetError as error:
            return self._error_response(error)
        return Response(WidgetStatusSerializer(result).data, status=202)

    @extend_schema(
        operation_id="reusable_widgets_status",
        responses={200: WidgetStatusSerializer, 404: WidgetErrorSerializer, 409: WidgetErrorSerializer},
    )
    @action(methods=["GET"], detail=True, required_scopes=["notebook:read"])
    def status(self, request: Request, **kwargs) -> Response:
        self._require_feature()
        try:
            result = get_reusable_widget_status(team_id=self.team_id, widget_id=self._widget_id())
        except WidgetError as error:
            return self._error_response(error)
        return Response(WidgetStatusSerializer(result).data)
