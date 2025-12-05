from django.db.models import Q

import structlog
from rest_framework import serializers, viewsets
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action

from products.error_tracking.backend.models import ErrorTrackingStackFrame

from .releases import ErrorTrackingReleaseSerializer

logger = structlog.get_logger(__name__)


class ErrorTrackingStackFrameSerializer(serializers.ModelSerializer):
    symbol_set_ref = serializers.CharField(source="symbol_set.ref", default=None)
    release = ErrorTrackingReleaseSerializer(source="symbol_set.release", read_only=True)
    raw_id = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingStackFrame
        fields = ["id", "raw_id", "created_at", "contents", "resolved", "context", "symbol_set_ref", "release"]

    def get_raw_id(self, obj):
        return obj.raw_id + "/" + str(obj.part)


class ErrorTrackingStackFrameViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingStackFrame.objects.all()
    serializer_class = ErrorTrackingStackFrameSerializer

    @action(methods=["POST"], detail=False)
    def batch_get(self, request, **kwargs):
        raw_ids = request.data.get("raw_ids", [])
        symbol_set = request.data.get("symbol_set", None)

        queryset = self.queryset.filter(team_id=self.team.id).select_related("symbol_set__release")

        if raw_ids:
            query_id_objects = Q()
            for raw_id in raw_ids:
                hash_id, part = get_raw_id_part(raw_id)
                query_id_objects |= Q(raw_id=hash_id, part=part)

            queryset = queryset.filter(query_id_objects)

        if symbol_set:
            queryset = queryset.filter(symbol_set=symbol_set)

        serializer = self.get_serializer(queryset, many=True)
        return Response({"results": serializer.data})


def get_raw_id_part(raw_id):
    res = raw_id.split("/")
    if len(res) != 2:
        return raw_id, 0
    return res[0], int(res[1])
