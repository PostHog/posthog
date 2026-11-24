from posthog.models import Team
from posthog.permissions import posthog_feature_flag_enabled

WAREHOUSE_MIGRATION_IMPORT_FLAG = "warehouse-migration-import"


def is_migration_import_enabled(team: Team, distinct_id: str | None) -> bool:
    """Evaluated like the frontend and MCP gates: the user, with the organization and project groups."""
    if not distinct_id:
        return False
    return posthog_feature_flag_enabled(
        WAREHOUSE_MIGRATION_IMPORT_FLAG, distinct_id, organization_id=team.organization_id, team_id=team.id
    )
