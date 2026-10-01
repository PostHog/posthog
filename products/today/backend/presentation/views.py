"""DRF views for today. They read the request, call the facade and serialize the result."""

from typing import cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from ..facade import api
from ..facade.contracts import BriefingWrite
from .serializers import (
    BriefingSerializer,
    BriefingWriteSerializer,
    CandidateListSerializer,
    TodayErrorSerializer,
    TodayQuerySerializer,
)


class TodayViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "today"
    scope_object_read_actions = ["briefing", "candidates"]
    scope_object_write_actions = ["refresh", "write"]

    def _user(self) -> User:
        user = cast(User, self.request.user)
        if not api.is_enabled_for(user, self.team):
            raise NotFound()
        return user

    @validated_request(
        query_serializer=TodayQuerySerializer,
        responses={200: OpenApiResponse(response=BriefingSerializer)},
        summary="Get today's briefing",
        description="Today's personal briefing: a short text about the top 5 items and a left bar with the top 10. There are two editions a day, from 8:00 and from 12:00 local time. Starts generating the current edition when there is none yet; while it writes, the template draft is returned with status 'writing'.",
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
        responses={200: OpenApiResponse(response=BriefingSerializer)},
        summary="Refresh today's briefing",
        description="Regenerate the current edition of today's briefing. The ready briefing stays on screen until the new one is written.",
    )
    @action(detail=False, methods=["post"], url_path="briefing/refresh")
    def refresh(self, request: Request, **kwargs) -> Response:
        user = self._user()
        briefing = api.refresh_briefing(
            team=self.team, user=user, timezone_name=request.validated_query_data.get("timezone")
        )
        return Response(BriefingSerializer(briefing).data)

    @validated_request(
        request_serializer=BriefingWriteSerializer,
        responses={
            200: OpenApiResponse(response=BriefingSerializer),
            400: OpenApiResponse(response=TodayErrorSerializer),
            404: OpenApiResponse(response=TodayErrorSerializer),
        },
        summary="Write today's briefing",
        description="Store the text and the items of a briefing that is being generated for the current user. Only the briefing named in the generation prompt can be written. The text must link every item exactly once, highlight only the first item, keep labels to 6 words and signals to 40 characters, and use no em or en dashes; a 400 lists every rule the text broke so it can be fixed and sent again.",
    )
    @action(detail=False, methods=["post"], url_path="briefing/write")
    def write(self, request: TypedRequest[BriefingWrite], **kwargs) -> Response:
        user = self._user()
        try:
            briefing = api.write_briefing(team=self.team, user=user, write=request.validated_data)
        except api.BriefingNotFound:
            raise NotFound("No briefing with that id is being written for you.")
        except api.BriefingWriteRejected as rejected:
            return Response(
                {"detail": "The briefing broke these rules: " + "; ".join(rejected.problems)},
                status=status.HTTP_400_BAD_REQUEST,
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
