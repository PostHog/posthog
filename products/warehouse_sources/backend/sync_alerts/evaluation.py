"""Evaluation of due warehouse alerts on the shared alerts platform.

A check reads sync statuses from Postgres and reports which groups fail. A table (or a source, or a
destination) that fails is a breaching group, and an open group that stops failing resolves. The
lifecycle decision comes from the shared machine under `PLATFORM_WAREHOUSE_ALERT_POLICY`.

This reads and decides. It writes nothing, so a retried attempt reads the same due checks and makes
the same decisions. The platform records the outcomes in its own activity.

Each batch is one team's due checks, so every read here is one query for the whole batch.
"""

import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from django.db.models import Q

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team

from products.alerts_platform.backend.facade.api import due_checks, has_incident_destination, slot_of
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    InstanceCheckState,
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts_platform.backend.facade.grouping import (
    GroupDecision,
    GroupObservation,
    decide_groups,
    delivery_parts,
)
from products.alerts_platform.backend.facade.lifecycle import (
    PLATFORM_WAREHOUSE_ALERT_POLICY,
    AlertSnapshot,
    AlertState,
    NotificationAction,
    decide_incident_action,
)
from products.alerts_platform.backend.facade.payload import MAX_BATCH_PAYLOAD_BYTES, payload_bytes
from products.alerts_platform.backend.facade.platform_metrics import (
    increment_checks,
    increment_checks_deferred,
    increment_state_transition,
    record_batch_duration,
    safe_record,
)
from products.alerts_platform.backend.facade.scheduling import is_utc_datetime_blocked, parse_blocked_windows_tuples
from products.warehouse_sources.backend.models.external_data_destination import ExternalDataDestination
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.presentation.views.external_data_source.helpers import (
    get_error_redaction_values,
    redact_error_message,
)
from products.warehouse_sources.backend.sync_alerts.destinations import EVENT_IDS_BY_INCIDENT_ACTION, EVENT_IDS_BY_KIND
from products.warehouse_sources.backend.sync_alerts.wording import (
    DESTINATION_LABEL,
    DESTINATION_TYPE_LABEL,
    REASON_LABEL,
    SCHEMA_LABEL,
    SOURCE_ID_KEY,
    SOURCE_LABEL,
    STATUS_LABEL,
    destination_alerts_url,
    group_by_of,
    source_alerts_url,
)

logger = structlog.get_logger(__name__)

Status = ExternalDataSchema.Status
FAILED_STATUSES: Final = frozenset({Status.FAILED.value})
BILLING_LIMIT_STATUSES: Final = frozenset({Status.BILLING_LIMIT_REACHED.value, Status.BILLING_LIMIT_TOO_LOW.value})
FAILING_DESTINATION_STATUSES: Final = frozenset(
    {ExternalDataDestination.Status.FAILING.value, ExternalDataDestination.Status.PAUSED.value}
)

# Rows one batch reads. A team past it still alerts on the first rows, and an open group the read may
# have cut is left open rather than resolved.
MAX_FAILING_ROWS: Final = 1000

_BILLING_REASONS: Final = {
    Status.BILLING_LIMIT_REACHED.value: "Syncing stopped because the project reached its data warehouse billing limit.",
    Status.BILLING_LIMIT_TOO_LOW.value: "Syncing stopped because the billing limit is too low to sync this table.",
}
_FAILED_WITHOUT_ERROR: Final = "The last sync failed."
_DESTINATION_FAILED_WITHOUT_ERROR: Final = "The last delivery to this destination failed."

Decision = tuple[PlatformAlertOutcome, AlertDeliveryRequest | None]


@frozen
class _Failing:
    """One failing row, with what its group's labels need."""

    group_ids: Mapping[str, str]
    status: str
    labels: dict[str, str]


@frozen
class _Reading:
    """What one batch read: the failing rows, and the labels of open groups that no longer fail."""

    failing: tuple[_Failing, ...]
    truncated: bool
    resolved_labels: Mapping[str, dict[str, str]]
    # Open groups that no longer fail only because a sync is running again. They stay open until it ends.
    retrying: frozenset[str] = frozenset()


