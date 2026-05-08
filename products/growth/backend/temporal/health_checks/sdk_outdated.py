import json
from collections import defaultdict
from typing import Any

import structlog

from posthog.dags.common.owners import JobOwners
from posthog.exceptions_capture import capture_exception
from posthog.models.health_issue import HealthIssue
from posthog.redis import get_client
from posthog.temporal.health_checks.detectors import HealthExecutionPolicy
from posthog.temporal.health_checks.framework import HealthCheck
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

from products.growth.backend.constants import (
    SDK_TYPES,
    TEAM_SDK_CACHE_EXPIRY,
    SdkVersionEntry,
    github_sdk_versions_key,
    team_sdk_versions_key,
)
from products.growth.backend.sdk_doctor_alerts import emit_sdk_doctor_alert_event
from products.growth.backend.sdk_health import compute_sdk_health

logger = structlog.get_logger(__name__)

SDK_VERSIONS_SQL = """
SELECT
    team_id,
    `mat_$lib` AS lib,
    `mat_$lib_version` AS lib_version,
    max(timestamp) AS max_timestamp,
    count(*) AS event_count
FROM events
WHERE
    team_id IN %(team_ids)s
    AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
    AND `mat_$lib` IS NOT NULL
    AND `mat_$lib` != ''
    AND `mat_$lib_version` IS NOT NULL
    AND `mat_$lib_version` != ''
GROUP BY team_id, lib, lib_version
ORDER BY
    team_id,
    lib,
    arrayMap(x -> toInt64OrZero(x), splitByChar('.', extract(assumeNotNull(lib_version), '(\\d+(\\.\\d+)+)'))) DESC,
    event_count DESC
"""


def _decode_redis_json(raw: bytes | str) -> dict:
    return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)


def _load_github_sdk_data() -> dict[str, dict]:
    """Load latest SDK versions from Redis for all known SDK types."""
    redis_client = get_client()
    keys = [github_sdk_versions_key(sdk_type) for sdk_type in SDK_TYPES]
    values = redis_client.mget(keys)

    data: dict[str, dict] = {}
    for sdk_type, raw in zip(SDK_TYPES, values):
        if not raw:
            continue
        parsed = _decode_redis_json(raw)
        if "latestVersion" in parsed:
            data[sdk_type] = parsed
    return data


def _cache_team_sdk_data(team_sdk_data: dict[int, dict[str, list[SdkVersionEntry]]]) -> None:
    """Cache team SDK version data in Redis for the SDK Doctor API."""
    if not team_sdk_data:
        return

    redis_client = get_client()
    pipe = redis_client.pipeline()
    for team_id, sdk_data in team_sdk_data.items():
        cache_key = team_sdk_versions_key(team_id)
        pipe.setex(cache_key, TEAM_SDK_CACHE_EXPIRY, json.dumps(sdk_data))
    pipe.execute()


class SdkOutdatedCheck(HealthCheck):
    name = "sdk_outdated"
    kind = "sdk_outdated"
    owner = JobOwners.TEAM_GROWTH
    policy = HealthExecutionPolicy(batch_size=10, max_concurrent=3)
    schedule = "0 8 * * *"
    active_since_days = 30

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        github_data = _load_github_sdk_data()
        if not github_data:
            logger.warning("GitHub SDK version data unavailable in Redis; skipping sdk_outdated check")
            return {}

        rows = execute_clickhouse_health_team_query(
            SDK_VERSIONS_SQL,
            team_ids=team_ids,
            lookback_days=7,
        )

        team_sdk_data: defaultdict[int, defaultdict[str, list[SdkVersionEntry]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for team_id, lib, lib_version, max_timestamp, event_count in rows:
            if lib in SDK_TYPES:
                team_sdk_data[team_id][lib].append(
                    {
                        "lib_version": lib_version,
                        "max_timestamp": str(max_timestamp),
                        "count": event_count,
                    }
                )

        _cache_team_sdk_data({tid: dict(sdk_data) for tid, sdk_data in team_sdk_data.items()})

        self._emit_alerts_for_outdated_teams(team_sdk_data, github_data)

        issues: defaultdict[int, list[HealthCheckResult]] = defaultdict(list)
        for team_id, sdk_data in team_sdk_data.items():
            for lib_name, entries in sdk_data.items():
                if lib_name not in github_data or not entries:
                    continue
                sdk_github_data = github_data[lib_name]
                latest_version = sdk_github_data["latestVersion"]
                release_dates = sdk_github_data.get("releaseDates", {})

                current_version = entries[0].get("lib_version")

                if current_version and current_version != latest_version:
                    issues[team_id].append(
                        HealthCheckResult(
                            severity=HealthIssue.Severity.WARNING,
                            payload={
                                "sdk_name": lib_name,
                                "latest_version": latest_version,
                                "usage": [
                                    {
                                        "lib_version": entry["lib_version"],
                                        "count": entry.get("count", 0),
                                        "max_timestamp": entry["max_timestamp"],
                                        "release_date": release_dates.get(entry["lib_version"]),
                                        "is_latest": entry["lib_version"] == latest_version,
                                    }
                                    for entry in entries
                                ],
                            },
                            hash_keys=["sdk_name"],
                        )
                    )

        return issues

    def _emit_alerts_for_outdated_teams(
        self,
        team_sdk_data: dict[int, dict[str, list[SdkVersionEntry]]] | defaultdict,
        github_data: dict[str, dict],
    ) -> None:
        """
        For each team whose SDKs trip the smart-semver `needs_attention` rule, emit
        `$sdk_doctor_alert_firing` so subscribed HogFunctions (Slack/Discord/email/etc.)
        can notify the user. A per-team Redis cooldown inside
        `emit_sdk_doctor_alert_event` keeps this from spamming daily.

        Alert emission is best-effort: a failure on one team must not break the health
        check for the rest of the batch.
        """
        for team_id, sdk_data in team_sdk_data.items():
            try:
                combined = self._build_combined_health_data(sdk_data, github_data)
                if not combined:
                    continue
                report = compute_sdk_health(combined)
                emit_sdk_doctor_alert_event(team_id=team_id, report=report)
            except Exception as e:
                logger.exception("Failed to emit SDK Doctor alert event", team_id=team_id, error=str(e))
                capture_exception(e, additional_properties={"team_id": team_id})

    @staticmethod
    def _build_combined_health_data(
        sdk_data: dict[str, list[SdkVersionEntry]],
        github_data: dict[str, dict],
    ) -> dict[str, dict[str, Any]]:
        """
        Reshape per-team SDK usage + GitHub version data into the structure
        `compute_sdk_health` expects — mirrors the combine step in the
        `/api/projects/:team_id/sdk_doctor/report` endpoint.
        """
        combined: dict[str, dict[str, Any]] = {}
        for lib, entries in sdk_data.items():
            if lib not in github_data or not entries:
                continue
            sdk_for_lib = github_data[lib]
            latest_version = sdk_for_lib["latestVersion"]
            release_dates = sdk_for_lib.get("releaseDates", {})
            combined[lib] = {
                "latest_version": latest_version,
                "usage": [
                    {
                        **entry,
                        "is_latest": entry["lib_version"] == latest_version,
                        "release_date": release_dates.get(entry["lib_version"]),
                    }
                    for entry in entries
                ],
            }
        return combined
