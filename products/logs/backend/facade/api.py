"""Facade API for logs.

The data-capability surface other apps import from. Accepts and returns contracts,
never ORM instances or querysets.

Keep heavy imports (HogQL, temporalio) out of this module — those live in
``facade/queries.py`` and ``facade/temporal.py`` so config-only consumers don't drag
them onto the ``django.setup()`` import path.
"""

from typing import TYPE_CHECKING

from posthog.models.team.extensions import get_or_create_team_extension

from products.logs.backend.facade import contracts
from products.logs.backend.models import TeamLogsConfig

if TYPE_CHECKING:
    from posthog.models import Team


def _to_team_logs_config(config: TeamLogsConfig) -> contracts.TeamLogsConfig:
    return contracts.TeamLogsConfig(logs_distinct_id_attribute_key=config.logs_distinct_id_attribute_key)


def get_team_logs_config(team: "Team") -> contracts.TeamLogsConfig:
    """Read a team's logs config, creating it with defaults if it doesn't exist yet."""
    config = get_or_create_team_extension(team, TeamLogsConfig)
    return _to_team_logs_config(config)


def update_team_logs_config(team: "Team", logs_distinct_id_attribute_key: str) -> contracts.TeamLogsConfig:
    """Set the distinct-id attribute key for a team's logs config."""
    config = get_or_create_team_extension(team, TeamLogsConfig)
    config.logs_distinct_id_attribute_key = logs_distinct_id_attribute_key
    config.save(update_fields=["logs_distinct_id_attribute_key"])
    return _to_team_logs_config(config)
