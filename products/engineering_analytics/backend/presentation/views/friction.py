"""Friction read: every author's friction as a multiple of the typical author."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.presentation.serializers.friction import (
    AuthorFrictionDetailSerializer,
    AuthorFrictionListSerializer,
)
from products.engineering_analytics.backend.presentation.views._base import (
    _SOURCE_ID,
    EngineeringAnalyticsViewSetBase,
    _bad_request,
)

_GITHUB_TEAM = OpenApiParameter(
    name="github_team",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="GitHub team slug: list only the team's members, through the team membership table. Ranks stay "
    "repository-wide.",
)

_AUTHOR = OpenApiParameter(
    name="author",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=True,
    description="GitHub login of the author to show.",
)

_REPO = OpenApiParameter(
    name="repo",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="'owner/name' repository, when the selected source syncs several.",
)


class FrictionActionsMixin(EngineeringAnalyticsViewSetBase):
    READ_ACTIONS = ["author_friction", "author_friction_detail"]

    @extend_schema(
        operation_id="engineering_analytics_author_friction",
        parameters=[_GITHUB_TEAM, _SOURCE_ID, _REPO],
        responses={
            200: AuthorFrictionListSerializer,
            400: OpenApiResponse(description="Invalid source_id or repo."),
        },
        description=(
            "Every author's friction over pull requests merged in the last 30 days, most first: red CI they did "
            "not cause, re-runs that failed again, CI waits, the wait for the first approval, merge-queue time and "
            "kickouts, and rework. The score is a multiple of the typical author and never counts how much or how "
            "fast someone ships. Bots are excluded, and authors need at least 3 merged pull requests."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def author_friction(self, request: Request, **kwargs) -> Response:
        try:
            friction = api.get_author_friction(
                team=self.team,
                github_team=request.query_params.get("github_team") or None,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid source_id or repo")
        return Response(AuthorFrictionListSerializer(instance=friction).data)

    @extend_schema(
        operation_id="engineering_analytics_author_friction_detail",
        parameters=[_AUTHOR, _SOURCE_ID, _REPO],
        responses={
            200: AuthorFrictionDetailSerializer,
            400: OpenApiResponse(description="Missing author, or invalid source_id or repo."),
        },
        description=(
            "One author's friction over pull requests merged in the last 30 days, next to the median of each of "
            "the author's teams, and the author's pull requests that added the most friction. Bots are excluded."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def author_friction_detail(self, request: Request, **kwargs) -> Response:
        author = request.query_params.get("author")
        if not author:
            return Response({"detail": "author is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            detail = api.get_author_friction_detail(
                team=self.team,
                author=author,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid author, source_id or repo")
        return Response(AuthorFrictionDetailSerializer(instance=detail).data)
