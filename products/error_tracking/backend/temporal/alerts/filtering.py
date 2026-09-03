"""Alert filter evaluation: does a lifecycle transition match an alert's filters.

Filters gate thread openers only; replies follow the thread without a second
evaluation. The compiled bytecode is the same one hog function destinations
evaluate, and the property surface mirrors the internal-event consumer
(convertInternalEventToHogFunctionInvocationGlobals in nodejs/src/cdp/utils.ts):
the triggering exception's properties are flattened under the lifecycle event's
own properties, with the lifecycle properties winning on key collisions.
"""

import json

import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.models import Team

from products.error_tracking.backend.models import ErrorTrackingAlert
from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs
from products.error_tracking.backend.temporal.lifecycle.event_properties import fetch_event_properties

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.stl import BLOCKING_FUNCTIONS

logger = structlog.get_logger(__name__)

# issue_id on events resolves through the fingerprint-state join, which cannot prune by
# partition on its own; the time bound keeps the manual-opener fallback from scanning a
# team's whole exception history. An issue quiet for longer has no useful sample anyway.
MANUAL_FALLBACK_LOOKBACK_DAYS = 30


def has_configured_filters(alert: ErrorTrackingAlert) -> bool:
    # Empty filters still carry trivially-true compiled bytecode, so look at the
    # configured predicate keys instead.
    filters = alert.filters or {}
    return any(filters.get(key) for key in ("events", "actions", "properties", "filter_test_accounts"))


def _coerce_numeric(value: str) -> object:
    # Extras cross Temporal as strings; numeric filters need real numbers or
    # HogVM compares lexicographically ("9" > "10").
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def alert_filters_match(
    alert: ErrorTrackingAlert, inputs: AlertDeliveryWorkflowInputs, exception_properties: dict[str, object]
) -> bool:
    if not has_configured_filters(alert):
        return True
    bytecode = (alert.filters or {}).get("bytecode")
    if not bytecode:
        # Configured filters without compiled bytecode cannot be honored: skip the
        # opener rather than posting issues the user meant to exclude.
        logger.warning("error_tracking_alert_filters_missing_bytecode", alert_id=str(alert.id))
        return False

    # The producers always emit these keys, null included, and on the CDP plane a null
    # lifecycle value shadows the exception's own property; mirror that so both planes agree.
    lifecycle_properties: dict[str, object] = {
        **{key: _coerce_numeric(value) for key, value in (inputs.extra or {}).items()},
        "name": inputs.issue_name,
        "description": inputs.issue_description,
        "issue_description": inputs.issue_description,
        "first_seen": inputs.first_seen,
        "severity": inputs.severity,
    }
    optional_properties = {
        # Spiking events carry no status at all, so absence must stay absence.
        "status": inputs.status,
        # Older in-flight payloads predate lifecycle_timestamp; the exception time
        # is the right value for created/reopened and the previous one for spiking.
        "exception_timestamp": inputs.lifecycle_timestamp or inputs.event_timestamp,
        "fingerprint": inputs.fingerprint,
        "assignee": inputs.assignee,
    }
    lifecycle_properties.update({key: value for key, value in optional_properties.items() if value is not None})
    filter_globals = {
        "event": inputs.event,
        "distinct_id": inputs.issue_id,
        "timestamp": inputs.event_timestamp,
        "elements_chain": "",
        "properties": {**exception_properties, **lifecycle_properties},
    }
    try:
        # Filters run on the shared worker; a smuggled blocking call must not hold it.
        result = execute_bytecode(bytecode, filter_globals, disallowed_functions=BLOCKING_FUNCTIONS).result
    except Exception:
        # Match the hog function consumer: a filter that cannot be evaluated
        # skips delivery instead of firing on excluded issues.
        logger.exception(
            "error_tracking_alert_filter_evaluation_failed",
            alert_id=str(alert.id),
            team_id=inputs.team_id,
            lifecycle_event=inputs.event,
        )
        return False
    return bool(result)


class _EventPropertiesInputs:
    """Adapter for the lifecycle event-properties protocol."""

    class _Snapshot:
        def __init__(self, created_at: str) -> None:
            self.created_at = created_at

    def __init__(self, inputs: AlertDeliveryWorkflowInputs) -> None:
        self.team_id = inputs.team_id
        self.event_uuid = inputs.event_uuid or ""
        self.event_timestamp = inputs.event_timestamp or ""
        self.issue = self._Snapshot(inputs.first_seen or "")


def fetch_exception_properties(inputs: AlertDeliveryWorkflowInputs) -> dict[str, object]:
    """The triggering exception's properties, for openers with configured filters.

    Ingestion transitions carry the event uuid: the Redis handoff (with a
    ClickHouse fallback) that the lifecycle activities already use serves those,
    and a miss raises so the activity retries. Manual openers carry no triggering
    event, so the issue's latest exception stands in, resolved through the
    fingerprint override mapping so merges and splits keep matching; a miss there
    is expected (old issues age out of retention) and evaluates as no event
    properties.
    """
    team = Team.objects.get(id=inputs.team_id)
    if inputs.event_uuid:
        return fetch_event_properties(team, _EventPropertiesInputs(inputs))
    return _fetch_latest_issue_exception_properties(team, inputs)


def _fetch_latest_issue_exception_properties(team: Team, inputs: AlertDeliveryWorkflowInputs) -> dict[str, object]:
    query = parse_select(
        """
        SELECT properties
        FROM events
        WHERE event = '$exception'
            AND issue_id = toUUID({issue_id})
            AND timestamp > now() - INTERVAL {lookback_days} DAY
        ORDER BY timestamp DESC
        LIMIT 1
        """,
        placeholders={
            "issue_id": ast.Constant(value=inputs.issue_id),
            "lookback_days": ast.Constant(value=MANUAL_FALLBACK_LOOKBACK_DAYS),
        },
    )
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="ErrorTrackingAlertFilterEventProperties",
        workload=Workload.OFFLINE,
        ch_user=ClickHouseUser.ERROR_TRACKING,
    )
    if not response.results:
        logger.warning(
            "error_tracking_alert_filter_event_not_found",
            team_id=inputs.team_id,
            issue_id=inputs.issue_id,
        )
        return {}
    properties = response.results[0][0]
    if isinstance(properties, str):
        properties = json.loads(properties)
    return properties if isinstance(properties, dict) else {}