def evaluate_warehouse_alert_batch(
    source: SourceKind, team_id: int, slot: str, cutoff: datetime
) -> SourceBatchEvaluation:
    """Evaluates one batch key of a warehouse alert kind against the tick's cutoff."""
    started_at = time.monotonic()
    checks = due_checks(team_id, source.value, slot, cutoff)
    if not checks:
        return SourceBatchEvaluation(outcomes=(), deliveries=())
    tz_name = Team.objects.filter(id=team_id).values_list("timezone", flat=True).first()
    if tz_name is None:
        return SourceBatchEvaluation(outcomes=(), deliveries=())

    reading = (
        _read_sources(team_id, checks) if source == SourceKind.WAREHOUSE_SOURCE else _read_destinations(team_id, checks)
    )
    decided = [
        _decide(source, check, reading, now=cutoff, muted=_in_quiet_hours(check, cutoff, tz_name)) for check in checks
    ]
    evaluation = _collect(source, decided, team_id=team_id, slot=slot)
    safe_record(record_batch_duration, source.value, int((time.monotonic() - started_at) * 1000))
    return evaluation


def _in_quiet_hours(check: PlatformAlertCheckInput, now: datetime, tz_name: str) -> bool:
    try:
        return is_utc_datetime_blocked(now, tz_name, parse_blocked_windows_tuples(check.schedule_restriction))
    except Exception:
        # A restriction that cannot be read must not hold back a failure.
        logger.exception("Unparseable schedule restriction on a warehouse alert", check_id=str(check.id))
        return False


def _observations(source: SourceKind, check: PlatformAlertCheckInput, reading: _Reading) -> list[GroupObservation]:
    config = check.source_config
    if source == SourceKind.WAREHOUSE_DESTINATION:
        scope = {str(item) for item in config.get("destination_ids") or []}
        return [
            GroupObservation(grouping_key=row.group_ids["destination"], current_breached=True, labels=row.labels)
            for row in reading.failing
            if not scope or row.group_ids["destination"] in scope
        ]

    scope = {str(item) for item in config.get("source_ids") or []}
    statuses = FAILED_STATUSES | (BILLING_LIMIT_STATUSES if config.get("include_billing_limits") else frozenset())
    in_scope = [
        row for row in reading.failing if row.status in statuses and (not scope or row.group_ids["source"] in scope)
    ]
    if group_by_of(config) == "schema":
        return [
            GroupObservation(grouping_key=row.group_ids["schema"], current_breached=True, labels=row.labels)
            for row in in_scope
        ]
    by_source: dict[str, list[_Failing]] = {}
    for row in in_scope:
        by_source.setdefault(row.group_ids["source"], []).append(row)
    return [
        GroupObservation(
            grouping_key=source_id,
            current_breached=True,
            # How many of the source's tables fail, which the message states.
            value=float(len(rows)),
            labels={
                **rows[0].labels,
                SCHEMA_LABEL: ", ".join(row.labels[SCHEMA_LABEL] for row in rows),
            },
        )
        for source_id, rows in by_source.items()
    ]


def _decide(
    source: SourceKind, check: PlatformAlertCheckInput, reading: _Reading, *, now: datetime, muted: bool
) -> Decision:
    def absent(key: str) -> GroupObservation | None:
        # A group the read may have cut could still be failing, so it stays as it is. So does one whose
        # sync is retrying, so a retry that fails again does not resolve and re-fire the same failure.
        if reading.truncated or key in reading.retrying:
            return None
        return GroupObservation(grouping_key=key, current_breached=False, labels=reading.resolved_labels.get(key, {}))

    decision = decide_groups(
        check,
        _observations(source, check, reading),
        snapshot_of=lambda instance, _prior: _snapshot(check, instance),
        policy=PLATFORM_WAREHOUSE_ALERT_POLICY,
        now=now,
        muted=muted,
        absent=absent,
    )
    for verdict in decision.verdicts:
        safe_record(increment_checks, source.value, verdict.outcome.notification.value)
        if verdict.snapshot.state != verdict.outcome.new_state:
            safe_record(
                increment_state_transition, source.value, verdict.snapshot.state.value, verdict.outcome.new_state.value
            )
    recorded = decision.as_outcome(
        configuration_id=check.id,
        evaluation_key=f"slot:{slot_of(check.next_check_at, now)}",
        grouping=check.grouping,
        query_duration_ms=None,
        results_cut=reading.truncated,
    )
    return recorded, _request(source, check, recorded, decision)


