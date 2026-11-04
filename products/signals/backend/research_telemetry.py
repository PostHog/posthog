from __future__ import annotations

from typing import Literal

from posthog.event_usage import groups
from posthog.models import Team
from posthog.ph_client import ph_background_capture


def capture_research_access_event(
    *,
    team_id: int,
    origin: Literal["pipeline", "scout"],
    reason: str,
    fallback: bool,
    report_id: str | None = None,
    scout_config_id: str | None = None,
) -> None:
    team = Team.objects.select_related("organization").get(id=team_id)
    ph_background_capture()(
        distinct_id=str(team.uuid),
        event="signal_research_fallback" if fallback else "signal_research_blocked",
        groups=groups(team.organization, team),
        properties={
            "team_id": team_id,
            "report_id": report_id,
            "scout_config_id": scout_config_id,
            "origin": origin,
            "reason": reason,
            "research_mode": "data_only" if fallback else "blocked",
        },
    )
