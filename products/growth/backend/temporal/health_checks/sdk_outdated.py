import json
from collections import defaultdict
from typing import Any

import structlog

from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.redis import get_client
from posthog.temporal.health_checks.detectors import HealthExecutionPolicy
from posthog.temporal.health_checks.framework import (
    _SEVERITY_WEIGHT,
    AlertContent,
    HealthCheck,
    Remediation,
    SignalContent,
    build_signal_extra,
)
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

from products.growth.backend.constants import (
    SDK_TYPES,
    TEAM_SDK_CACHE_EXPIRY,
    SdkVersionEntry,
    github_sdk_versions_key,
    team_sdk_versions_key,
)
from products.growth.backend.sdk_health import SdkAssessment, _is_safe_for_interpolation, compute_sdk_health

# Issue severity follows the SDK Health assessment severity: a single outdated SDK is a warning,
# but when the bulk of a team's SDKs are outdated the assessment escalates to "danger".
_SEVERITY_BY_ASSESSMENT: dict[str, HealthIssue.Severity] = {
    "danger": HealthIssue.Severity.CRITICAL,
    "warning": HealthIssue.Severity.WARNING,
}

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
    """Cache team SDK version data in Redis for the SDK Health API."""
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
    remediation = Remediation(
        human="""
            Open the SDK Health page (the Health section of the app). It lists every SDK you're sending
            events from, the versions in use, the latest available version, and how far behind each one is.
            Follow each outdated SDK's upgrade guide — usually bumping the dependency in your package
            manager (npm/yarn/pnpm, pip/poetry, gem, go get, etc.) and redeploying. For browser-snippet
            installs, make sure you're loading the latest snippet.
        """,
        agent="""
            Read this issue with `health-issues-get` to get the affected SDK and the latest version from
            the payload, and use `execute-sql` to see which `properties.$lib` / `properties.$lib_version`
            values still send events (`SELECT properties.$lib, properties.$lib_version, count() FROM events
            WHERE timestamp > now() - INTERVAL 7 DAY GROUP BY 1, 2 ORDER BY 3 DESC`). Then fix it in the
            user's codebase: bump the PostHog SDK dependency to the latest version in the relevant manifest
            (package.json, requirements.txt / pyproject.toml, Gemfile, go.mod, etc.), update the lockfile,
            and check the SDK's changelog (via `docs-search`) for breaking changes to adjust. The issue
            clears on the next check run once upgraded traffic arrives.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        sdk_name = issue.payload.get("sdk_name", "an SDK")
        # `reason` is the assessment's single source of truth (compute_sdk_health → _build_reason).
        # It already names the current in-use version and the specific older versions driving the
        # alert, and routes every version through SDK Health's allowlist before interpolation — so
        # it's both complete and safe to forward to alert destinations (Slack, email, webhooks).
        summary = issue.payload.get("reason")
        if not summary:
            # Fallback for issues persisted before `reason` was added to the payload. `current_version`
            # originates from the $lib_version event property — attacker controllable via project token —
            # so gate it through the same allowlist before interpolating.
            #
            # Can be removed after 2026-06-08.
            latest = issue.payload.get("latest_version") or "the latest version"
            raw_current = issue.payload.get("current_version")
            current = raw_current if raw_current and _is_safe_for_interpolation(raw_current) else None
            summary = f"{sdk_name} is on {current}, latest is {latest}" if current else f"{sdk_name} is behind {latest}"
        return AlertContent(
            title=f"{sdk_name} SDK is outdated",
            summary=summary,
            link="/health/sdk-health",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        sdk_name = issue.payload.get("sdk_name", "An SDK")
        # `reason` is the assessment's allowlist-safe source of truth (see render_alert) — safe to
        # forward verbatim. It names the in-use and target versions driving the issue.
        reason = issue.payload.get("reason") or f"{sdk_name} is behind the latest release."
        title = f"{sdk_name} SDK is outdated"
        return SignalContent(
            description=(
                f"The {sdk_name} SDK is outdated for this project. {reason} "
                "Outdated SDKs miss bug fixes, performance improvements, and new features, and may "
                "carry known issues. Recommend upgrading to the latest version."
            ),
            weight=_SEVERITY_WEIGHT[issue.severity],
            extra=build_signal_extra(issue, title=title, summary=reason, link="/health/sdk-health"),
        )

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

        issues: defaultdict[int, list[HealthCheckResult]] = defaultdict(list)
        for team_id, sdk_data in team_sdk_data.items():
            combined = _build_combined_data(sdk_data, github_data)
            if not combined:
                continue
            report = compute_sdk_health(combined, project_id=team_id)
            for assessment in report.sdks:
                if assessment.needs_updating:
                    issues[team_id].append(_build_health_result(assessment))

        return issues


def _build_combined_data(
    sdk_data: dict[str, list[SdkVersionEntry]],
    github_data: dict[str, dict],
) -> dict[str, dict[str, Any]]:
    """Shape per-team SDK usage into the structure compute_sdk_health expects."""
    combined: dict[str, dict[str, Any]] = {}
    for lib_name, entries in sdk_data.items():
        if lib_name not in github_data or not entries:
            continue
        sdk_github_data = github_data[lib_name]
        latest_version = sdk_github_data["latestVersion"]
        release_dates = sdk_github_data.get("releaseDates", {})
        combined[lib_name] = {
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
        }
    return combined


def _build_health_result(assessment: SdkAssessment) -> HealthCheckResult:
    """Build a HealthCheckResult from a computed SDK assessment.

    The payload carries everything both the alert (render_alert) and the unified Health scene's
    per-version table (SdkOutdatedRenderer) need, so neither has to recompute or re-query.
    """
    severity = _SEVERITY_BY_ASSESSMENT.get(assessment.severity, HealthIssue.Severity.WARNING)
    primary = assessment.releases[0] if assessment.releases else None
    return HealthCheckResult(
        severity=severity,
        payload={
            "sdk_name": assessment.lib,
            "latest_version": assessment.latest_version,
            "current_version": primary.version if primary else None,
            "reason": assessment.reason,
            "banners": assessment.banners,
            "is_outdated": assessment.is_outdated,
            "is_old": assessment.is_old,
            "usage": [
                {
                    "lib_version": release.version,
                    "count": release.count,
                    "max_timestamp": release.max_timestamp,
                    "release_date": release.release_date,
                    "is_latest": release.version == assessment.latest_version,
                    "is_outdated": release.is_outdated,
                    "status_reason": release.status_reason,
                }
                for release in assessment.releases
            ],
        },
        hash_keys=["sdk_name"],
    )
