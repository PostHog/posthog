"""Author-scoped reads: one author's delivery summary and pull request timelines."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.presentation.serializers.authors import (
    AuthorPullRequestTimelinesSerializer,
    AuthorSummarySerializer,
)
from products.engineering_analytics.backend.presentation.views._base import (
    _DATE_FROM,
    _DATE_TO,
    _REPO,
    _SOURCE_ID,
    EngineeringAnalyticsViewSetBase,
    _bad_request,
)

_AUTHOR = OpenApiParameter(
    name="author",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=True,
    description="GitHub login of the author.",
)


class AuthorActionsMixin(EngineeringAnalyticsViewSetBase):
    READ_ACTIONS = ["author_summary", "author_pull_request_timelines"]

    @extend_schema(
        operation_id="engineering_analytics_author_summary",
        parameters=[_AUTHOR, _DATE_FROM, _DATE_TO, _SOURCE_ID, _REPO],
        responses={
            200: AuthorSummarySerializer,
            400: OpenApiResponse(description="Missing author, or invalid date or source_id."),
        },
        description=(
            "One author's delivery and CI friction over a window (date_from default -30d), each figure next to the "
            "same figure over the whole repository: CI spend per merged PR, ready to merged split at the first "
            "approval, pushes after approval, merge-queue attempts, and lead time to deploy. Bots and drafts are "
            "excluded. Figures whose optional source isn't synced are null and flagged."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def author_summary(self, request: Request, **kwargs) -> Response:
        author = request.query_params.get("author")
        if not author:
            return Response({"detail": "author is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            summary = api.get_author_summary(
                team=self.team,
                author=author,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid author, date, or source_id")
        return Response(AuthorSummarySerializer(instance=summary).data)

    @extend_schema(
        operation_id="engineering_analytics_author_pull_request_timelines",
        parameters=[_AUTHOR, _DATE_FROM, _DATE_TO, _SOURCE_ID, _REPO],
        responses={
            200: AuthorPullRequestTimelinesSerializer,
            400: OpenApiResponse(description="Missing author, or invalid date or source_id."),
        },
        description=(
            "One author's open pull requests plus those merged in the window (date_from default -30d), each as a "
            "timeline of what it waited on from ready for review to merge or now: review, CI, red checks by what "
            "turned them green, and the merge queue."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def author_pull_request_timelines(self, request: Request, **kwargs) -> Response:
        author = request.query_params.get("author")
        if not author:
            return Response({"detail": "author is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            timelines = api.get_author_timelines(
                team=self.team,
                author=author,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid author, date, or source_id")
        return Response(AuthorPullRequestTimelinesSerializer(instance=timelines).data)
