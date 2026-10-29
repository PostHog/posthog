import datetime as dt
from collections import defaultdict

from django.db.models import Max, Sum

from posthog.dataclasses import frozen
from posthog.temporal.health_checks.rollups.freshness import RollupWindow, rollup_window, window_rows
from posthog.utils import ensure_utc

from products.growth.backend.constants import SDK_TYPES, SdkVersionEntry
from products.growth.backend.models import SdkVersionsDaily
from products.growth.backend.sdk_health import sort_sdk_version_entries

SDK_VERSIONS_WINDOW_DAYS = 7

TeamSdkVersions = dict[str, list[SdkVersionEntry]]


@frozen
class _VersionUsage:
    count: int
    max_timestamp: dt.datetime


def sdk_versions_window() -> RollupWindow | None:
    return rollup_window(SdkVersionsDaily, SDK_VERSIONS_WINDOW_DAYS)


def _read_usage(team_ids: list[int], window: RollupWindow) -> dict[int, dict[tuple[str, str], _VersionUsage]]:
    rows = (
        window_rows(SdkVersionsDaily, team_ids, window)
        .values("team_id", "lib", "lib_version")
        .annotate(count=Sum("event_count"), max_timestamp=Max("max_timestamp"))
    )
    usage: defaultdict[int, dict[tuple[str, str], _VersionUsage]] = defaultdict(dict)
    for row in rows:
        usage[row["team_id"]][(row["lib"], row["lib_version"])] = _VersionUsage(
            count=row["count"], max_timestamp=ensure_utc(row["max_timestamp"]).astimezone(dt.UTC)
        )
    return dict(usage)


def _to_entries(usage: dict[tuple[str, str], _VersionUsage]) -> TeamSdkVersions:
    entries: defaultdict[str, list[SdkVersionEntry]] = defaultdict(list)
    for (lib, lib_version), version_usage in usage.items():
        if lib not in SDK_TYPES:
            continue
        entries[lib].append(
            {
                "lib_version": lib_version,
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
        key = (lib, lib_version or "")
        previous = usage.get(key, _VersionUsage(count=0, max_timestamp=max_timestamp))
        usage[key] = _VersionUsage(
            count=previous.count + count, max_timestamp=max(previous.max_timestamp, max_timestamp)
        )
    return _to_entries(usage)
