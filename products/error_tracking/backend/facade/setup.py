from datetime import datetime
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


@dataclass(frozen=True)
class _SDKTransportConfiguration:
    library: str
    autocapture_configuration: Literal["project_setting", "local", "unknown"]
    local_option: str | None


_SDK_CONFIGURATIONS = (
    _SDKTransportConfiguration(library="web", autocapture_configuration="project_setting", local_option=None),
    _SDKTransportConfiguration(
        library="posthog-node", autocapture_configuration="local", local_option="enableExceptionAutocapture"
    ),
    _SDKTransportConfiguration(library="posthog-python", autocapture_configuration="unknown", local_option=None),
    _SDKTransportConfiguration(library="posthog-react-native", autocapture_configuration="unknown", local_option=None),
    _SDKTransportConfiguration(library="posthog-ruby", autocapture_configuration="unknown", local_option=None),
    _SDKTransportConfiguration(library="posthog-ios", autocapture_configuration="unknown", local_option=None),
    _SDKTransportConfiguration(library="posthog-rs", autocapture_configuration="unknown", local_option=None),
    _SDKTransportConfiguration(library="posthog-android", autocapture_configuration="unknown", local_option=None),
    _SDKTransportConfiguration(library="posthog-go", autocapture_configuration="unknown", local_option=None),
    _SDKTransportConfiguration(library="posthog-php", autocapture_configuration="unknown", local_option=None),
    _SDKTransportConfiguration(library="posthog-flutter", autocapture_configuration="unknown", local_option=None),
    _SDKTransportConfiguration(library="posthog-java", autocapture_configuration="unknown", local_option=None),
)
_SDK_CONFIGURATIONS_BY_LIBRARY = {sdk.library: sdk for sdk in _SDK_CONFIGURATIONS}
_SUPPORTED_SDK_LIBRARIES = ", ".join(f"'{sdk.library}'" for sdk in _SDK_CONFIGURATIONS)
_RECENT_USAGE_QUERY = parse_select("""
    SELECT
        count() AS event_count,
        countIf(event = '$exception') AS exception_count,
        if(count() > 0, max(timestamp), NULL) AS last_event_at,
        if(countIf(event = '$exception') > 0, maxIf(timestamp, event = '$exception'), NULL) AS last_exception_at
    FROM events
    WHERE timestamp >= now() - INTERVAL 7 DAY
""")
_RECENT_SDK_USAGE_QUERY = parse_select(f"""
    SELECT
        properties.$lib AS library,
        count() AS event_count,
        argMax(properties.$lib_version, timestamp) AS latest_version,
        max(timestamp) AS last_seen_at
    FROM events
    WHERE timestamp >= now() - INTERVAL 7 DAY
      AND properties.$lib IN ({_SUPPORTED_SDK_LIBRARIES})
    GROUP BY library
    ORDER BY library ASC
    LIMIT {len(_SDK_CONFIGURATIONS)}
""")


@dataclass(frozen=True)
class _RecentErrorTrackingUsage:
    event_count: int
    exception_count: int
    last_event_at: datetime | None
    last_exception_at: datetime | None
    observed_sdks: list[ErrorTrackingObservedSDK]


def _get_remote_config_autocapture(team_id: int) -> bool | None:
    config = RemoteConfig.objects.filter(team_id=team_id).values_list("config", flat=True).first()
    if not isinstance(config, dict):
        return None
    value = config.get("autocaptureExceptions")
    return value if isinstance(value, bool) else None


def _as_int(value: object) -> int:
    if not isinstance(value, int):
        raise ValueError("Expected an integer in error tracking setup query results")
    return value


def _as_optional_datetime(value: object) -> datetime | None:
    if value is not None and not isinstance(value, datetime):
        raise ValueError("Expected a timestamp in error tracking setup query results")
    return value


def _get_recent_usage(team: Team) -> _RecentErrorTrackingUsage:
    with tags_context(
        product=Product.ERROR_TRACKING,
        feature=Feature.QUERY,
        team_id=team.id,
        org_id=team.organization_id,
        query_type="error_tracking_setup_status",
    ):
        response = execute_hogql_query(_RECENT_USAGE_QUERY, team, query_type="error_tracking_setup_status")
        sdk_response = execute_hogql_query(_RECENT_SDK_USAGE_QUERY, team, query_type="error_tracking_setup_status_sdks")

    row = response.results[0] if response.results else [0, 0, None, None]
    observed_sdks: list[ErrorTrackingObservedSDK] = []
    for sdk_row in sdk_response.results or []:
        library = str(sdk_row[0])
        sdk = _SDK_CONFIGURATIONS_BY_LIBRARY.get(library)
        if sdk is None:
            continue

        last_seen_at = sdk_row[3]
        if not isinstance(last_seen_at, datetime):
            raise ValueError(f"Missing last seen timestamp for observed SDK {sdk.library}")

        latest_version = sdk_row[2]
        observed_sdks.append(
            ErrorTrackingObservedSDK(
                library=sdk.library,
                event_count=_as_int(sdk_row[1]),
                latest_version=str(latest_version) if latest_version else None,
                last_seen_at=last_seen_at,
                autocapture_configuration=sdk.autocapture_configuration,
                local_option=sdk.local_option,
            )
        )

    return _RecentErrorTrackingUsage(
        event_count=_as_int(row[0]),
        exception_count=_as_int(row[1]),
        last_event_at=_as_optional_datetime(row[2]),
        last_exception_at=_as_optional_datetime(row[3]),
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
        last_event_at=recent_usage.last_event_at if recent_usage else None,
        last_exception_at=recent_usage.last_exception_at if recent_usage else None,
        observed_sdks=recent_usage.observed_sdks if recent_usage else [],
        warnings=warnings,
    )
