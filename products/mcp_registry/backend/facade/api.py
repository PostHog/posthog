"""Cross-boundary surface of the MCP registry product.

Presentation (and, later, other products) reach registry capabilities through here rather
than importing internals. Each entrypoint takes primitive/caller context, drives the
`logic` layer, and maps ORM rows to `contracts` dataclasses before returning — Django
models never cross this boundary. The Celery/beat surface lives in `facade/tasks.py`
rather than here so its heavy imports stay off the request path.
"""

from typing import Any

from products.mcp_registry.backend import logic
from products.mcp_registry.backend.connect import build_connect_instructions
from products.mcp_registry.backend.constants import MCP_REGISTRY_FEATURE_FLAG as MCP_REGISTRY_FEATURE_FLAG
from products.mcp_registry.backend.models import MCPRegistryServer
from products.mcp_registry.backend.ranking import DEFAULT_RANKING_VERSION, RANKING_VERSIONS, latest_completed_run

from . import contracts

_DISCOVER_TOOLS_PER_CANDIDATE = 5


def known_ranking_versions() -> list[str]:
    return sorted(RANKING_VERSIONS)


def is_valid_version(version: str) -> bool:
    return version in RANKING_VERSIONS


def default_ranking_version() -> str:
    return DEFAULT_RANKING_VERSION


def _to_tool(tool: Any) -> contracts.RegistryTool:
    return contracts.RegistryTool(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        source=tool.source,
        last_seen_at=tool.last_seen_at,
    )


def _to_measured_stats(row: Any) -> contracts.MeasuredStats:
    return contracts.MeasuredStats(
        window_days=row.window_days,
        calls=row.calls,
        sessions=row.sessions,
        errors=row.errors,
        error_rate_pct=row.error_rate_pct,
        intent_coverage_pct=row.intent_coverage_pct,
        distinct_tools=row.distinct_tools,
        harness_count=row.harness_count,
        tool_stats=row.tool_stats,
        link_method=row.link_method,
        link_candidates=row.link_candidates,
        computed_at=row.computed_at,
    )


def _summary(server: MCPRegistryServer) -> contracts.RegistryServerSummary:
    return contracts.RegistryServerSummary(
        id=server.id,
        registry_name=server.registry_name,
        display_name=server.display_name,
        description=server.description,
        canonical_url=server.canonical_url,
        liveness=server.liveness,
        auth_method=server.auth_method,
        listed_in_registry=server.listed_in_registry,
        is_measured=server.is_measured,
        rank_score=getattr(server, "rank_score", None),
    )


def list_servers(
    *, version: str, search: str, measured_only: bool, team_id: int, caller_is_staff: bool
) -> list[contracts.RegistryServerSummary]:
    """Ranked summaries for the caller's visible index."""
    queryset = logic.ranked_queryset(
        version=version, search=search, measured_only=measured_only, team_id=team_id, caller_is_staff=caller_is_staff
    )
    return [_summary(server) for server in queryset]


def get_server_detail(*, pk: str, team_id: int, caller_is_staff: bool) -> contracts.RegistryServerDetail | None:
    """Full server record, or None when the caller may not see this server."""
    try:
        server = logic.get_server_for_caller(pk, team_id=team_id, caller_is_staff=caller_is_staff)
    except (MCPRegistryServer.DoesNotExist, ValueError):
        return None

    visibility = logic.measured_visibility(server, team_id, caller_is_staff)
    can_see_measured = bool(visibility.rows)
    latest_scores: list[contracts.ScoreInfo] = []
    for version in known_ranking_versions():
        run = latest_completed_run(version)
        if run is None:
            continue
        score = logic.score_for_run(run, server)
        if score is not None:
            latest_scores.append(
                contracts.ScoreInfo(
                    version=version,
                    score=score.score,
                    components=logic.visible_components(score.components, visibility.sees_every_row),
                    computed_at=run.computed_at,
                )
            )

    return contracts.RegistryServerDetail(
        **_summary(server).__dict__,
        remotes=server.remotes,
        packages=server.packages,
        repository_url=server.repository_url,
        website_url=server.website_url,
        last_probed_at=server.last_probed_at,
        tools=[_to_tool(tool) for tool in logic.visible_tools(server, can_see_measured)],
        measured_stats=[_to_measured_stats(row) for row in visibility.rows],
        scores=latest_scores,
        connect_instructions=build_connect_instructions(server),
    )


