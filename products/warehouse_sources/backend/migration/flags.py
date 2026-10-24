from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false

WAREHOUSE_MIGRATION_IMPORT_FLAG = "warehouse-migration-import"


def is_migration_import_enabled(team: Team) -> bool:
    organization_id = str(team.organization_id)
    return feature_enabled_or_false(
        WAREHOUSE_MIGRATION_IMPORT_FLAG,
        organization_id,
        groups={"organization": organization_id},
        group_properties={"organization": {"id": organization_id}},
    )
