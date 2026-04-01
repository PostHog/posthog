import json
from collections import defaultdict
from typing import Any

import structlog

from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.redis import get_client
from posthog.temporal.health_checks.detectors import DEFAULT_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import HealthCheck
from posthog.temporal.health_checks.models import HealthCheckResult

from products.growth.backend.constants import github_sdk_versions_key, team_sdk_versions_key
from products.growth.dags.github_sdk_versions import SDK_TYPES

logger = structlog.get_logger(__name__)


def _decode_redis_json(raw: bytes | str) -> Any:
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


class SdkOutdatedCheck(HealthCheck):
    name = "sdk_outdated"
    kind = "sdk_outdated"
    owner = JobOwners.TEAM_GROWTH
    policy = DEFAULT_EXECUTION_POLICY

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        github_data = _load_github_sdk_data()
        if not github_data:
            logger.warning("GitHub SDK version data unavailable in Redis; skipping sdk_outdated check")
            return {}

        redis_client = get_client()
        keys = [team_sdk_versions_key(tid) for tid in team_ids]
        values = redis_client.mget(keys)

        issues: defaultdict[int, list[HealthCheckResult]] = defaultdict(list)
        for team_id, raw in zip(team_ids, values):
            if not raw:
                continue
            team_data = _decode_redis_json(raw)
            if not team_data:
                continue

            for lib_name, entries in team_data.items():
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
