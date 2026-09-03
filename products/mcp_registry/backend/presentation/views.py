import re
from typing import Any

from django.db.models import Case, Exists, Expression, F, FloatField, OuterRef, Q, QuerySet, Subquery, Value, When
from django.db.models.functions import Coalesce, Power

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
from products.mcp_registry.backend.models import MCPMeasuredStats, MCPRankingScore, MCPRegistryServer, MCPRegistryTool
from products.mcp_registry.backend.presentation.serializers import (
    MCPDiscoverResponseSerializer,
    MCPRankingVersionSerializer,
    MCPRegistryCompareRowSerializer,
    MCPRegistryServerDetailSerializer,
    MCPRegistryServerListSerializer,
)

_MAX_SEARCH_TOKENS = 5
_COMPARE_DEFAULT_LIMIT = 20
_COMPARE_MAX_LIMIT = 100
_DISCOVER_DEFAULT_LIMIT = 5
_DISCOVER_MAX_LIMIT = 20
_DISCOVER_TOOLS_PER_CANDIDATE = 5
# Weight of the strongest single-token match (a verified-namespace hit), used to
# normalize relevance into [0, 1].
_MAX_TOKEN_WEIGHT = 4.0
# Fit outweighs authority: a server has to plausibly do the thing before its track
# record matters. Tuning these is a ranking-version decision, not a per-query one.
_FIT_EXPONENT = 0.6
_AUTHORITY_EXPONENT = 0.4
# Words that match nearly every server, so they only dilute relevance.
_STOPWORDS = frozenset(
    {"and", "any", "can", "for", "from", "get", "how", "into", "its", "make", "me", "my", "our", "the", "with", "you"}
)


def _measured_summary(stats: list[MCPMeasuredStats]) -> dict[str, Any] | None:
    """Combine a server's measured sources into one agent-readable trust summary."""
    total_calls = sum(row.calls for row in stats)
    if total_calls <= 0:
        return None
    return {
        "calls": total_calls,
        "sessions": sum(row.sessions for row in stats),
        "error_rate_pct": round(sum(row.error_rate_pct * row.calls for row in stats) / total_calls, 2),
        "intent_coverage_pct": round(sum(row.intent_coverage_pct * row.calls for row in stats) / total_calls, 2),
        "harness_count": max(row.harness_count for row in stats),
        "window_days": max(row.window_days for row in stats),
        "sources": len(stats),
    }


class MCPRegistryPagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 200


def _content_tokens(search: str) -> list[str]:
    """Query tokens worth matching on: stopwords carry no signal but match everything."""
    return [token for token in search.lower().split() if token not in _STOPWORDS and len(token) > 2][
        :_MAX_SEARCH_TOKENS
    ]


def _namespace_match(token: str) -> Q:
    """Whether the token appears in the server's reverse-DNS namespace.

    Worth more than any other match: the official registry validates namespace
    ownership, so `com.vercel/*` requires proving control of vercel.com, while a display
    name is free text anyone can set. Without this, third-party clones with the vendor's
    name in their title outrank the vendor's own server.

    The token is regex-escaped, so the pattern stays a literal bounded to the segment
    before the first slash.
    """
    return Q(registry_name__iregex=rf"^[^/]*{re.escape(token)}[^/]*/")


def _tool_match(token: str) -> Exists:
    """Whether any of the server's tools is named for the token.

    An Exists subquery rather than a join on `tools`: joining multiplies a server's row
    once per matching tool, which both duplicates it in the results and makes a
    row-wise relevance expression score the same server differently per copy.
    """
    return Exists(MCPRegistryTool.objects.filter(server=OuterRef("pk"), name__icontains=token))


def _search_filter(tokens: list[str]) -> Q:
    query = Q()
    for token in tokens:
        query |= (
            Q(display_name__icontains=token)
            | Q(registry_name__icontains=token)
            | Q(description__icontains=token)
            | Q(_tool_match(token))
        )
    return query


