from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api
from .serializers import ExecutionDetailSerializer, ExecutionFilterSerializer, ExecutionSummarySerializer


class ExecutionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"

    @extend_schema(
        parameters=[ExecutionFilterSerializer],
        responses={200: ExecutionSummarySerializer(many=True)},
        description="List workflow executions with optional filters.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        filters = ExecutionFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        items = api.list_executions(
            team_id=self.team_id,
            status=filters.validated_data.get("status"),
            execution_type=filters.validated_data.get("execution_type"),
            limit=filters.validated_data.get("limit", 50),
            offset=filters.validated_data.get("offset", 0),
        )
        return Response(ExecutionSummarySerializer(items, many=True).data)

    @extend_schema(
        responses={200: ExecutionDetailSerializer},
        description="Retrieve a workflow execution with its full event history.",
    )
    def retrieve(self, request: Request, pk: str = "", **kwargs) -> Response:
        detail = api.get_execution(pk, team_id=self.team_id)
        return Response(ExecutionDetailSerializer(detail).data, status=status.HTTP_200_OK)
