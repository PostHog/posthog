from datetime import timedelta
from typing import Any

from posthog.clickhouse.client import sync_execute
from posthog.models.team.team import Team

RECOMMENDATION_TYPE = "cross_sell"
REFRESH_INTERVAL = timedelta(hours=1)


def _team_has_logs(team_id: int) -> bool:
    result = sync_execute(
        "SELECT 1 FROM logs_distributed WHERE team_id = %(team_id)s LIMIT 1",
        {"team_id": team_id},
    )
    return len(result) > 0


def compute(team: Team) -> dict[str, Any]:
    products: list[dict[str, Any]] = [
        {
            "key": "session_replay",
            "enabled": bool(team.session_recording_opt_in),
        },
        {
            "key": "logs",
            "enabled": _team_has_logs(team.id),
        },
    ]

    return {"products": products}
