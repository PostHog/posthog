"""Delivery reads: a scope's delivery summary, its pull request timelines, and an author's comparison with
their team."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.facade.contracts import QueryWorkLimitExceededError
from products.engineering_analytics.backend.presentation.serializers.delivery import (
    DeliveryComparisonSerializer,
    DeliverySummarySerializer,
    PullRequestTimelinesSerializer,
)
from products.engineering_analytics.backend.presentation.views._base import (
    _DATE_FROM,
    _DATE_TO,
    _SOURCE_ID,
    EngineeringAnalyticsViewSetBase,
    _bad_request,
    _optional_int_param,
)

_AUTHOR = OpenApiParameter(
    name="author",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="GitHub login: scope the read to this author's pull requests. Pass exactly one scope.",
)

_GITHUB_TEAM = OpenApiParameter(
    name="github_team",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="GitHub team slug: scope the read to pull requests authored by the team's members, through the team "
    "membership table. Pass exactly one scope.",
)

_PR_NUMBER = OpenApiParameter(
    name="pr_number",
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Pull request number: scope the read to this one pull request. Needs repo. Pass exactly one scope.",
)

_REPO = OpenApiParameter(
    name="repo",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="'owner/name' repository. Required with pr_number; otherwise it picks the repository when the "
    "selected source syncs several.",
)


_COMPARISON_AUTHOR = OpenApiParameter(
    name="author",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=True,
    description="GitHub login of the author to compare with their team and the repository.",
)

_FOCUS_PR_NUMBER = OpenApiParameter(
    name="pr_number",
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    required=False,
    description="A pull request by the author. Needs repo. A team of the author's that this pull request asked to "
    "review is the team to compare with, and the pull request stays out of the medians.",
)


class DeliveryActionsMixin(EngineeringAnalyticsViewSetBase):
    READ_ACTIONS = ["delivery_summary", "delivery_comparison", "pull_request_timelines"]

    @extend_schema(
        operation_id="engineering_analytics_delivery_summary",
        parameters=[_AUTHOR, _GITHUB_TEAM, _DATE_FROM, _DATE_TO, _SOURCE_ID, _REPO],
        responses={
            200: DeliverySummarySerializer,
            400: OpenApiResponse(description="Not exactly one of author or github_team, or invalid date or source_id."),
        },
        description=(
            "Delivery and CI friction for one author or one GitHub team over a window (date_from default -30d), each "
            "figure next to the same figure over the whole repository: CI spend per merged PR, ready to merged split "
            "at the first approval, pushes after approval, merge-queue attempts, and lead time to deploy. Bots and "
            "drafts are excluded. Figures whose optional source isn't synced are null and flagged."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def delivery_summary(self, request: Request, **kwargs) -> Response:
        try:
            summary = api.get_delivery_summary(
                team=self.team,
                author=request.query_params.get("author") or None,
                github_team=request.query_params.get("github_team") or None,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid scope, date, or source_id")
        return Response(DeliverySummarySerializer(instance=summary).data)

    @extend_schema(
        operation_id="engineering_analytics_delivery_comparison",
        parameters=[_COMPARISON_AUTHOR, _FOCUS_PR_NUMBER, _DATE_FROM, _DATE_TO, _SOURCE_ID, _REPO],
        responses={
            200: DeliveryComparisonSerializer,
            400: OpenApiResponse(description="Missing author, or invalid pr_number, date or source_id."),
        },
        description=(
            "One author's median ready to merged time, split at the first approval, next to the same medians for "
            "the author's own team and for the whole repository, over pull requests merged in the window "
            "(date_from default -30d). The team is picked from the author's GitHub teams that own code: a team "
            "that pr_number asked to review, else the team the author's pull requests asked to review most often, "
            "else every team. Bots and drafts are excluded."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def delivery_comparison(self, request: Request, **kwargs) -> Response:
        try:
            comparison = api.get_delivery_comparison(
                team=self.team,
                author=request.query_params.get("author") or None,
                pr_number=_optional_int_param(request, "pr_number"),
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid author, pull request, date, or source_id")
        return Response(DeliveryComparisonSerializer(instance=comparison).data)

    @extend_schema(
        operation_id="engineering_analytics_pull_request_timelines",
        parameters=[_AUTHOR, _GITHUB_TEAM, _PR_NUMBER, _REPO, _DATE_FROM, _DATE_TO, _SOURCE_ID],
        responses={
            200: PullRequestTimelinesSerializer,
            503: OpenApiResponse(description="The complete result exceeds the request's warehouse query budget."),
            400: OpenApiResponse(
                description="Not exactly one of author, github_team or pr_number, pr_number without repo, or invalid "
                "date or source_id."
            ),
        },
        description=(
            "Pull requests as timelines of what each waited on from ready for review to merge or now: review, CI, "
            "red checks by what turned them green, and the merge queue. Scope to one author or one GitHub team (open "
            "PRs plus PRs merged in the window, date_from default -30d), or to one pull request with pr_number and "
            "repo."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def pull_request_timelines(self, request: Request, **kwargs) -> Response:
        try:
            timelines = api.get_pull_request_timelines(
                team=self.team,
                author=request.query_params.get("author") or None,
                github_team=request.query_params.get("github_team") or None,
                pr_number=_optional_int_param(request, "pr_number"),
                repo=request.query_params.get("repo") or None,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid scope, date, or source_id")
        except QueryWorkLimitExceededError:
            return Response(
                {
                    "detail": "This scope needs too much data to load at once. Select a shorter date range or one author."
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(PullRequestTimelinesSerializer(instance=timelines).data)
