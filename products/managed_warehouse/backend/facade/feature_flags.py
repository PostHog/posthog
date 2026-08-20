from typing import TYPE_CHECKING

import structlog

from posthog.permissions import posthog_feature_flag_enabled

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)

DATA_WAREHOUSE_SCENE_FLAG = "data-warehouse-scene"
MANAGED_WAREHOUSE_SQL_EDITOR_FLAG = "managed-warehouse-sql-editor"
MANAGED_WAREHOUSE_QUERY_STATUS_LABEL_PREFIX = f"{MANAGED_WAREHOUSE_SQL_EDITOR_FLAG}:"
DUCKLAKE_DATA_IMPORTS_COPY_FLAG = "ducklake-data-imports-copy-workflow"


def is_managed_warehouse_sql_editor_enabled(team: "Team") -> bool:
    try:
        return posthog_feature_flag_enabled(
            MANAGED_WAREHOUSE_SQL_EDITOR_FLAG,
            str(team.uuid),
            organization_id=team.organization_id,
            team_id=team.id,
        )
    except Exception:
        logger.exception("managed_warehouse_sql_editor_feature_flag_check_failed", team_id=team.id)
        return False


def is_ducklake_data_imports_copy_enabled(team: "Team") -> bool:
    """Whether warehouse syncs for this team feed the DuckLake copy.

    Mirrors `ducklake_copy_data_imports_gate_activity`. Callers use it to leave the sync path
    alone for these teams: that copy has no retry other than the next sync.
    """
    try:
        return posthog_feature_flag_enabled(
            DUCKLAKE_DATA_IMPORTS_COPY_FLAG,
            str(team.uuid),
            organization_id=team.organization_id,
            team_id=team.id,
        )
    except Exception:
        logger.exception("ducklake_data_imports_copy_feature_flag_check_failed", team_id=team.id)
        return True
