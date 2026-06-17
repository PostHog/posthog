from rest_framework import viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action

from products.error_tracking.backend.facade import (
    api as error_tracking_api,
    contracts,
)


class ErrorTrackingStackFrameSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.ErrorTrackingStackFrame


class ErrorTrackingStackFrameViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    scope_object_read_actions = ["list", "retrieve", "batch_get"]
    scope_object_write_actions: list = []
    serializer_class = ErrorTrackingStackFrameSerializer

    def list(self, request, *args, **kwargs):
        frames = error_tracking_api.list_stack_frames(self.team.id)
        page = self.paginate_queryset(frames)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(frames, many=True).data)

    def retrieve(self, request, *args, pk=None, **kwargs):
        frame = error_tracking_api.get_stack_frame(self.team.id, pk)
        if frame is None:
            raise NotFound()
        return Response(self.get_serializer(frame).data)

    @action(methods=["POST"], detail=False)
    def batch_get(self, request, **kwargs):
        raw_ids = request.data.get("raw_ids", [])
        symbol_set = request.data.get("symbol_set", None)
        frames = error_tracking_api.batch_get_stack_frames(self.team.id, raw_ids, symbol_set)
        return Response({"results": self.get_serializer(frames, many=True).data})
