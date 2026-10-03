"""DRF views for today. They read the request, call the facade and serialize the result."""

from collections.abc import Callable
from typing import cast

import structlog
from drf_spectacular.utils import OpenApiResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.llm.system_one import SystemOneNotConfigured, SystemOneRequestFailed
from posthog.models import User
from posthog.utils import UUID_REGEX

from products.signals.backend.facade import api as signals

from ..facade import api, contracts
from ..facade.enums import KeyClauseRole
from .serializers import (
    BriefingSerializer,
    CandidateListSerializer,
    ExcerptChoiceQuerySerializer,
    ExcerptChoiceSerializer,
    KeyClausesQuerySerializer,
    KeyClausesSerializer,
    ReportPageSerializer,
    TodayQuerySerializer,
)

logger = structlog.get_logger(__name__)
JEV_UNAVAILABLE = OpenApiResponse(description="The decision model is unavailable.")


class JevUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The decision model is unavailable."
    default_code = "jev_unavailable"


def _ask_jev[T](team_id: int, ask: Callable[[], T]) -> T:
    try:
        return ask()
    except (SystemOneNotConfigured, SystemOneRequestFailed) as error:
        logger.warning("today_jev_unavailable", team_id=team_id, reason=type(error).__name__)
        raise JevUnavailable() from error


class TodayViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "today"
    scope_object_read_actions = ["briefing", "candidates", "report_page", "key_clauses", "excerpt_choice"]
    scope_object_write_actions = ["refresh"]

    def _user(self) -> User:
        user = cast(User, self.request.user)
        # No briefing for this person: the page shows the report list instead.
        if not api.may_get_briefing(user, self.team):
            raise NotFound()
        return user

    def _jev_user(self) -> User:
        user = cast(User, self.request.user)
        if not api.may_ask_jev(user, self.team):
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

    @validated_request(
        responses={200: OpenApiResponse(response=ReportPageSerializer)},
        summary="Get a report's page",
        description="What the Today report page shows for a report: its lead, the proposal and the impact sentence cut to whole sentences, and the pull request it names. Sample report ids return the built-in sample reports. 404 when the report is missing or the person does not have the new navigation.",
    )
    @action(detail=False, methods=["get"], url_path=rf"reports/(?P<report_id>{UUID_REGEX}|sample-[a-z]+)/page")
    def report_page(self, request: Request, report_id: str, **kwargs) -> Response:
        if not api.is_enabled_for(cast(User, request.user), self.team):
            raise NotFound()
        page = api.report_page(team=self.team, report_id=report_id)
        if page is None:
            raise NotFound()
        return Response(ReportPageSerializer(page).data)

    @validated_request(
        request_serializer=KeyClausesQuerySerializer,
        responses={200: OpenApiResponse(response=KeyClausesSerializer), 503: JEV_UNAVAILABLE},
        summary="Mark the key clauses of a report",
        description="For each text the report page shows, the clauses that state the problem, its cause or the fix, each with sentences from the report that explain it. Only clauses the report explains further are returned, at most 2 across all texts. 404 when the report is missing or the person may not use Jev.",
    )
    @action(detail=False, methods=["post"], url_path=rf"reports/(?P<report_id>{UUID_REGEX})/key_clauses")
    def key_clauses(self, request: Request, report_id: str, **kwargs) -> Response:
        requests = [
            contracts.KeyClauseRequest(text=item["text"], roles=[KeyClauseRole(role) for role in item["roles"]])
            for item in request.validated_data["requests"]
        ]
        user = self._jev_user()
        texts = _ask_jev(
            self.team.id,
            lambda: api.report_key_clauses(team=self.team, user=user, report_id=report_id, requests=requests),
        )
        if texts is None:
            raise NotFound()
        return Response(KeyClausesSerializer({"texts": texts}).data)

    @validated_request(
        request_serializer=ExcerptChoiceQuerySerializer,
        responses={200: OpenApiResponse(response=ExcerptChoiceSerializer), 503: JEV_UNAVAILABLE},
        summary="Pick the code excerpt a finding describes",
        description="Asks the decision model which of several code excerpts shows what a finding describes. Returns null when it is unsure. 404 when the person may not use Jev.",
    )
    @action(detail=False, methods=["post"], url_path="excerpt_choice")
    def excerpt_choice(self, request: Request, **kwargs) -> Response:
        user = self._jev_user()
        index = _ask_jev(
            self.team.id,
            lambda: api.pick_code_excerpt(
                team=self.team,
                user=user,
                finding=request.validated_data["finding"],
                excerpts=request.validated_data["excerpts"],
            ),
        )
        return Response(ExcerptChoiceSerializer({"index": index}).data)
