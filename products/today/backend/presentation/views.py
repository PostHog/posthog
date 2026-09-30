"""DRF views for today. They read the request, call the facade and serialize the result."""

from typing import cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from ..facade import api
from .serializers import BriefingSerializer, CandidateListSerializer, TodayErrorSerializer, TodayQuerySerializer


class TodayViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "today"
    scope_object_read_actions = ["briefing", "candidates"]
    scope_object_write_actions = ["refresh"]

    def _user(self) -> User:
        user = cast(User, self.request.user)
        if not api.is_enabled_for(user, self.team):
            raise NotFound()
        return user

    @validated_request(
        query_serializer=TodayQuerySerializer,
        responses={200: OpenApiResponse(response=BriefingSerializer)},
        summary="Get today's briefing",
        description="Today's personal briefing: a short text about the top 5 items and a left bar with the top 10. Starts generating one when there is none yet; while it writes, the template draft is returned with status 'writing'.",
    )
    @action(detail=False, methods=["get"], url_path="briefing")
    def briefing(self, request: Request, **kwargs) -> Response:
        user = self._user()
        briefing = api.get_briefing(
            team=self.team, user=user, timezone_name=request.validated_query_data.get("timezone")
        )
        return Response(BriefingSerializer(briefing).data)

    @validated_request(
        query_serializer=TodayQuerySerializer,
        responses={
            200: OpenApiResponse(response=BriefingSerializer),
            429: OpenApiResponse(response=TodayErrorSerializer),
        },
        summary="Refresh today's briefing",
        description=f"Start a new generation of today's briefing. Allowed {api.MAX_REFRESHES_PER_DAY} times per day.",
    )
    @action(detail=False, methods=["post"], url_path="briefing/refresh")
    def refresh(self, request: Request, **kwargs) -> Response:
        user = self._user()
        try:
            briefing = api.refresh_briefing(
                team=self.team, user=user, timezone_name=request.validated_query_data.get("timezone")
            )
        except api.RefreshLimitReached:
            return Response(
                {
                    "detail": f"You can refresh your briefing {api.MAX_REFRESHES_PER_DAY} times a day. Try again tomorrow."
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        return Response(BriefingSerializer(briefing).data)

    @validated_request(
        query_serializer=TodayQuerySerializer,
        responses={200: OpenApiResponse(response=CandidateListSerializer)},
        summary="List today's ranked items",
        description="The ranked items behind today's briefing, with the facts and the reason for each, without the written text.",
    )
    @action(detail=False, methods=["get"], url_path="candidates")
    def candidates(self, request: Request, **kwargs) -> Response:
        user = self._user()
        candidates = api.list_candidates(
            team=self.team, user=user, timezone_name=request.validated_query_data.get("timezone")
        )
        return Response(CandidateListSerializer(candidates).data)
