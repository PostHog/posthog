"""DRF views for today. They read the request, call the facade and serialize the result."""

from typing import cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from products.signals.backend.facade import api as signals

from ..facade import api
from .serializers import BriefingSerializer, CandidateListSerializer, TodayQuerySerializer


class TodayViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "today"
    scope_object_read_actions = ["briefing", "candidates"]
    scope_object_write_actions = ["refresh"]

    def _user(self) -> User:
        user = cast(User, self.request.user)
        # No briefing for this person: the page shows the report list instead.
        if not api.may_get_briefing(user, self.team):
            raise NotFound()
        return user

    @validated_request(
        query_serializer=TodayQuerySerializer,
        responses={200: OpenApiResponse(response=BriefingSerializer)},
        summary="Get today's briefing",
        description="Today's personal briefing: a short text about up to 5 items and the same items for the left bar. A new one is written every morning from 8:00 local time. Starts generating today's when there is none yet and returns it as 'collecting'. While a refresh is being written, the ready briefing is returned as 'writing', so it can stay on screen; poll again after a few seconds. 404 when the person gets no briefing: the flag is off, the organization has not approved AI data processing, or it is out of AI credits.",
    )
    @action(detail=False, methods=["get"], url_path="briefing")
    def briefing(self, request: Request, **kwargs) -> Response:
        user = self._user()
        briefing = api.get_briefing(
            team=self.team,
            user=user,
            timezone_name=request.validated_query_data.get("timezone"),
            metric_access=signals.ReportMetricAccessPolicy(request=request, team=self.team),
        )
        return Response(BriefingSerializer(briefing).data)

    @validated_request(
        query_serializer=TodayQuerySerializer,
        responses={200: OpenApiResponse(response=BriefingSerializer)},
        summary="Refresh today's briefing",
        description="Regenerate today's briefing. The ready briefing stays on screen until the new one is written.",
    )
    @action(detail=False, methods=["post"], url_path="briefing/refresh")
    def refresh(self, request: Request, **kwargs) -> Response:
        user = self._user()
        briefing = api.refresh_briefing(
            team=self.team,
            user=user,
            timezone_name=request.validated_query_data.get("timezone"),
            metric_access=signals.ReportMetricAccessPolicy(request=request, team=self.team),
        )
        return Response(BriefingSerializer(briefing).data)

    @validated_request(
        query_serializer=TodayQuerySerializer,
        responses={200: OpenApiResponse(response=CandidateListSerializer)},
        summary="List today's ranked items",
        description="The items behind today's briefing, with the facts and the reason for each, without the written text.",
    )
    @action(detail=False, methods=["get"], url_path="candidates")
    def candidates(self, request: Request, **kwargs) -> Response:
        user = self._user()
        candidates = api.list_candidates(
            team=self.team, user=user, timezone_name=request.validated_query_data.get("timezone")
        )
        return Response(CandidateListSerializer(candidates).data)
