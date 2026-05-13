from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api, contracts
from ..tasks import ping_monitor
from .serializers import (
    BulkCreateMonitorSerializer,
    CreateMonitorSerializer,
    MonitorSerializer,
    MonitorSummarySerializer,
    PingSerializer,
    SuggestedUrlSerializer,
)


class MonitorViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"

    @extend_schema(responses={200: MonitorSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        items = api.list_all()
        return Response(MonitorSerializer(items, many=True).data)

    @extend_schema(
        responses={200: MonitorSummarySerializer(many=True)},
        description="Per-monitor status, 30-day uptime, 24h latency, last ping, and 30 daily status buckets.",
    )
    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request: Request, **kwargs) -> Response:
        summaries = api.list_monitor_summaries(team_id=self.team_id)
        return Response(MonitorSummarySerializer(summaries, many=True).data)

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

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="days",
                type=int,
                required=False,
                description="Look-back window in days. Defaults to 30.",
            ),
            OpenApiParameter(
                name="limit",
                type=int,
                required=False,
                description="Maximum number of suggestions to return. Defaults to 20.",
            ),
        ],
        responses={200: SuggestedUrlSerializer(many=True)},
        description="Suggest pingable URLs derived from $pageview events, excluding hosts already monitored.",
    )
    @action(detail=False, methods=["get"], url_path="suggested_urls")
    def suggested_urls(self, request: Request, **kwargs) -> Response:
        days = int(request.query_params.get("days", 30))
        limit = int(request.query_params.get("limit", 20))
        suggestions = api.list_suggested_urls(team_id=self.team_id, days=days, limit=limit)
        return Response(SuggestedUrlSerializer(suggestions, many=True).data)

    @extend_schema(
        request=BulkCreateMonitorSerializer,
        responses={201: MonitorSerializer(many=True)},
        description="Create multiple monitors in a single atomic transaction. Used by the URL-suggester bulk add.",
    )
    @action(detail=False, methods=["post"], url_path="bulk_create")
    def bulk_create(self, request: Request, **kwargs) -> Response:
        serializer = BulkCreateMonitorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dtos = api.bulk_create(
            contracts.BulkCreateMonitorInput(
                team_id=self.team_id,
                items=[
                    contracts.BulkCreateMonitorItem(name=item["name"], url=item["url"])
                    for item in serializer.validated_data["monitors"]
                ],
            )
        )
        return Response(MonitorSerializer(dtos, many=True).data, status=status.HTTP_201_CREATED)
