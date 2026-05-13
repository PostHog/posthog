from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api, contracts
from ..tasks import ping_monitor
from .serializers import CreateMonitorSerializer, MonitorSerializer, PingSerializer


class MonitorViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"

    @extend_schema(responses={200: MonitorSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        items = api.list_all()
        return Response(MonitorSerializer(items, many=True).data)

    @extend_schema(request=CreateMonitorSerializer, responses={201: MonitorSerializer})
    def create(self, request: Request, **kwargs) -> Response:
        serializer = CreateMonitorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dto = api.create(
            contracts.CreateMonitorInput(
                team_id=self.team_id,
                **serializer.validated_data,
            )
        )
        return Response(MonitorSerializer(dto).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: PingSerializer(many=True)})
    @action(detail=True, methods=["get"], url_path="pings")
    def pings(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        pings = api.list_recent_pings(team_id=self.team_id, monitor_id=pk)
        return Response(PingSerializer(pings, many=True).data)

    @extend_schema(
        request=None,
        responses={202: OpenApiResponse(description="Ping task enqueued.")},
    )
    @action(detail=True, methods=["post"], url_path="ping_now")
    def ping_now(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        ping_monitor.delay(str(pk))
        return Response(status=status.HTTP_202_ACCEPTED)
