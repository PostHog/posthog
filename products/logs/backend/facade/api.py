"""Facade API for logs.

This is the only module other apps may import for logs configuration data.

Responsibilities:
- Call internal models/logic
- Convert Django models to contracts before returning
- Remain thin and stable

Do NOT:
- Implement business logic here
- Import DRF, serializers, or HTTP concerns
- Return ORM instances or QuerySets

Kept deliberately light: query-runner, celery, and temporal surfaces live in
sibling facade modules (``queries``, ``tasks``, ``temporal``) so importing this
module doesn't pull HogQL or temporalio onto the caller's import path.
"""

from typing import TYPE_CHECKING

from posthog.models.team.extensions import get_or_create_team_extension

from products.logs.backend.facade.contracts import TeamLogsConfigData
from products.logs.backend.models import TeamLogsConfig

if TYPE_CHECKING:
    from posthog.models.team import Team


def _to_team_logs_config_data(config: TeamLogsConfig) -> TeamLogsConfigData:
    return TeamLogsConfigData(
        team_id=config.team_id,
        logs_distinct_id_attribute_key=config.logs_distinct_id_attribute_key,
    )


def get_or_create_team_logs_config(team: "Team") -> TeamLogsConfigData:
    config = get_or_create_team_extension(team, TeamLogsConfig)
    return _to_team_logs_config_data(config)


def update_team_logs_config(team: "Team", *, logs_distinct_id_attribute_key: str) -> TeamLogsConfigData:
    config = get_or_create_team_extension(team, TeamLogsConfig)
    config.logs_distinct_id_attribute_key = logs_distinct_id_attribute_key
    config.save(update_fields=["logs_distinct_id_attribute_key"])
    return _to_team_logs_config_data(config)
