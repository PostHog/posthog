from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api, contracts
from ..logic import SlugAlreadyTakenError
from ..tasks import ping_monitor
from .serializers import (
    BulkCreateMonitorSerializer,
    CreateIncidentSerializer,
    CreateMonitorSerializer,
    IncidentSerializer,
    MonitorSerializer,
    MonitorSummarySerializer,
    OutageSerializer,
    PingSerializer,
    PublicStatusPageSerializer,
    ReorderMonitorsSerializer,
    ResolveIncidentSerializer,
    StatusPageSerializer,
    SuggestedUrlSerializer,
    UpdateIncidentSerializer,
    UpdateMonitorSerializer,
    UpdateStatusPageSerializer,
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

    @extend_schema(responses={200: PingSerializer(many=True)})
    @action(detail=True, methods=["get"], url_path="pings")
    def pings(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        pings = api.list_recent_pings(team_id=self.team_id, monitor_id=pk)
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
    @action(detail=True, methods=["get"], url_path="outages")
    def outages(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        days = int(request.query_params.get("days", 7))
        outages = api.list_outages_for_monitor(team_id=self.team_id, monitor_id=UUID(str(pk)), days=days)
        return Response(OutageSerializer(outages, many=True).data)

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
        request=ReorderMonitorsSerializer,
        responses={204: OpenApiResponse(description="Display order saved.")},
        description="Persist the user-controlled display order. Position 0 renders first.",
    )
    @action(detail=False, methods=["post"], url_path="reorder")
    def reorder(self, request: Request, **kwargs) -> Response:
        serializer = ReorderMonitorsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        api.reorder(
            contracts.ReorderMonitorsInput(
                team_id=self.team_id,
                ordered_ids=serializer.validated_data["ordered_ids"],
            )
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

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


class IncidentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="monitor_id",
                type=OpenApiTypes.UUID,
                required=False,
                description="When provided, only incidents for this monitor are returned.",
            ),
        ],
        responses={200: IncidentSerializer(many=True)},
        description="Incidents for the team, ongoing first, then most recently started.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        monitor_id = request.query_params.get("monitor_id")
        if monitor_id:
            try:
                items = api.list_incidents_for_monitor(team_id=self.team_id, monitor_id=UUID(monitor_id))
            except ValueError as exc:
                raise ValidationError({"monitor_id": "Invalid UUID."}) from exc
        else:
            items = api.list_incidents(team_id=self.team_id)
        return Response(IncidentSerializer(items, many=True).data)

    @extend_schema(
        responses={200: IncidentSerializer, 404: OpenApiResponse(description="Incident not found.")},
    )
    def retrieve(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        try:
            dto = api.get_incident(team_id=self.team_id, incident_id=UUID(str(pk)))
        except Exception as exc:
            raise NotFound("Incident not found") from exc
        return Response(IncidentSerializer(dto).data)

    @extend_schema(request=CreateIncidentSerializer, responses={201: IncidentSerializer})
    def create(self, request: Request, **kwargs) -> Response:
        serializer = CreateIncidentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            dto = api.create_incident(
                contracts.CreateIncidentInput(
                    team_id=self.team_id,
                    monitor_id=serializer.validated_data["monitor_id"],
                    name=serializer.validated_data["name"],
                    description=serializer.validated_data.get("description", ""),
                    started_at=serializer.validated_data.get("started_at"),
                    resolved_at=serializer.validated_data.get("resolved_at"),
                    resolution_note=serializer.validated_data.get("resolution_note", ""),
                )
            )
        except Exception as exc:
            raise ValidationError({"monitor_id": "Monitor not found for this team."}) from exc
        return Response(IncidentSerializer(dto).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=UpdateIncidentSerializer, responses={200: IncidentSerializer})
    def partial_update(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        serializer = UpdateIncidentSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        # If the caller explicitly sends "resolved_at": null, that means "reopen the incident".
        # DRF's validated_data merges null into the field, but partial=True won't include the key
        # if it was absent — so we need to check the raw request to distinguish "omitted" from "set to null".
        clear_resolved_at = "resolved_at" in request.data and request.data.get("resolved_at") is None
        try:
            dto = api.update_incident(
                contracts.UpdateIncidentInput(
                    team_id=self.team_id,
                    incident_id=UUID(str(pk)),
                    name=serializer.validated_data.get("name"),
                    description=serializer.validated_data.get("description"),
                    started_at=serializer.validated_data.get("started_at"),
                    resolved_at=serializer.validated_data.get("resolved_at") if not clear_resolved_at else None,
                    resolution_note=serializer.validated_data.get("resolution_note"),
                    clear_resolved_at=clear_resolved_at,
                )
            )
        except Exception as exc:
            raise NotFound("Incident not found") from exc
        return Response(IncidentSerializer(dto).data)

    @extend_schema(responses={204: OpenApiResponse(description="Incident deleted.")})
    def destroy(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        api.delete_incident(team_id=self.team_id, incident_id=UUID(str(pk)))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=ResolveIncidentSerializer,
        responses={200: IncidentSerializer},
        description="Mark the incident as resolved with a required resolution note. The note is shown on the public status page.",
    )
    @action(detail=True, methods=["post"], url_path="resolve")
    def resolve(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        serializer = ResolveIncidentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            dto = api.resolve_incident(
                contracts.ResolveIncidentInput(
                    team_id=self.team_id,
                    incident_id=UUID(str(pk)),
                    resolution_note=serializer.validated_data["resolution_note"],
                )
            )
        except Exception as exc:
            raise NotFound("Incident not found") from exc
        return Response(IncidentSerializer(dto).data)

    @extend_schema(
        request=None,
        responses={200: IncidentSerializer},
        description="Reopen the incident, clearing resolved_at and the resolution note so it shows as ongoing again.",
    )
    @action(detail=True, methods=["post"], url_path="reopen")
    def reopen(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        try:
            dto = api.reopen_incident(team_id=self.team_id, incident_id=UUID(str(pk)))
        except Exception as exc:
            raise NotFound("Incident not found") from exc
        return Response(IncidentSerializer(dto).data)


class StatusPageViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"

    @extend_schema(responses={200: StatusPageSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        items = api.list_status_pages(team_id=self.team_id)
        return Response(StatusPageSerializer(items, many=True).data)

    @extend_schema(responses={200: StatusPageSerializer})
    def retrieve(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        try:
            page = api.get_status_page(team_id=self.team_id, page_id=UUID(str(pk)))
        except Exception as exc:
            raise NotFound("Status page not found") from exc
        return Response(StatusPageSerializer(page).data)

    @extend_schema(
        request=None,
        responses={201: StatusPageSerializer},
        description="Create a draft status page with default title, color, and slug. Returns the new draft.",
    )
    def create(self, request: Request, **kwargs) -> Response:
        page = api.create_status_page(team_id=self.team_id)
        return Response(StatusPageSerializer(page).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=UpdateStatusPageSerializer,
        responses={200: StatusPageSerializer},
        description="Patch any subset of title, slug, monitor_ids on the page.",
    )
    def partial_update(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        serializer = UpdateStatusPageSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            page = api.update_status_page(
                contracts.UpdateStatusPageInput(
                    team_id=self.team_id,
                    page_id=UUID(str(pk)),
                    title=serializer.validated_data.get("title"),
                    slug=serializer.validated_data.get("slug"),
                    monitor_ids=serializer.validated_data.get("monitor_ids"),
                )
            )
        except SlugAlreadyTakenError as exc:
            raise ValidationError({"slug": "This slug is already taken."}) from exc
        return Response(StatusPageSerializer(page).data)

    @extend_schema(request=None, responses={204: OpenApiResponse(description="Status page deleted.")})
    def destroy(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        api.delete_status_page(team_id=self.team_id, page_id=UUID(str(pk)))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=None,
        responses={200: StatusPageSerializer},
        description="Publish the status page. Makes it accessible at /status/<slug> without authentication.",
    )
    @action(detail=True, methods=["post"], url_path="publish")
    def publish(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        page = api.publish_status_page(team_id=self.team_id, page_id=UUID(str(pk)))
        return Response(StatusPageSerializer(page).data)

    @extend_schema(
        request=None,
        responses={200: StatusPageSerializer},
        description="Revert the status page to draft and remove public access.",
    )
    @action(detail=True, methods=["post"], url_path="unpublish")
    def unpublish(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        page = api.unpublish_status_page(team_id=self.team_id, page_id=UUID(str(pk)))
        return Response(StatusPageSerializer(page).data)


@extend_schema(tags=["uptime"])
class PublicStatusPageViewSet(viewsets.ViewSet):
    """Unauthenticated retrieval of a published status page by slug.

    Bypasses team and project scoping — the slug is globally unique and the resource is intentionally public.
    Returns 404 when the slug doesn't match a published page (drafts are not exposed).
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    lookup_field = "slug"
    lookup_value_regex = r"[a-z0-9-]+"

    @extend_schema(
        responses={
            200: PublicStatusPageSerializer,
            404: OpenApiResponse(description="No published status page matches this slug."),
        },
        parameters=[
            OpenApiParameter(
                name="slug",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description="Globally unique slug from the status page's settings.",
            )
        ],
        description="Public read-only payload for a published status page.",
    )
    def retrieve(self, request: Request, slug: str, **kwargs) -> Response:
        view = api.get_public_status_page(slug=slug)
        if view is None:
            raise NotFound("Status page not found")
        return Response(PublicStatusPageSerializer(view).data)
