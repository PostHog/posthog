from typing import Any

from django.db.models import F, OuterRef, Q, QuerySet, Subquery

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import PostHogFeatureFlagPermission

from products.mcp_registry.backend.facade.api import (
    DEFAULT_RANKING_VERSION,
    MCP_REGISTRY_FEATURE_FLAG,
    RANKING_VERSIONS,
    build_connect_instructions,
    latest_completed_run,
)
from products.mcp_registry.backend.models import MCPRankingScore, MCPRegistryServer
from products.mcp_registry.backend.presentation.serializers import (
    MCPRankingVersionSerializer,
    MCPRegistryCompareRowSerializer,
    MCPRegistryServerDetailSerializer,
    MCPRegistryServerListSerializer,
)

_MAX_SEARCH_TOKENS = 5
_COMPARE_DEFAULT_LIMIT = 20
_COMPARE_MAX_LIMIT = 100


class MCPRegistryPagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 200


def _search_filter(search: str) -> Q:
    """Token-OR text match over server metadata and tool names.

    Deliberately simple: this is the v1 relevance layer, replaced by embedding-based
    capability search behind the same query parameter. The static rank_score ordering
    on top is what stays.
    """
    query = Q()
    for token in search.split()[:_MAX_SEARCH_TOKENS]:
        query |= (
            Q(display_name__icontains=token)
            | Q(registry_name__icontains=token)
            | Q(description__icontains=token)
            | Q(tools__name__icontains=token)
        )
    return query


class MCPRegistryServerViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Search and inspect the MCP registry index.

    The index is global (the same servers exist for every project); the endpoint is
    project-scoped only for auth and flag gating.
    """

    serializer_class = MCPRegistryServerListSerializer
    scope_object = "INTERNAL"
    posthog_feature_flag = MCP_REGISTRY_FEATURE_FLAG
    permission_classes = [PostHogFeatureFlagPermission]
    pagination_class = MCPRegistryPagination

    def dangerously_get_queryset(self) -> QuerySet:
        # Global rows: there is no team column to scope by; access control is the
        # flag + project membership on the route.
        return MCPRegistryServer.objects.all()

    def _resolve_version(self, request: Request) -> str:
        version = request.query_params.get("version") or DEFAULT_RANKING_VERSION
        if version not in RANKING_VERSIONS:
            raise ValidationError({"version": f"unknown ranking version; one of: {sorted(RANKING_VERSIONS)}"})
        return version

    def _ranked_queryset(self, version: str, search: str, measured_only: bool) -> QuerySet:
        queryset = self.dangerously_get_queryset()
        if search:
            queryset = queryset.filter(_search_filter(search)).distinct()
        if measured_only:
            queryset = queryset.filter(is_measured=True)
        run = latest_completed_run(version)
        if run is not None:
            score_subquery = MCPRankingScore.objects.filter(run=run, server=OuterRef("pk")).values("score")[:1]
            queryset = queryset.annotate(rank_score=Subquery(score_subquery)).order_by(
                F("rank_score").desc(nulls_last=True), "-is_measured", "display_name"
            )
        else:
            queryset = queryset.order_by("-is_measured", "display_name")
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Free-text query matched against server names, descriptions, and tool names.",
            ),
            OpenApiParameter(
                "version",
                OpenApiTypes.STR,
                description="Ranking version ordering the results; defaults to the current default version.",
            ),
            OpenApiParameter(
                "measured_only",
                OpenApiTypes.BOOL,
                description="Only servers with real MCP Analytics signal.",
            ),
        ],
        responses={200: MCPRegistryServerListSerializer(many=True)},
        description="List registry servers ordered by static rank under the chosen ranking version.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        version = self._resolve_version(request)
        queryset = self._ranked_queryset(
            version=version,
            search=(request.query_params.get("search") or "").strip(),
            measured_only=request.query_params.get("measured_only") in ("true", "1"),
        )
        page = self.paginate_queryset(queryset)
        serializer = MCPRegistryServerListSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        responses={200: MCPRegistryServerDetailSerializer},
        description="Full server record: tools, measured stats, per-version scores, connection instructions.",
    )
    def retrieve(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        server = self.get_object()
        latest_scores = []
        for version in sorted(RANKING_VERSIONS):
            run = latest_completed_run(version)
            if run is None:
                continue
            score = MCPRankingScore.objects.filter(run=run, server=server).first()
            if score is not None:
                latest_scores.append(
                    {
                        "version": version,
                        "score": score.score,
                        "components": score.components,
                        "computed_at": run.computed_at,
                    }
                )
        serializer = MCPRegistryServerDetailSerializer(
            server,
            context={
                "latest_scores": latest_scores,
                "connect_instructions": build_connect_instructions(server),
            },
        )
        return Response(serializer.data)

    @extend_schema(
        responses={200: MCPRankingVersionSerializer(many=True)},
        description="Registered ranking versions and their latest completed runs.",
    )
    @action(detail=False, methods=["GET"], pagination_class=None)
    def versions(self, request: Request, **kwargs) -> Response:
        payload = []
        for version in sorted(RANKING_VERSIONS):
            run = latest_completed_run(version)
            payload.append(
                {
                    "version": version,
                    "description": (RANKING_VERSIONS[version].__doc__ or "").strip().split("\n")[0],
                    "is_default": version == DEFAULT_RANKING_VERSION,
                    "latest_run": (
                        {
                            "id": str(run.id),
                            "server_count": run.server_count,
                            "computed_at": run.computed_at,
                        }
                        if run
                        else None
                    ),
                }
            )
        return Response(MCPRankingVersionSerializer(payload, many=True).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "versions",
                OpenApiTypes.STR,
                description="Comma-separated ranking versions to compare (2+).",
                required=True,
            ),
            OpenApiParameter("search", OpenApiTypes.STR, description="Optional text filter applied to every arm."),
            OpenApiParameter("limit", OpenApiTypes.INT, description="Rows per arm (default 20, max 100)."),
        ],
        responses={200: OpenApiTypes.OBJECT},
        description="Rank the same index under several ranking versions side by side. With exactly two "
        "versions the response includes per-server rank deltas, the review surface for promoting a "
        "new ranking version.",
    )
    @action(detail=False, methods=["GET"], pagination_class=None)
    def compare(self, request: Request, **kwargs) -> Response:
        raw_versions = [v.strip() for v in (request.query_params.get("versions") or "").split(",") if v.strip()]
        if len(raw_versions) < 2:
            raise ValidationError({"versions": "pass at least two comma-separated ranking versions"})
        unknown = [v for v in raw_versions if v not in RANKING_VERSIONS]
        if unknown:
            raise ValidationError({"versions": f"unknown ranking versions: {unknown}"})
        try:
            limit = min(int(request.query_params.get("limit", _COMPARE_DEFAULT_LIMIT)), _COMPARE_MAX_LIMIT)
        except ValueError:
            raise ValidationError({"limit": "must be an integer"})
        search = (request.query_params.get("search") or "").strip()

        # ReturnList from serializer .data, so typed loosely on purpose.
        arms: dict[str, Any] = {}
        for version in raw_versions:
            rows = self._ranked_queryset(version=version, search=search, measured_only=False)[:limit]
            arms[version] = MCPRegistryCompareRowSerializer(
                [
                    {
                        "rank": index + 1,
                        "id": server.id,
                        "registry_name": server.registry_name,
                        "display_name": server.display_name,
                        "score": getattr(server, "rank_score", None) or 0.0,
                        "is_measured": server.is_measured,
                    }
                    for index, server in enumerate(rows)
                ],
                many=True,
            ).data

        response: dict = {"versions": arms}
        if len(raw_versions) == 2:
            first, second = raw_versions
            second_ranks = {row["id"]: row["rank"] for row in arms[second]}
            response["rank_deltas"] = {
                str(row["id"]): second_ranks[row["id"]] - row["rank"]
                for row in arms[first]
                if row["id"] in second_ranks
            }
        return Response(response)
