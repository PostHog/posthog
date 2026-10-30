import datetime as dt
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from django.db.models import Max, Sum

from posthog.clickhouse.query_tagging import Product
from posthog.dataclasses import frozen
from posthog.temporal.health_checks.rollups.framework import DailyRollup
from posthog.temporal.health_checks.rollups.freshness import RollupWindow, rollup_window, window_rows
from posthog.utils import ensure_utc

from products.growth.backend.constants import SDK_TYPES, SdkVersionEntry
from products.growth.backend.models import SdkVersionsDaily
from products.growth.backend.sdk_health import sort_sdk_version_entries

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


SDK_VERSIONS_WINDOW_DAYS = 7

TeamSdkVersions = dict[str, list[SdkVersionEntry]]


@frozen
class _SdkVersion:
    lib: str
    lib_version: str


@frozen
class _VersionUsage:
    count: int
    max_timestamp: dt.datetime


def sdk_versions_window() -> RollupWindow | None:
    return rollup_window(SdkVersionsDaily, SDK_VERSIONS_WINDOW_DAYS)


def _read_usage(team_ids: list[int], window: RollupWindow) -> dict[int, dict[_SdkVersion, _VersionUsage]]:
    rows = (
        window_rows(SdkVersionsDaily, team_ids, window)
        .values("team_id", "lib", "lib_version")
        .annotate(count=Sum("event_count"), max_timestamp=Max("max_timestamp"))
    )
    usage: defaultdict[int, dict[_SdkVersion, _VersionUsage]] = defaultdict(dict)
    for row in rows:
        usage[row["team_id"]][_SdkVersion(lib=row["lib"], lib_version=row["lib_version"])] = _VersionUsage(
            count=row["count"], max_timestamp=ensure_utc(row["max_timestamp"]).astimezone(dt.UTC)
        )
    return dict(usage)


def _to_entries(usage: dict[_SdkVersion, _VersionUsage]) -> TeamSdkVersions:
    entries: defaultdict[str, list[SdkVersionEntry]] = defaultdict(list)
    for version, version_usage in usage.items():
        if version.lib not in SDK_TYPES:
            continue
        entries[version.lib].append(
            {
                "lib_version": version.lib_version,
                "max_timestamp": str(version_usage.max_timestamp),
                "count": version_usage.count,
            }
        )
    return {lib: sort_sdk_version_entries(lib_entries) for lib, lib_entries in entries.items()}


def sdk_versions_from_rollup(team_ids: list[int], window: RollupWindow) -> dict[int, TeamSdkVersions]:
    """SDK versions per team over the window, in the shape SDK Health reads. Teams with no traffic are absent."""
    return {team_id: _to_entries(usage) for team_id, usage in _read_usage(team_ids, window).items()}


def merge_live_usage(
    team_id: int, window: RollupWindow | None, live_rows: list[tuple[str, str, dt.datetime, int]]
) -> TeamSdkVersions:
    """Combine the team's rollup window, if any, with live `(lib, lib_version, max_timestamp, count)` rows."""
    usage = _read_usage([team_id], window).get(team_id, {}) if window else {}
    for lib, lib_version, live_max_timestamp, count in live_rows:
        max_timestamp = ensure_utc(live_max_timestamp).astimezone(dt.UTC)
        key = _SdkVersion(lib=lib, lib_version=lib_version or "")
        previous = usage.get(key, _VersionUsage(count=0, max_timestamp=max_timestamp))
        usage[key] = _VersionUsage(
            count=previous.count + count, max_timestamp=max(previous.max_timestamp, max_timestamp)
        )
    return _to_entries(usage)
