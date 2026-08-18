from typing import TYPE_CHECKING

import structlog

from posthog.permissions import posthog_feature_flag_enabled

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)

DATA_WAREHOUSE_SCENE_FLAG = "data-warehouse-scene"
MANAGED_WAREHOUSE_SQL_EDITOR_FLAG = "managed-warehouse-sql-editor"
MANAGED_WAREHOUSE_QUERY_STATUS_LABEL_PREFIX = f"{MANAGED_WAREHOUSE_SQL_EDITOR_FLAG}:"


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