def _snapshot(check: PlatformAlertCheckInput, instance: InstanceCheckState) -> AlertSnapshot:
    return AlertSnapshot(
        state=AlertState(instance.state),
        cooldown=timedelta(minutes=check.cooldown_minutes),
        last_notified_at=instance.last_notified_at,
        snooze_until=instance.snooze_until,
        consecutive_failures=check.consecutive_failures,
        firing_started_at=instance.firing_started_at,
    )


def _request(
    source: SourceKind, check: PlatformAlertCheckInput, recorded: PlatformAlertOutcome, decision: GroupDecision
) -> AlertDeliveryRequest | None:
    """The delivery for a recorded outcome, or None when it neither announces nor moves a firing.

    A firing that opens or closes needs a delivery even when cooldown or mute held the message,
    because a paging destination needs one resolve for every trigger.
    """
    actions = {
        verdict.group.grouping_key: action
        for verdict in decision.verdicts
        if (
            action := decide_incident_action(
                verdict.snapshot.state, verdict.outcome.new_state, policy=PLATFORM_WAREHOUSE_ALERT_POLICY
            )
        )
        is not None
    }
    if actions and not has_incident_destination(team_id=check.team_id, configuration_id=check.id):
        actions = {}
    sends_messages = any(verdict.outcome.notification != NotificationAction.NONE for verdict in decision.verdicts)
    if not sends_messages and not actions:
        return None
    alert_url = source_alerts_url if source == SourceKind.WAREHOUSE_SOURCE else destination_alerts_url
    return AlertDeliveryRequest(
        source=source,
        team_id=check.team_id,
        configuration_id=str(check.id),
        evaluation_key=recorded.evaluation_key,
        destination_alert_id=str(check.destination_alert_id),
        event_ids_by_kind=EVENT_IDS_BY_KIND[source],
        event_ids_by_incident_action=EVENT_IDS_BY_INCIDENT_ACTION[source],
        incident_actions=actions,
        sends_messages=sends_messages,
        source_alert_url=alert_url(check.team_id, check.destination_alert_id),
        owned_by_platform=check.owned_by_platform,
        overflowed=recorded.overflowed,
        overflow_is_lower_bound=recorded.overflow_is_lower_bound,
        parts=delivery_parts(recorded, actions),
    )


def _collect(source: SourceKind, decided: Sequence[Decision], *, team_id: int, slot: str) -> SourceBatchEvaluation:
    """The batch, held to one payload. A check that does not fit keeps its due time for a later tick."""
    outcomes: list[PlatformAlertOutcome] = []
    deliveries: list[AlertDeliveryRequest] = []
    deferred = 0
    spent = 0
    for outcome, delivery in decided:
        size = payload_bytes(outcome) + (payload_bytes(delivery) if delivery is not None else 0)
        if spent + size > MAX_BATCH_PAYLOAD_BYTES:
            deferred += 1
            continue
        spent += size
        outcomes.append(outcome)
        if delivery is not None:
            deliveries.append(delivery)
    if deferred:
        logger.warning(
            "Deferred warehouse alert checks over the batch payload budget",
            source=source.value,
            team_id=team_id,
            slot=slot,
            deferred=deferred,
        )
        safe_record(increment_checks_deferred, source.value, deferred)
    return SourceBatchEvaluation(outcomes=tuple(outcomes), deliveries=tuple(deliveries), omitted=deferred)


