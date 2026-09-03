from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import PostHogFeatureFlagPermission

from products.mcp_registry.backend.facade import api as registry_api
from products.mcp_registry.backend.facade.api import MCP_REGISTRY_FEATURE_FLAG
from products.mcp_registry.backend.presentation.serializers import (
    MCPDiscoverResponseSerializer,
    MCPMeasuredProjectSerializer,
    MCPMeasuredStatsSerializer,
    MCPRankingScoreInfoSerializer,
    MCPRankingVersionSerializer,
    MCPRegistryCompareRowSerializer,
    MCPRegistryServerDetailSerializer,
    MCPRegistryServerListSerializer,
    MCPRegistryToolSerializer,
)

_COMPARE_DEFAULT_LIMIT = 20
_COMPARE_MAX_LIMIT = 100
_DISCOVER_DEFAULT_LIMIT = 5
_DISCOVER_MAX_LIMIT = 20


class MCPRegistryPagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 200


class MCPRegistryServerViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Search and inspect the MCP registry index.

    The index is global (the same servers exist for every project); the endpoint is
    project-scoped only for auth and flag gating. Every read goes through the facade:
    this viewset parses the request and serializes the contract it gets back.
    """

    serializer_class = MCPRegistryServerListSerializer
    scope_object = "INTERNAL"
    posthog_feature_flag = MCP_REGISTRY_FEATURE_FLAG
    permission_classes = [PostHogFeatureFlagPermission]
    pagination_class = MCPRegistryPagination

    def _caller_is_staff(self) -> bool:
        return bool(getattr(self.request.user, "is_staff", False))

    def _caller_context(self) -> dict[str, Any]:
        return {"team_id": self.team.id, "caller_is_staff": self._caller_is_staff()}

    def _resolve_version(self, request: Request) -> str:
        version = request.query_params.get("version") or registry_api.default_ranking_version()
        if not registry_api.is_valid_version(version):
            raise ValidationError(
                {"version": f"unknown ranking version; one of: {registry_api.known_ranking_versions()}"}
            )
        return version

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
        summaries = registry_api.list_servers(
            version=version,
            search=(request.query_params.get("search") or "").strip(),
            measured_only=request.query_params.get("measured_only") in ("true", "1"),
            **self._caller_context(),
        )
        page = self.paginate_queryset(summaries)
        serializer = MCPRegistryServerListSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        responses={200: MCPRegistryServerDetailSerializer},
        description="Full server record: tools, measured stats, per-version scores, connection instructions.",
    )
    def retrieve(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        detail = registry_api.get_server_detail(pk=pk, **self._caller_context())
        if detail is None:
            raise NotFound()
        summary_fields = [
            "id",
            "registry_name",
            "display_name",
            "description",
            "canonical_url",
            "liveness",
            "auth_method",
            "listed_in_registry",
            "is_measured",
            "rank_score",
        ]
        serializer = MCPRegistryServerDetailSerializer(
            {
                **{field: getattr(detail, field) for field in summary_fields},
                "remotes": detail.remotes,
                "packages": detail.packages,
                "repository_url": detail.repository_url,
                "website_url": detail.website_url,
                "last_probed_at": detail.last_probed_at,
                "tools": MCPRegistryToolSerializer(detail.tools, many=True).data,
                "measured_stats": MCPMeasuredStatsSerializer(detail.measured_stats, many=True).data,
                "scores": MCPRankingScoreInfoSerializer(detail.scores, many=True).data,
                "connect": detail.connect_instructions,
            }
        )
        return Response(serializer.data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "intent",
                OpenApiTypes.STR,
                required=True,
                description="What the agent is trying to do, in natural language.",
            ),
            OpenApiParameter("version", OpenApiTypes.STR, description="Ranking version to rank candidates by."),
            OpenApiParameter("limit", OpenApiTypes.INT, description="Candidates to return (default 5, max 20)."),
        ],
        responses={200: MCPDiscoverResponseSerializer},
        description="Given a task, return the MCP servers most likely to do it, each with its rank rationale, "
        "real usage signal where we measure it, and ready-to-run connection instructions. One call is "
        "everything an agent needs to go from a task to a connected server.",
    )
    @action(detail=False, methods=["GET"], pagination_class=None)
    def discover(self, request: Request, **kwargs) -> Response:
        intent = (request.query_params.get("intent") or "").strip()
        if not intent:
            raise ValidationError({"intent": "describe what you are trying to do"})
        version = self._resolve_version(request)
        try:
            limit = min(int(request.query_params.get("limit", _DISCOVER_DEFAULT_LIMIT)), _DISCOVER_MAX_LIMIT)
        except ValueError:
            raise ValidationError({"limit": "must be an integer"})

        candidates = registry_api.discover_servers(
            intent=intent, version=version, limit=limit, **self._caller_context()
        )
        return Response(
            MCPDiscoverResponseSerializer({"intent": intent, "ranking_version": version, "candidates": candidates}).data
        )

    @extend_schema(
        responses={200: MCPMeasuredProjectSerializer(many=True)},
        description="Which projects feed MCP Analytics signal into the index, and how much each "
        "contributes. Staff only, because it reports across every project rather than the one in "
        "the route: it answers whether the measured layer has enough coverage to rank on.",
    )
    @action(detail=False, methods=["GET"], pagination_class=None)
    def measured_projects(self, request: Request, **kwargs) -> Response:
        if not self._caller_is_staff():
            raise PermissionDenied("Reporting across projects is limited to PostHog staff.")
        rows = registry_api.measured_projects()
        return Response(MCPMeasuredProjectSerializer(rows, many=True).data)

    @extend_schema(
        responses={200: MCPRankingVersionSerializer(many=True)},
        description="Registered ranking versions and their latest completed runs.",
    )
    @action(detail=False, methods=["GET"], pagination_class=None)
    def versions(self, request: Request, **kwargs) -> Response:
        payload = registry_api.ranking_versions()
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
        unknown = [v for v in raw_versions if not registry_api.is_valid_version(v)]
        if unknown:
            raise ValidationError({"versions": f"unknown ranking versions: {unknown}"})
        try:
            limit = min(int(request.query_params.get("limit", _COMPARE_DEFAULT_LIMIT)), _COMPARE_MAX_LIMIT)
        except ValueError:
            raise ValidationError({"limit": "must be an integer"})
        search = (request.query_params.get("search") or "").strip()

        arms = registry_api.compare_rankings(
            versions=raw_versions, search=search, limit=limit, **self._caller_context()
        )
        arms_data = {version: MCPRegistryCompareRowSerializer(rows, many=True).data for version, rows in arms.items()}

        response: dict = {"versions": arms_data}
        if len(raw_versions) == 2:
            first, second = raw_versions
            response["rank_deltas"] = registry_api.rank_deltas(arms, first, second)
        return Response(response)
