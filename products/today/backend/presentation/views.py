"""DRF views for today. They read the request, call the facade and serialize the result."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import structlog
from drf_spectacular.utils import OpenApiResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.llm.system_one import SystemOneNotConfigured, SystemOneRequestFailed
from posthog.models import User
from posthog.rate_limit import BurstRateThrottle, SustainedRateThrottle
from posthog.utils import UUID_REGEX

from products.signals.backend.facade import api as signals

from ..facade import api, contracts
from .serializers import (
    BriefingSerializer,
    CandidateListSerializer,
    ExcerptChoiceRequestSerializer,
    ExcerptChoiceSerializer,
    FigureMarksSerializer,
    KeyClausesQuerySerializer,
    ReportKeyClausesSerializer,
    ReportPageSerializer,
    TodayQuerySerializer,
)

logger = structlog.get_logger(__name__)
JEV_UNAVAILABLE = OpenApiResponse(description="The decision model is unavailable.")


class JevUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The decision model is unavailable."
    default_code = "jev_unavailable"


class JevBurstThrottle(UserRateThrottle):
    scope = "today_jev_burst"
    rate = "60/minute"


class JevSustainedThrottle(UserRateThrottle):
    scope = "today_jev_sustained"
    rate = "1500/day"


JEV_THROTTLES = [BurstRateThrottle, SustainedRateThrottle, JevBurstThrottle, JevSustainedThrottle]


@contextmanager
def _jev_errors_as_responses(team_id: int) -> Iterator[None]:
    try:
        yield
    except SystemOneRequestFailed as error:
        logger.warning("today_jev_unavailable", team_id=team_id, reason=type(error).__name__, status=error.status_code)
        raise JevUnavailable() from error
    except (SystemOneNotConfigured, contracts.JevTimedOut) as error:
        logger.warning("today_jev_unavailable", team_id=team_id, reason=type(error).__name__)
        raise JevUnavailable() from error


class TodayViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "today"
    scope_object_read_actions = ["briefing", "candidates", "excerpt_choice"]
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

    def _check_report_access(self, user: User) -> None:
        if not signals.may_read_reports(user=user, team=self.team):
            raise PermissionDenied()

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
        description="What the Today report page shows for a report: its lead, the proposal and the impact sentence cut to whole sentences, and the pull request it names. Sample report ids return the built-in sample reports. 404 when the report is missing or the person does not have the new navigation. 403 when the person may not read Inbox reports, and a scoped key needs task:read as well, because the page shows the report's signals.",
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=rf"reports/(?P<report_id>{UUID_REGEX}|sample-[a-z]+)/page",
        required_scopes=["today:read", "task:read"],
    )
    def report_page(self, request: Request, report_id: str, **kwargs) -> Response:
        user = cast(User, request.user)
        if not api.is_enabled_for(user, self.team):
            raise NotFound()
        self._check_report_access(user)
        page = api.report_page(team=self.team, report_id=report_id)
        if page is None:
            raise NotFound()
        return Response(ReportPageSerializer(page).data)

    @validated_request(
        query_serializer=KeyClausesQuerySerializer,
        responses={
            200: OpenApiResponse(response=ReportKeyClausesSerializer),
            503: JEV_UNAVAILABLE,
        },
        summary="Mark the key clauses of a report",
        description="The clauses in the report page's lead, impact sentence and proposal that state the problem, its cause or the fix, each with sentences from the report that explain it. Only clauses the report explains further are returned, at most 2 across all texts. 404 when the report is missing or the person may not use Jev.",
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=rf"reports/(?P<report_id>{UUID_REGEX})/key_clauses",
        required_scopes=["today:read", "task:read"],
        throttle_classes=JEV_THROTTLES,
    )
    def key_clauses(self, request: Request, report_id: str, **kwargs) -> Response:
        user = self._jev_user()
        self._check_report_access(user)
        include_impact = request.validated_query_data["include_impact"]
        with _jev_errors_as_responses(self.team.id):
            found = api.report_key_clauses(
                team=self.team, user=user, report_id=report_id, include_impact=include_impact
            )
        if found is None:
            raise NotFound()
        return Response(ReportKeyClausesSerializer(found).data)

    @validated_request(
        responses={200: OpenApiResponse(response=FigureMarksSerializer), 503: JEV_UNAVAILABLE},
        summary="Mark the numbers of a report with their sources",
        description="The numbers in the report's lead and impact sentence that a signal or the agent's research states, each with the sentence that states it. A number is marked only when the decision model is sure it is a measured result and that one source states the same result. 404 when the report is missing or the person may not use Jev.",
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=rf"reports/(?P<report_id>{UUID_REGEX})/figure_marks",
        required_scopes=["today:read", "task:read"],
        throttle_classes=JEV_THROTTLES,
    )
    def figure_marks(self, request: Request, report_id: str, **kwargs) -> Response:
        user = self._jev_user()
        self._check_report_access(user)
        with _jev_errors_as_responses(self.team.id):
            marks = api.report_figure_marks(team=self.team, user=user, report_id=report_id)
        if marks is None:
            raise NotFound()
        return Response(FigureMarksSerializer({"marks": marks}).data)

    @validated_request(
        request_serializer=ExcerptChoiceRequestSerializer,
        responses={
            200: OpenApiResponse(response=ExcerptChoiceSerializer),
            503: JEV_UNAVAILABLE,
        },
        summary="Pick the code excerpt a finding describes",
        description="Asks the decision model which of several code excerpts shows what a finding describes. Returns null when it is unsure. 404 when the person may not use Jev.",
    )
    @action(detail=False, methods=["post"], url_path="excerpt_choice", throttle_classes=JEV_THROTTLES)
    def excerpt_choice(self, request: Request, **kwargs) -> Response:
        user = self._jev_user()
        with _jev_errors_as_responses(self.team.id):
            index = api.pick_code_excerpt(
                team=self.team,
                user=user,
                finding=request.validated_data["finding"],
                excerpts=request.validated_data["excerpts"],
            )
        return Response(ExcerptChoiceSerializer({"index": index}).data)
