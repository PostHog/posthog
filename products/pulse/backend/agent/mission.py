"""Mission bundle: everything a sandbox agent run needs, as data.

Tool grants are mission DATA (spec finding 3a): the bundle carries a list of MCP
grants serialized into the agent-server --mcpServers config. This module ships only
the PostHog MCP grant; new missions add grants, not code. The bundle never carries
secrets — the OAuth token is minted inside the run_agent activity so it never
enters Temporal payloads or persisted workflow history.
"""

import datetime as dt
import dataclasses
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.utils import timezone

from pydantic import BaseModel, Field

from posthog.models.team import Team

from products.pulse.backend.generation.gate import MAX_OPPORTUNITIES
from products.pulse.backend.models import BriefConfig, ProductBrief
from products.pulse.backend.sources.base import SourceItem

GENERAL_BRIEF_MISSION = "general_brief"
QUERY_PERFORMANCE_MISSION = "query_performance"
POSTHOG_MCP_SCOPES: list[str] = ["query:read", "insight:read", "dashboard:read"]


class McpToolGrant(BaseModel):
    name: str
    url: str
    scopes: list[str]
    headers: dict[str, str] = Field(default_factory=dict)

    def to_mcp_server_config(self, *, token: str) -> dict[str, Any]:
        """Shape matches the agent-server --mcpServers JSON (ACP McpServer schema),
        see products/tasks/backend/temporal/process_task/utils.py::McpServerConfig."""
        headers = [
            {"name": "Authorization", "value": f"Bearer {token}"},
            {"name": "x-posthog-mcp-consumer", "value": "pulse"},
            *({"name": name, "value": value} for name, value in self.headers.items()),
        ]
        return {"type": "http", "name": self.name, "url": self.url, "headers": headers}


class MissionBundle(BaseModel):
    mission: str
    team_id: int
    brief_id: str
    window_start: dt.datetime
    window_end: dt.datetime
    period_days: int
    focus_prompt: str
    # Serialized SourceItem dicts: heterogeneous untrusted JSON, hence Any values.
    seed_items: list[dict[str, Any]]
    tool_grants: list[McpToolGrant]
    max_opportunities: int = MAX_OPPORTUNITIES

    @property
    def required_scopes(self) -> list[str]:
        seen: dict[str, None] = {}
        for grant in self.tool_grants:
            for scope in grant.scopes:
                seen.setdefault(scope, None)
        return list(seen)


def _posthog_mcp_grant() -> McpToolGrant:
    return McpToolGrant(
        name="posthog",
        url=f"{settings.SITE_URL.rstrip('/')}/mcp",
        scopes=list(POSTHOG_MCP_SCOPES),
    )


def _query_performance_grant() -> McpToolGrant:
    # The internal grant is one data entry on the generic seam (spec finding 3a):
    # cluster-level query logs sit outside team scope, so they enter via this
    # dedicated scope rather than query:read.
    return McpToolGrant(
        name="query_performance",
        url=f"{settings.SITE_URL.rstrip('/')}/mcp",
        scopes=["clickhouse_test_cluster_perf:read"],
    )


def build_general_brief_mission(
    *, team: Team, brief: ProductBrief, config: BriefConfig | None, items: list[SourceItem]
) -> MissionBundle:
    window_end = timezone.now()
    return MissionBundle(
        mission=GENERAL_BRIEF_MISSION,
        team_id=team.pk,
        brief_id=str(brief.id),
        window_start=window_end - dt.timedelta(days=brief.period_days),
        window_end=window_end,
        period_days=brief.period_days,
        focus_prompt=(config.focus_prompt if config else "") or "the whole product",
        seed_items=[dataclasses.asdict(item) for item in items],
        tool_grants=[_posthog_mcp_grant()],
    )


def build_query_performance_mission(
    *, team: Team, brief: ProductBrief, config: BriefConfig | None, items: list[SourceItem]
) -> MissionBundle:
    base = build_general_brief_mission(team=team, brief=brief, config=config, items=items)
    return base.model_copy(
        update={
            "mission": QUERY_PERFORMANCE_MISSION,
            "tool_grants": [*base.tool_grants, _query_performance_grant()],
        }
    )


MissionBuilder = Callable[..., MissionBundle]

MISSION_BUILDERS: dict[str, MissionBuilder] = {
    GENERAL_BRIEF_MISSION: build_general_brief_mission,
    QUERY_PERFORMANCE_MISSION: build_query_performance_mission,
}
