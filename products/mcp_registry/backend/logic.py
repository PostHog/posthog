"""Business rules and ORM access for the MCP registry.

Owns every `.objects` query, the visibility policy that decides what a caller may see,
and the queryset construction behind list/discover/compare. The facade is a thin
orchestration layer over this; presentation never reaches past the facade. The versioned
scoring functions stay in `ranking` (they are the versioning contract), and the crawl /
probe / aggregation pipelines keep their own modules — this module is the read-side and
task-facing business layer.
"""

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db.models import (
    Case,
    Count,
    Exists,
    Expression,
    F,
    FloatField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Power

from products.mcp_registry.backend.models import (
    MCPMeasuredStats,
    MCPRankingRun,
    MCPRankingScore,
    MCPRegistryServer,
    MCPRegistryTool,
)
from products.mcp_registry.backend.ranking import latest_completed_run

_MAX_SEARCH_TOKENS = 5
_MAX_TOKEN_WEIGHT = 4.0
# Fit outweighs authority: a server has to plausibly do the thing before its track
# record matters. Tuning these is a ranking-version decision, not a per-query one.
_FIT_EXPONENT = 0.6
_AUTHORITY_EXPONENT = 0.4
# Components computed from measured rows, so they carry the same disclosure risk.
_DERIVED_COMPONENT_KEYS = frozenset(
    {"trust", "measured_reliability", "measured_volume_confidence", "measured_intent_coverage"}
)
# Words that match nearly every server, so they only dilute relevance.
_STOPWORDS = frozenset(
    {"and", "any", "can", "for", "from", "get", "how", "into", "its", "make", "me", "my", "our", "the", "with", "you"}
)


@dataclass(frozen=True)
class MeasuredVisibility:
    rows: list[MCPMeasuredStats]
    sees_every_row: bool


def content_tokens(search: str) -> list[str]:
    """Query tokens worth matching on: stopwords carry no signal but match everything."""
    return [token for token in search.lower().split() if token not in _STOPWORDS and len(token) > 2][
        :_MAX_SEARCH_TOKENS
    ]


def visible_components(components: dict[str, Any], sees_every_row: bool) -> dict[str, Any]:
    """Score inputs, minus the ones computed from measurements this caller cannot see.

    A measured server's components are derived from every contributing project's rows, so
    handing them over whole would disclose by arithmetic what the tiering on the stats
    withholds directly. The rank itself stays: a caller may learn that a server ranks well
    and that real usage backs it, without the numbers behind it.
    """
    if sees_every_row or not components.get("measured"):
        return components
    return {key: value for key, value in components.items() if key not in _DERIVED_COMPONENT_KEYS}


def visible_tools(server: MCPRegistryServer, can_see_measured: bool) -> list[MCPRegistryTool]:
    """Tools known only from another project's traffic stay hidden.

    A probed tools/list is ours, because we asked the server for it. A tool learned from
    analytics is evidence of somebody's calls, so it follows the same tier as the stats.
    """
    tools = list(server.tools.all())
    if can_see_measured:
        return tools
    return [tool for tool in tools if tool.source != "analytics"]


def measured_visibility(server: MCPRegistryServer, team_id: int | None, is_staff: bool) -> MeasuredVisibility:
    """The measured rows this caller may see, and whether they are all of them.

    The second value gates the derived score components, which blend every contributing
    project's rows. Seeing one row is not licence to see a number computed from somebody
    else's, so a project sharing a server with other measurers gets its own figures and a
    redacted breakdown.

    Registry rows are global, but each stats row aggregates one project's own
    $mcp_tool_call events, so visibility is tiered. PostHog staff see every row, which is
    how we tell whether ranking behaves across the whole fleet instead of one project. A
    project sees its own rows. Anyone else sees none, because another customer's call
    volumes, error rates, and per-tool breakdowns are not ours to hand out.

    `measured_public` is deliberately not consulted. It is one boolean on a server that
    several projects contribute rows to, so it cannot record which contributor agreed to
    publish; a public surface needs a rule that can.
    """
    rows = list(server.measured_stats.all())
    if is_staff:
        return MeasuredVisibility(rows=rows, sees_every_row=True)
    # No row carries a null team_id, so a caller without a project matches nothing.
    visible = [row for row in rows if row.team_id == team_id]
    return MeasuredVisibility(rows=visible, sees_every_row=len(visible) == len(rows))


def measured_summary(stats: list[MCPMeasuredStats]) -> dict[str, Any] | None:
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


def base_queryset(team_id: int, caller_is_staff: bool) -> QuerySet:
    """Servers this caller may see at all.

    Registry rows are global, so there is normally no team column to scope by. The
    exception is a row absent from the official registry: it exists only because some
    project's events named a server we could not match, so the row and its name are
    that project's data rather than a public listing. The name is also unvalidated
    text from whoever captured the event, which is another reason not to show it to
    other customers. Those rows stay with the project that produced them, and staff.
    """
    queryset = MCPRegistryServer.objects.all()
    if caller_is_staff:
        return queryset
    measured_by_caller = Exists(MCPMeasuredStats.objects.for_team(team_id).filter(server=OuterRef("pk")))
    return queryset.filter(Q(listed_in_registry=True) | Q(measured_by_caller))


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


def ranked_queryset(*, version: str, search: str, measured_only: bool, team_id: int, caller_is_staff: bool) -> QuerySet:
    """Rank by fit x authority, the product this whole thing exists to compute.

    `relevance` is how well the server's text answers the query; `rank_score` is
    liveness x trust from the ranking run, where trust is real usage signal for
    measured servers. They multiply rather than tie-break so neither can dominate:
    a strong match on a dead server loses, and so does a live measured server that
    does not do the thing. Exponents weight fit over authority.
    """
    queryset = base_queryset(team_id, caller_is_staff)
    tokens = content_tokens(search)
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


def get_server_for_caller(pk: str | UUID, *, team_id: int, caller_is_staff: bool) -> MCPRegistryServer:
    """One visible server by id, 404ing for a caller who may not see it."""
    return base_queryset(team_id, caller_is_staff).get(pk=pk)


def score_for_run(run: MCPRankingRun | None, server: MCPRegistryServer) -> MCPRankingScore | None:
    if run is None:
        return None
    return MCPRankingScore.objects.filter(run=run, server=server).first()


def measured_project_rollup() -> list[dict[str, Any]]:
    """Per-project contribution to the measured layer (staff fleet view)."""
    return list(
        MCPMeasuredStats.objects.unscoped()
        .values("team_id")
        .annotate(servers=Count("server", distinct=True), total_calls=Sum("calls"))
        .order_by("-total_calls")
    )
