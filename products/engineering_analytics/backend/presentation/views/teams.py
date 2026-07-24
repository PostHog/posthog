"""Team-level rollups: CI health, activity, and merge trend."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.facade.contracts import FLAKY_TEST_SIGNAL_CAVEAT
from products.engineering_analytics.backend.presentation.serializers.teams import (
    TeamCIActivitySerializer,
    TeamCIHealthListSerializer,
    TeamMergeTrendSerializer,
)
from products.engineering_analytics.backend.presentation.views._base import (
    _DATE_TO,
    _SOURCE_ID,
    EngineeringAnalyticsViewSetBase,
    _bad_request,
    _optional_int_param,
)


class TeamActionsMixin(EngineeringAnalyticsViewSetBase):
    READ_ACTIONS = ["team_ci_health", "team_ci_activity", "team_merge_trend"]

    @extend_schema(
        operation_id="engineering_analytics_team_ci_health",
        parameters=[
            OpenApiParameter(
                name="date_from",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Window start: relative ('-14d', '-7d') or ISO8601. Defaults to -14d; the window "
                "may span at most 30 days. An equal-length prior window is scanned for the *_prior twins; "
                "near the 30-day ceiling that prior window can reach past Traces retention, deflating "
                "*_prior counts and overstating deltas.",
            ),
            _DATE_TO,
            OpenApiParameter(
                name="min_failed_prs",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="An unrecovered test counts toward regression_test_count once it failed on at least "
                "this many distinct pull requests in the window. Minimum 1. Defaults to 3. Does not affect "
                "flaky_test_count, which needs proof, not a threshold.",
            ),
            OpenApiParameter(
                name="limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of teams to return (1-200). Defaults to 100.",
            ),
            _SOURCE_ID,
        ],
        responses={
            200: TeamCIHealthListSerializer,
            400: OpenApiResponse(
                description="Invalid date, threshold, limit, or source_id, or a window longer than 30 days."
            ),
        },
        description=(
            "Per-owning-team rollup of the CI test surfaces each team owns, over the same run evidence as "
            "flaky_tests and with the same meaning of flaky: flaky_test_count is owned tests one commit was "
            "seen both failing and passing in the window, regression_test_count is owned tests that failed "
            "with no such proof and still hit the blast-radius bar, plus failed/recovery/quarantined run counts. Each has an "
            "equal-length previous-window twin for honest deltas. Ownership is stamped on the spans at CI "
            "emission time from the repo's ownership map (products/*/product.yaml + CODEOWNERS); unstamped "
            "spans aggregate under the literal team 'unowned', and a re-stamped test lands under its latest "
            "owner only. Teams are organizational owners of code surfaces, never authors. " + FLAKY_TEST_SIGNAL_CAVEAT
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def team_ci_health(self, request: Request, **kwargs) -> Response:
        try:
            result = api.list_team_ci_health(
                team=self.team,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                min_failed_prs=_optional_int_param(request, "min_failed_prs"),
                limit=_optional_int_param(request, "limit"),
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date, threshold, limit, or source_id")
        return Response(TeamCIHealthListSerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_team_ci_activity",
        parameters=[
            OpenApiParameter(
                name="owner_team",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Owning team slug to scope to (as returned by team_ci_health), e.g. 'team-replay', "
                "or the literal 'unowned' for tests with no ownership stamp.",
            ),
            OpenApiParameter(
                name="date_from",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Window start: relative ('-14d', '-7d') or ISO8601. Defaults to -14d; the window "
                "may span at most 30 days. An equal-length prior window feeds the *_prior twins; near the "
                "30-day ceiling that prior window can reach past Traces retention, deflating *_prior counts.",
            ),
            _DATE_TO,
            OpenApiParameter(
                name="test_limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of per-test signal rows to return (1-100). Defaults to 25.",
            ),
            _SOURCE_ID,
        ],
        responses={
            200: TeamCIActivitySerializer,
            400: OpenApiResponse(
                description="Missing owner_team, invalid date, test_limit, or source_id, or a window longer "
                "than 30 days."
            ),
        },
        description=(
            "One owning team's CI test activity: per-test current-vs-prior signal pairs (the before/after "
            "comparison) over the window and its equal-length prior twin. Signal = runs where an owned "
            "test failed, errored, or a retry recovered it. " + FLAKY_TEST_SIGNAL_CAVEAT
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def team_ci_activity(self, request: Request, **kwargs) -> Response:
        try:
            result = api.get_team_ci_activity(
                team=self.team,
                owner_team=request.query_params.get("owner_team") or "",
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                test_limit=_optional_int_param(request, "test_limit"),
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid owner_team, date, test_limit, or source_id")
        return Response(TeamCIActivitySerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_team_merge_trend",
        parameters=[
            OpenApiParameter(
                name="owner_team",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Team slug to scope to (as returned by team_ci_health), matched against the "
                "GitHub org team slug of the source's team_members snapshot. The literal 'unowned' names "
                "an ownership gap, not an org team, and has no merge trend.",
            ),
            OpenApiParameter(
                name="date_from",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Window start: relative ('-14d', '-7d') or ISO8601. Defaults to -14d; the window "
                "may span at most 30 days.",
            ),
            _DATE_TO,
            _SOURCE_ID,
        ],
        responses={
            200: TeamMergeTrendSerializer,
            400: OpenApiResponse(
                description="Missing owner_team, invalid date or source_id, or a window longer than 30 days."
            ),
        },
        description=(
            "One team's daily time-to-merge trend: the median and average open→merge seconds over the PRs "
            "the team's members merged each day (PR author login → GitHub org team membership). Team-level "
            "aggregates only, never per-member figures or cross-team rankings. Timing is the coarse "
            "open→merge (draft + review time combined); bots are excluded. Requires the GitHub source's "
            "team_members snapshot; has_membership_data is false without it."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def team_merge_trend(self, request: Request, **kwargs) -> Response:
        try:
            result = api.get_team_merge_trend(
                team=self.team,
                owner_team=request.query_params.get("owner_team") or "",
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid owner_team, date, or source_id")
        return Response(TeamMergeTrendSerializer(instance=result).data)