def _relevance_annotation(tokens: list[str]) -> Expression:
    """How well each server's own text answers the query.

    Counts distinct query tokens matched, weighting where the match landed: a server
    named for the thing beats one that mentions it in passing, and both beat a match
    that only appears in a tool name. Tool-name matches are worth least because a
    server exposing `list_data_products` is not thereby about product analytics, which
    is how the unweighted OR match used to rank an airtime vendor first.

    Lexical, so it cannot match a paraphrase ("watch user sessions" against "session
    replay"). Embedding-based capability search replaces this function; keeping
    relevance separate from the static score is what makes that swap local.
    """
    if not tokens:
        return Value(0.0, output_field=FloatField())
    expression: Expression = Value(0.0, output_field=FloatField())
    for token in tokens:
        expression = expression + Case(
            When(_namespace_match(token), then=Value(_MAX_TOKEN_WEIGHT)),
            When(display_name__icontains=token, then=Value(3.0)),
            When(registry_name__icontains=token, then=Value(3.0)),
            When(description__icontains=token, then=Value(2.0)),
            When(_tool_match(token), then=Value(0.5)),
            default=Value(0.0),
            output_field=FloatField(),
        )
    return expression


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
        """Rank by fit x authority, the product this whole thing exists to compute.

        `relevance` is how well the server's text answers the query; `rank_score` is
        liveness x trust from the ranking run, where trust is real usage signal for
        measured servers. They multiply rather than tie-break so neither can dominate:
        a strong match on a dead server loses, and so does a live measured server that
        does not do the thing. Exponents weight fit over authority.
        """
        queryset = self.dangerously_get_queryset()
        tokens = _content_tokens(search)
        if measured_only:
            queryset = queryset.filter(is_measured=True)
        run = latest_completed_run(version)
        if run is not None:
            score_subquery = MCPRankingScore.objects.filter(run=run, server=OuterRef("pk")).values("score")[:1]
            queryset = queryset.annotate(rank_score=Subquery(score_subquery))

        if not tokens:
            ordering = [F("rank_score").desc(nulls_last=True)] if run is not None else []
            return queryset.order_by(*ordering, "-is_measured", "display_name").distinct()

        queryset = queryset.filter(_search_filter(tokens)).annotate(
            relevance=_relevance_annotation(tokens) / (_MAX_TOKEN_WEIGHT * len(tokens))
        )
        if run is None:
            return queryset.order_by("-relevance", "-is_measured", "display_name").distinct()
        return (
            queryset.annotate(
                combined_score=Power(F("relevance"), _FIT_EXPONENT)
                * Power(Coalesce(F("rank_score"), Value(0.0)), _AUTHORITY_EXPONENT)
            )
            .order_by(F("combined_score").desc(nulls_last=True), "-is_measured", "display_name")
            .distinct()
        )

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

        tokens = intent.lower().split()[:_MAX_SEARCH_TOKENS]
        servers = list(
            self._ranked_queryset(version=version, search=intent, measured_only=False).prefetch_related(
                "tools", "measured_stats"
            )[:limit]
        )

        candidates = []
        for index, server in enumerate(servers):
            score = MCPRankingScore.objects.filter(run=latest_completed_run(version), server=server).first()
            stats = list(server.measured_stats.all())
            candidates.append(
                {
                    "rank": index + 1,
                    "id": server.id,
                    "registry_name": server.registry_name,
                    "title": server.display_name,
                    "description": server.description,
                    "score": getattr(server, "rank_score", None) or 0.0,
                    "why": score.components if score else {},
                    "liveness": server.liveness,
                    "auth_method": server.auth_method,
                    "measured": _measured_summary(stats),
                    "matched_tools": [
                        {"name": tool.name, "description": tool.description[:160], "source": tool.source}
                        for tool in server.tools.all()
                        if any(token in tool.name.lower() for token in tokens)
                    ][:_DISCOVER_TOOLS_PER_CANDIDATE],
                    "connect": build_connect_instructions(server),
                }
            )

        return Response(
            MCPDiscoverResponseSerializer({"intent": intent, "ranking_version": version, "candidates": candidates}).data
        )

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
