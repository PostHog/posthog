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
from rest_framework.throttling import BaseThrottle, UserRateThrottle

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.llm.system_one import SystemOneNotConfigured, SystemOneRequestFailed
from posthog.models import User
from posthog.permissions import get_authenticator_scopes
from posthog.rate_limit import BurstRateThrottle, SustainedRateThrottle
from posthog.utils import UUID_REGEX

from products.signals.backend.facade import api as signals

from ..facade import api, contracts
from .serializers import (
    ExcerptChoiceRequestSerializer,
    ExcerptChoiceSerializer,
    FigureMarksSerializer,
    HighlightsSerializer,
    KeyClausesQuerySerializer,
    PulsePinsSerializer,
    ReportKeyClausesSerializer,
    ReportPageSerializer,
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


class PulsePinsBurstThrottle(UserRateThrottle):
    scope = "today_pulse_pins_burst"
    rate = "30/minute"


class PulsePinsSustainedThrottle(UserRateThrottle):
    scope = "today_pulse_pins_sustained"
    rate = "300/day"


PULSE_PIN_THROTTLES = [BurstRateThrottle, SustainedRateThrottle, PulsePinsBurstThrottle, PulsePinsSustainedThrottle]


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
    scope_object_read_actions = ["excerpt_choice", "highlights", "pulse_pins"]
    scope_object_write_actions = ["set_pulse_pins"]

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action == "set_pulse_pins":
            return [throttle() for throttle in PULSE_PIN_THROTTLES]
        return super().get_throttles()

    def _jev_user(self) -> User:
        user = cast(User, self.request.user)
        if not api.may_ask_jev(user, self.team):
            raise NotFound()
        return user

    def _check_report_access(self, user: User) -> None:
        if not signals.may_read_reports(user=user, team=self.team):
            raise PermissionDenied()

    @validated_request(
        responses={200: OpenApiResponse(response=HighlightsSerializer)},
        summary="Get today's highlights",
        description="The project's key metrics and up to 6 ranked items, each labeled risk or opportunity. Queries, rules and copy templates make every item; no AI is used. The highlights are computed in the background and stay fresh for 15 minutes per person, or 1 minute when a source failed. The call never waits: while they are computed, it returns `computing` with the last ready highlights of the day, so poll every 2 seconds until the status is `ready` or `failed`. 404 when the person does not have the new navigation. A scoped key needs query:read as well, because every highlight runs a query.",
    )
    @action(detail=False, methods=["get"], url_path="highlights", required_scopes=["today:read", "query:read"])
    def highlights(self, request: Request, **kwargs) -> Response:
        user = cast(User, request.user)
        if not api.is_enabled_for(user, self.team):
            raise NotFound()
        scopes = get_authenticator_scopes(request.successful_authenticator)
        found = api.get_highlights(team=self.team, user=user, scopes=None if scopes is None else frozenset(scopes))
        return Response(HighlightsSerializer(found).data)

    @validated_request(
        responses={200: OpenApiResponse(response=PulsePinsSerializer)},
        summary="Get the numbers the person keeps",
        description="The numbers the person keeps at the start of the key numbers on their home, in order. Suggestions fill the free places. 404 when the person does not have the new navigation.",
    )
    @action(detail=False, methods=["get"], url_path="pulse_pins")
    def pulse_pins(self, request: Request, **kwargs) -> Response:
        user = cast(User, request.user)
        if not api.is_enabled_for(user, self.team):
            raise NotFound()
        scopes = get_authenticator_scopes(request.successful_authenticator)
        found = api.get_pulse_pins(team=self.team, user=user, scopes=None if scopes is None else frozenset(scopes))
        return Response(PulsePinsSerializer(found).data)

    @validated_request(
        request_serializer=PulsePinsSerializer,
        responses={200: OpenApiResponse(response=PulsePinsSerializer)},
        summary="Set the numbers the person keeps",
        description="Replaces the numbers the person keeps at the start of the key numbers, in order. Repeated keys are dropped and only the first 4 are kept. The next highlights request computes the new numbers. 404 when the person does not have the new navigation.",
    )
    @pulse_pins.mapping.put
    def set_pulse_pins(self, request: Request, **kwargs) -> Response:
        user = cast(User, request.user)
        if not api.is_enabled_for(user, self.team):
            raise NotFound()
        saved = api.set_pulse_pins(team=self.team, user=user, pins=request.validated_data.pins)
        return Response(PulsePinsSerializer(saved).data)

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
