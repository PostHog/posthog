from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api, contracts
from .serializers import (
    CreateMonitorSerializer,
    MonitorSerializer,
    MonitorSummarySerializer,
    OutageSerializer,
    PingSerializer,
    UpdateMonitorSerializer,
)


class MonitorViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "uptime"
    # Responses are small bare arrays (a team has a handful of monitors); without this,
    # drf-spectacular assumes the default paginator and generates wrapper types that
    # don't match the runtime shape.
    pagination_class = None

    @extend_schema(responses={200: MonitorSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        items = api.list_all()
        return Response(MonitorSerializer(items, many=True).data)

    @extend_schema(
        responses={200: MonitorSummarySerializer(many=True)},
        description="Per-monitor status, 90-day uptime, 24h latency, last ping, and 90 daily status buckets.",
    )
    @action(detail=False, methods=["get"], url_path="summary", required_scopes=["uptime:read"])
    def summary(self, request: Request, **kwargs) -> Response:
        summaries = api.list_monitor_summaries(team_id=self.team_id)
        return Response(MonitorSummarySerializer(summaries, many=True).data)

    @extend_schema(
        responses={200: MonitorSummarySerializer, 404: OpenApiResponse(description="Monitor not found.")},
        description="Same data as the summary list, but for one monitor by id.",
    )
    def retrieve(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        summary = api.retrieve_monitor_summary(team_id=self.team_id, monitor_id=UUID(str(pk)))
        if summary is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(MonitorSummarySerializer(summary).data)

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

    @extend_schema(request=UpdateMonitorSerializer, responses={200: MonitorSerializer})
    def partial_update(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        serializer = UpdateMonitorSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        dto = api.update(
            contracts.UpdateMonitorInput(
                team_id=self.team_id,
                monitor_id=UUID(str(pk)),
                name=serializer.validated_data.get("name"),
                url=serializer.validated_data.get("url"),
            )
        )
        return Response(MonitorSerializer(dto).data)

    @extend_schema(responses={204: OpenApiResponse(description="Monitor deleted.")})
    def destroy(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        api.delete(team_id=self.team_id, monitor_id=UUID(str(pk)))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        responses={200: PingSerializer(many=True)},
        description="The 50 most recent pings for this monitor, newest first.",
    )
    @action(detail=True, methods=["get"], url_path="pings", required_scopes=["uptime:read"])
    def pings(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        pings = api.list_recent_pings(team_id=self.team_id, monitor_id=UUID(str(pk)))
        return Response(PingSerializer(pings, many=True).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="days",
                type=int,
                required=False,
                description="Look-back window in days. Defaults to 7.",
            ),
        ],
        responses={200: OutageSerializer(many=True)},
        description="Outages computed from raw pings: ongoing first, then most recently started resolved outages.",
    )
    @action(detail=True, methods=["get"], url_path="outages", required_scopes=["uptime:read"])
    def outages(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        days = int(request.query_params.get("days", 7))
        outages = api.list_outages_for_monitor(team_id=self.team_id, monitor_id=UUID(str(pk)), days=days)
        return Response(OutageSerializer(outages, many=True).data)
