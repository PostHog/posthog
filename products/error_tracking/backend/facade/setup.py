from typing import Literal

import structlog
from pydantic.dataclasses import dataclass

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.models import RemoteConfig, Team

from products.error_tracking.backend import logic

from .contracts import ErrorTrackingObservedSDK, ErrorTrackingSetupStatus, ErrorTrackingSetupWarning

logger = structlog.get_logger(__name__)

_RECENT_PERIOD_DAYS = 7
_SDK_CONFIGURATIONS: tuple[tuple[str, Literal["project_setting", "local", "unknown"], str | None], ...] = (
    ("web", "project_setting", None),
    ("posthog-node", "local", "enableExceptionAutocapture"),
    ("posthog-python", "unknown", None),
    ("posthog-react-native", "unknown", None),
    ("posthog-ruby", "unknown", None),
    ("posthog-ios", "unknown", None),
    ("posthog-rs", "unknown", None),
    ("posthog-android", "unknown", None),
    ("posthog-go", "unknown", None),
    ("posthog-php", "unknown", None),
    ("posthog-flutter", "unknown", None),
    ("posthog-java", "unknown", None),
)
_RECENT_USAGE_QUERY = parse_select("""
    SELECT
        count() AS event_count,
        countIf(event = '$exception') AS exception_count,
        countIf(properties.$lib = 'web') AS web_events,
        countIf(properties.$lib = 'posthog-node') AS node_events,
        countIf(properties.$lib = 'posthog-python') AS python_events,
        countIf(properties.$lib = 'posthog-react-native') AS react_native_events,
        countIf(properties.$lib = 'posthog-ruby') AS ruby_events,
        countIf(properties.$lib = 'posthog-ios') AS ios_events,
        countIf(properties.$lib = 'posthog-rs') AS rust_events,
        countIf(properties.$lib = 'posthog-android') AS android_events,
        countIf(properties.$lib = 'posthog-go') AS go_events,
        countIf(properties.$lib = 'posthog-php') AS php_events,
        countIf(properties.$lib = 'posthog-flutter') AS flutter_events,
        countIf(properties.$lib = 'posthog-java') AS java_events
    FROM events
    WHERE timestamp >= now() - INTERVAL 7 DAY
""")


@dataclass(frozen=True)
class _RecentErrorTrackingUsage:
    event_count: int
    exception_count: int
    observed_sdks: list[ErrorTrackingObservedSDK]


def _get_remote_config_autocapture(team_id: int) -> bool | None:
    config = RemoteConfig.objects.filter(team_id=team_id).values_list("config", flat=True).first()
    if not isinstance(config, dict):
        return None
    value = config.get("autocaptureExceptions")
    return value if isinstance(value, bool) else None


def _get_recent_usage(team: Team) -> _RecentErrorTrackingUsage:
    with tags_context(
        product=Product.ERROR_TRACKING,
        feature=Feature.QUERY,
        team_id=team.id,
        org_id=team.organization_id,
        query_type="error_tracking_setup_status",
    ):
        response = execute_hogql_query(_RECENT_USAGE_QUERY, team, query_type="error_tracking_setup_status")

    row = response.results[0] if response.results else [0] * (len(_SDK_CONFIGURATIONS) + 2)
    observed_sdks = [
        ErrorTrackingObservedSDK(
            library=library,
            event_count=int(row[index]),
            autocapture_configuration=configuration,
            local_option=local_option,
        )
        for index, (library, configuration, local_option) in enumerate(_SDK_CONFIGURATIONS, start=2)
        if int(row[index]) > 0
    ]
    return _RecentErrorTrackingUsage(
        event_count=int(row[0]),
        exception_count=int(row[1]),
        observed_sdks=observed_sdks,
    )


def get_error_tracking_setup_status(team: Team) -> ErrorTrackingSetupStatus:
    try:
        recent_usage = _get_recent_usage(team)
    except Exception as error:
        logger.exception("Failed to query recent error tracking setup data", team_id=team.id)
        capture_exception(error, {"team_id": team.id})
        recent_usage = None

    warnings: list[ErrorTrackingSetupWarning] = []
    if (
        recent_usage
        and recent_usage.exception_count == 0
        and any(sdk.library == "posthog-node" for sdk in recent_usage.observed_sdks)
    ):
        warnings.append(
            ErrorTrackingSetupWarning(
                code="node_autocapture_requires_local_configuration",
                message=(
                    "posthog-node requires `enableExceptionAutocapture: true` in the SDK initialization. "
                    "The project setting does not enable exception autocapture for posthog-node. "
                    "PostHog cannot verify this local SDK option from event data."
                ),
            )
        )

    return ErrorTrackingSetupStatus(
        project_autocapture_enabled=bool(team.autocapture_exceptions_opt_in),
        remote_config_autocapture_enabled=_get_remote_config_autocapture(team.id),
        has_issues=logic.issue_exists(team.id),
        recent_data_available=recent_usage is not None,
        recent_period_days=_RECENT_PERIOD_DAYS,
        recent_event_count=recent_usage.event_count if recent_usage else None,
        recent_exception_count=recent_usage.exception_count if recent_usage else None,
        observed_sdks=recent_usage.observed_sdks if recent_usage else [],
        warnings=warnings,
    )