def discover_servers(
    *, intent: str, version: str, limit: int, team_id: int, caller_is_staff: bool
) -> list[contracts.DiscoverCandidate]:
    """Ranked candidates for a natural-language intent, each with its rationale."""
    tokens = logic.content_tokens(intent)
    servers = list(
        logic.ranked_queryset(
            version=version, search=intent, measured_only=False, team_id=team_id, caller_is_staff=caller_is_staff
        ).prefetch_related("tools", "measured_stats")[:limit]
    )
    run = latest_completed_run(version)

    candidates = []
    for index, server in enumerate(servers):
        score = logic.score_for_run(run, server)
        visibility = logic.measured_visibility(server, team_id, caller_is_staff)
        can_see_measured = bool(visibility.rows)
        candidates.append(
            contracts.DiscoverCandidate(
                rank=index + 1,
                id=server.id,
                registry_name=server.registry_name,
                title=server.display_name,
                description=server.description,
                score=getattr(server, "rank_score", None) or 0.0,
                why=logic.visible_components(score.components, visibility.sees_every_row) if score else {},
                liveness=server.liveness,
                auth_method=server.auth_method,
                measured=logic.measured_summary(visibility.rows),
                matched_tools=[
                    {"name": tool.name, "description": tool.description[:160], "source": tool.source}
                    for tool in logic.visible_tools(server, can_see_measured)
                    if any(token in tool.name.lower() for token in tokens)
                ][:_DISCOVER_TOOLS_PER_CANDIDATE],
                connect=build_connect_instructions(server),
            )
        )
    return candidates


def measured_projects() -> list[contracts.MeasuredProject]:
    """Which projects feed the measured layer, and how much each contributes. Staff only."""
    return [
        contracts.MeasuredProject(team_id=row["team_id"], servers=row["servers"], calls=row["total_calls"])
        for row in logic.measured_project_rollup()
    ]


def ranking_versions() -> list[contracts.RankingVersionInfo]:
    """Registered ranking versions and their latest completed runs."""
    payload = []
    for version in known_ranking_versions():
        run = latest_completed_run(version)
        payload.append(
            contracts.RankingVersionInfo(
                version=version,
                description=(RANKING_VERSIONS[version].__doc__ or "").strip().split("\n")[0],
                is_default=version == DEFAULT_RANKING_VERSION,
                latest_run=(
                    contracts.RankingRunInfo(id=run.id, server_count=run.server_count, computed_at=run.computed_at)
                    if run
                    else None
                ),
            )
        )
    return payload


def compare_rankings(
    *, versions: list[str], search: str, limit: int, team_id: int, caller_is_staff: bool
) -> dict[str, list[contracts.CompareRow]]:
    """Rank the same index under several versions side by side."""
    arms: dict[str, list[contracts.CompareRow]] = {}
    for version in versions:
        rows = logic.ranked_queryset(
            version=version, search=search, measured_only=False, team_id=team_id, caller_is_staff=caller_is_staff
        )[:limit]
        arms[version] = [
            contracts.CompareRow(
                rank=index + 1,
                id=server.id,
                registry_name=server.registry_name,
                display_name=server.display_name,
                score=getattr(server, "rank_score", None) or 0.0,
                is_measured=server.is_measured,
            )
            for index, server in enumerate(rows)
        ]
    return arms


def rank_deltas(arms: dict[str, list[contracts.CompareRow]], first: str, second: str) -> dict[str, int]:
    """Per-server rank movement between two arms (the review surface for promoting a version)."""
    second_ranks = {row.id: row.rank for row in arms[second]}
    return {str(row.id): second_ranks[row.id] - row.rank for row in arms[first] if row.id in second_ranks}
