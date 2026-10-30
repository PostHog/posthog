from collections.abc import Mapping
from typing import Any

from posthog.clickhouse.query_tagging import Product
from posthog.temporal.health_checks.rollups.framework import DailyRollup

from products.growth.backend.constants import SDK_TYPES
from products.growth.backend.models import SdkVersionsDaily

MAX_VERSIONS_PER_TEAM_LIB_DAY = 100

SDK_VERSIONS_FILL_SQL = """
SELECT
    team_id,
    `mat_$lib` AS lib,
    `mat_$lib_version` AS lib_version,
    count() AS event_count,
    max(timestamp) AS max_timestamp
FROM events
WHERE team_id >= %(team_id_start)s
  AND team_id < %(team_id_end)s
  AND timestamp >= %(day_start)s
  AND timestamp < %(day_end)s
  AND `mat_$lib` IN %(sdk_types)s
  AND (`mat_$lib` = 'posthog-java' OR `mat_$lib_version` != '')
  AND length(`mat_$lib_version`) <= %(max_version_length)s
  AND position(`mat_$lib_version`, char(0)) = 0
GROUP BY team_id, lib, lib_version
ORDER BY team_id, lib, event_count DESC
LIMIT %(max_versions)s BY team_id, lib
"""


class SdkVersionsDailyRollup(DailyRollup):
    model = SdkVersionsDaily
    product = Product.SDK_HEALTH
    columns = ("team_id", "day", "lib", "lib_version", "event_count", "max_timestamp")
    retention_days = 10

    @classmethod
    def fill_sql(cls) -> str:
        return SDK_VERSIONS_FILL_SQL

    @classmethod
    def fill_params(cls) -> Mapping[str, Any]:
        return {
            "sdk_types": list(SDK_TYPES),
            "max_version_length": SdkVersionsDaily._meta.get_field("lib_version").max_length,
            "max_versions": MAX_VERSIONS_PER_TEAM_LIB_DAY,
        }