def _open_keys(checks: Sequence[PlatformAlertCheckInput]) -> set[str]:
    return {key for check in checks for key in check.open_keys()}


def _scoped_ids(checks: Sequence[PlatformAlertCheckInput], config_key: str) -> set[str] | None:
    """Every id the batch's checks watch, or None when one of them watches them all.

    The read is cut to these ids before its row limit, so a scoped check is not starved by other rows.
    """
    ids: set[str] = set()
    for check in checks:
        scope = check.source_config.get(config_key) or []
        if not scope:
            return None
        ids.update(str(item) for item in scope)
    return set(_uuids(ids))


def _source_display(source_type: str, prefix: str | None) -> str:
    return f"{source_type} ({prefix})" if prefix else source_type


def _read_sources(team_id: int, checks: Sequence[PlatformAlertCheckInput]) -> _Reading:
    statuses = FAILED_STATUSES | (
        BILLING_LIMIT_STATUSES if any(check.source_config.get("include_billing_limits") for check in checks) else set()
    )
    query = (
        ExternalDataSchema.objects.filter(team_id=team_id, status__in=statuses)
        # `deleted` is nullable, and a NULL row is not deleted.
        .exclude(deleted=True)
        .exclude(source__deleted=True)
    )
    if (scoped := _scoped_ids(checks, "source_ids")) is not None:
        query = query.filter(source_id__in=scoped)
    schemas = list(
        query
        # A schema the user turned off keeps its last status, and is not failing. One PostHog
        # turned off after an error it cannot retry past is.
        .filter(Q(should_sync=True) | Q(auto_disabled_at__isnull=False))
        .select_related("source")
        # Decrypted only for the sources whose errors need redacting, below.
        .defer("source__job_inputs")
        .order_by("source_id", "name", "id")[: MAX_FAILING_ROWS + 1]
    )
    truncated = len(schemas) > MAX_FAILING_ROWS
    schemas = schemas[:MAX_FAILING_ROWS]
    secrets = _secret_values(
        team_id, {schema.source_id for schema in schemas if schema.latest_error and schema.status in FAILED_STATUSES}
    )

    failing: list[_Failing] = []
    for schema in schemas:
        source_id = str(schema.source_id)
        if schema.status in BILLING_LIMIT_STATUSES:
            reason = _BILLING_REASONS[schema.status]
        elif schema.latest_error:
            # The error can quote a connection string or a request URL, and the message leaves PostHog.
            reason = (
                redact_error_message(schema.latest_error, secrets.get(source_id, frozenset())) or _FAILED_WITHOUT_ERROR
            )
        else:
            reason = _FAILED_WITHOUT_ERROR
        failing.append(
            _Failing(
                group_ids={"schema": str(schema.id), "source": source_id},
                status=schema.status or "",
                labels={
                    SOURCE_ID_KEY: source_id,
                    SOURCE_LABEL: _source_display(schema.source.source_type, schema.source.prefix),
                    SCHEMA_LABEL: schema.name,
                    REASON_LABEL: reason,
                },
            )
        )

    failing_keys = {key for row in failing for key in row.group_ids.values()}
    open_keys = _open_keys(checks)
    resolved = open_keys - failing_keys
    return _Reading(
        failing=tuple(failing),
        truncated=truncated,
        # A row can still be present in the batch-wide failing read while one check excludes its
        # status (for example, a billing limit). Hydrate every open key so that check can resolve
        # with its source and table names.
        resolved_labels=_source_labels(team_id, open_keys),
        retrying=_retrying_keys(team_id, resolved),
    )


def _secret_values(team_id: int, source_ids: set[UUID]) -> dict[str, frozenset[str]]:
    if not source_ids:
        return {}
    return {
        str(source.id): get_error_redaction_values(source)
        for source in ExternalDataSource.objects.filter(team_id=team_id, id__in=source_ids)
    }


