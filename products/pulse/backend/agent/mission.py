"""Mission bundle: everything a sandbox agent run needs, as data.

Tool grants are mission DATA (spec finding 3a): the bundle carries a list of MCP
grants serialized into the agent-server --mcpServers config. This module ships only
the PostHog MCP grant; new missions add grants, not code. The bundle never carries
secrets — the OAuth token is minted inside the run_agent activity so it never
enters Temporal payloads or persisted workflow history.
"""

import datetime as dt
import dataclasses
from typing import Any

from django.conf import settings
from django.utils import timezone

from pydantic import BaseModel, Field

from posthog.models.team import Team

from products.pulse.backend.generation.gate import MAX_OPPORTUNITIES, gate_thresholds
from products.pulse.backend.generation.goal import GoalStatus
from products.pulse.backend.models import BriefConfig, ProductBrief
from products.pulse.backend.sources.base import SourceItem

GENERAL_BRIEF_MISSION = "general_brief"
# The sandbox agent self-serves enrichment via these read scopes: base analytics plus feature-flag
# rollouts and heatmap hotspots, so it can investigate flags/heatmaps when they bear on the goal.
POSTHOG_MCP_SCOPES: list[str] = [
    "query:read",
    "insight:read",
    "dashboard:read",
    "feature_flag:read",
    "heatmap:read",
]


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
    # Serialized GoalStatus (dataclasses.asdict) or None for a goalless brief. Rendered into the
    # mission prompt's goal block so the agent targets the user's goal; figures stay code-computed.
    goal_status: dict[str, Any] | None = None

    @property
    def required_scopes(self) -> list[str]:
        # Order-preserving dedup across all grants' scopes.
        return list(dict.fromkeys(scope for grant in self.tool_grants for scope in grant.scopes))


def _posthog_mcp_grant() -> McpToolGrant:
    return McpToolGrant(
        name="posthog",
        url=f"{settings.SITE_URL.rstrip('/')}/mcp",
        scopes=list(POSTHOG_MCP_SCOPES),
    )


def build_general_brief_mission(
    *,
    team: Team,
    brief: ProductBrief,
    config: BriefConfig | None,
    items: list[SourceItem],
    goal_status: GoalStatus | None = None,
) -> MissionBundle:
    window_end = timezone.now()
    _, max_opportunities = gate_thresholds(config)
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
        max_opportunities=max_opportunities,
        goal_status=dataclasses.asdict(goal_status) if goal_status is not None else None,
    )
