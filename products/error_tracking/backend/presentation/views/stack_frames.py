from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action

from products.error_tracking.backend.facade import (
    api as error_tracking_api,
    contracts,
)
from products.error_tracking.backend.presentation.pagination import paginate_via_facade


class ErrorTrackingStackFrameSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.ErrorTrackingStackFrame


class ErrorTrackingStackFrameBatchGetRequestSerializer(serializers.Serializer):
    raw_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="Raw frame IDs in 'hash/part' format to resolve in a single request.",
    )
    symbol_set = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Optional symbol set reference to scope the lookup to a single symbol set.",
    )


class ErrorTrackingStackFrameBatchGetResponseSerializer(serializers.Serializer):
    results = ErrorTrackingStackFrameSerializer(many=True, help_text="Resolved stack frames for the requested raw IDs.")


class ErrorTrackingStackFrameViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    scope_object_read_actions = ["list", "retrieve", "batch_get"]
    scope_object_write_actions: list = []
    serializer_class = ErrorTrackingStackFrameSerializer

    def list(self, request, *args, **kwargs):
        return paginate_via_facade(
            self,
            request,
            lambda limit, offset: error_tracking_api.list_stack_frames(self.team.id, limit=limit, offset=offset),
        )

    def retrieve(self, request, *args, pk=None, **kwargs):
        frame = error_tracking_api.get_stack_frame(self.team.id, pk)
        if frame is None:
            raise NotFound()
        return Response(self.get_serializer(frame).data)

    @extend_schema(
        request=ErrorTrackingStackFrameBatchGetRequestSerializer,
        responses={200: OpenApiResponse(response=ErrorTrackingStackFrameBatchGetResponseSerializer)},
    )
    @action(methods=["POST"], detail=False)
    def batch_get(self, request, **kwargs):
        raw_ids = request.data.get("raw_ids", [])
        symbol_set = request.data.get("symbol_set", None)
        frames = error_tracking_api.batch_get_stack_frames(self.team.id, raw_ids, symbol_set)
        return Response({"results": self.get_serializer(frames, many=True).data})