def _source_labels(team_id: int, keys: set[str]) -> dict[str, dict[str, str]]:
    """Names for groups that stopped failing, so the resolve says what recovered. Deleted rows count too."""
    if not keys:
        return {}
    labels: dict[str, dict[str, str]] = {}
    ids = _uuids(keys)
    for schema_id, name, source_id, source_type, prefix in ExternalDataSchema.objects.filter(
        team_id=team_id, id__in=ids
    ).values_list("id", "name", "source_id", "source__source_type", "source__prefix"):
        labels[str(schema_id)] = {
            SOURCE_ID_KEY: str(source_id),
            SOURCE_LABEL: _source_display(source_type, prefix),
            SCHEMA_LABEL: name,
        }
    for source_id, source_type, prefix in ExternalDataSource.objects.filter(team_id=team_id, id__in=ids).values_list(
        "id", "source_type", "prefix"
    ):
        labels[str(source_id)] = {SOURCE_ID_KEY: str(source_id), SOURCE_LABEL: _source_display(source_type, prefix)}
    return labels


def _retrying_keys(team_id: int, keys: set[str]) -> frozenset[str]:
    """The keys among `keys` with a sync running again: a table that runs, or a source with a table that runs.

    A retry paints a failed table Running, so its group must not resolve until the retry ends.
    """
    if not keys:
        return frozenset()
    ids = _uuids(keys)
    running = (
        ExternalDataSchema.objects.filter(team_id=team_id, status=Status.RUNNING, should_sync=True)
        .exclude(deleted=True)
        .exclude(source__deleted=True)
        .filter(Q(id__in=ids) | Q(source_id__in=ids))
        .values_list("id", "source_id")
    )
    return frozenset(str(item) for row in running for item in row) & keys


def _read_destinations(team_id: int, checks: Sequence[PlatformAlertCheckInput]) -> _Reading:
    destinations = ExternalDataDestination.objects.for_team(team_id, canonical=True)
    failing_query = destinations.filter(deleted=False, status__in=FAILING_DESTINATION_STATUSES)
    if (scoped := _scoped_ids(checks, "destination_ids")) is not None:
        failing_query = failing_query.filter(id__in=scoped)
    rows = list(
        failing_query.order_by("name", "id").values_list("id", "name", "type", "status", "latest_error")[
            : MAX_FAILING_ROWS + 1
        ]
    )
    truncated = len(rows) > MAX_FAILING_ROWS
    failing = tuple(
        _Failing(
            group_ids={"destination": str(destination_id)},
            status=status,
            labels={
                DESTINATION_LABEL: name,
                DESTINATION_TYPE_LABEL: _destination_type_label(destination_type),
                STATUS_LABEL: ExternalDataDestination.Status(status).label,
                # Saved in words safe to show the user, without credentials.
                REASON_LABEL: latest_error or _DESTINATION_FAILED_WITHOUT_ERROR,
            },
        )
        for destination_id, name, destination_type, status, latest_error in rows[:MAX_FAILING_ROWS]
    )
    resolved = _open_keys(checks) - {row.group_ids["destination"] for row in failing}
    resolved_labels: dict[str, dict[str, str]] = {}
    if resolved:
        for destination_id, name, destination_type in destinations.filter(id__in=_uuids(resolved)).values_list(
            "id", "name", "type"
        ):
            resolved_labels[str(destination_id)] = {
                DESTINATION_LABEL: name,
                DESTINATION_TYPE_LABEL: _destination_type_label(destination_type),
            }
    return _Reading(failing=failing, truncated=truncated, resolved_labels=resolved_labels)


def _destination_type_label(destination_type: str) -> str:
    if destination_type in ExternalDataDestination.Type.values:
        return str(ExternalDataDestination.Type(destination_type).label)
    return destination_type


def _uuids(keys: set[str]) -> list[str]:
    # An open key is a stored id this product minted, but a malformed one must not fail the batch's query.
    return [key for key in keys if _is_uuid(key)]


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
