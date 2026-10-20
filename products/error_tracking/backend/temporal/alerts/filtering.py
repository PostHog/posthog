"""Alert filter evaluation: does a lifecycle transition match an alert's filters.

Filters gate thread openers only; replies follow the thread without a second
evaluation. The compiled bytecode is the same one hog function destinations
evaluate, and the property surface mirrors the internal-event consumer
(convertInternalEventToHogFunctionInvocationGlobals in nodejs/src/cdp/utils.ts):
the triggering exception's properties are flattened under the lifecycle event's
own properties, with the lifecycle properties winning on key collisions.
"""

import structlog

from posthog.models import Team

from products.error_tracking.backend.models import ErrorTrackingAlert
from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs
from products.error_tracking.backend.temporal.lifecycle.event_properties import fetch_event_properties

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.stl import BLOCKING_FUNCTIONS

logger = structlog.get_logger(__name__)


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


# Every key the lifecycle snapshot can carry, populated or not: a filter on one of
# these is decidable without the exception (an absent value is a real "not set").
LIFECYCLE_PROPERTY_KEYS = frozenset(
    {
        "name",
        "description",
        "issue_description",
        "first_seen",
        "severity",
        "status",
        "exception_timestamp",
        "fingerprint",
        "assignee",
    }
)


def _filter_property_keys(alert: ErrorTrackingAlert, event: str) -> set[str]:
    # Global properties apply to every branch; event branches are OR'd by the
    # compiler, so only the branch for this event can constrain the outcome.
    filters = alert.filters or {}
    leaves = list(filters.get("properties") or [])
    for entity in filters.get("events") or []:
        if isinstance(entity, dict) and entity.get("id") == event:
            leaves.extend(entity.get("properties") or [])
    return {leaf["key"] for leaf in leaves if isinstance(leaf, dict) and isinstance(leaf.get("key"), str)}


def alert_filters_match(
    alert: ErrorTrackingAlert, inputs: AlertDeliveryWorkflowInputs, exception_properties: dict[str, object] | None
) -> bool:
    """Whether the transition passes the alert's filters.

    `exception_properties` is None when the transition has no triggering event to
    read them from (manual reopen, assign). Filters on lifecycle keys still evaluate;
    one on any other key fails closed, because negated operators (is not, is not
    set) would otherwise pass on the missing value and open excluded issues.
    """
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
    if exception_properties is None:
        # Conservative on purpose: one OR'd branch that needs the exception makes the
        # whole filter undecidable, even if a sibling branch would match on its own.
        decidable_keys = LIFECYCLE_PROPERTY_KEYS | (inputs.extra or {}).keys()
        unavailable_keys = _filter_property_keys(alert, inputs.event) - decidable_keys
        if unavailable_keys:
            logger.info(
                "error_tracking_alert_filter_needs_exception_properties",
                alert_id=str(alert.id),
                team_id=inputs.team_id,
                lifecycle_event=inputs.event,
                keys=sorted(unavailable_keys),
            )
            return False
        exception_properties = {}
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


def fetch_exception_properties(inputs: AlertDeliveryWorkflowInputs) -> dict[str, object] | None:
    """The triggering exception's properties, for openers with configured filters.

    Ingestion transitions carry the event uuid: the Redis handoff (with a
    ClickHouse fallback) that the lifecycle activities already use serves those,
    and a miss raises so the activity retries. Manual transitions (reopen, assign)
    have no triggering event and get no lookup (a bulk action would turn into one
    ClickHouse scan per issue): None tells the filter the data is unavailable.
    """
    if not inputs.event_uuid:
        return None
    team = Team.objects.get(id=inputs.team_id)
    return fetch_event_properties(team, _EventPropertiesInputs(inputs))
