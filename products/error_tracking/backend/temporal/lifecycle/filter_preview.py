"""Replay lifecycle filters without retaining a second copy of the exception event."""

import json
import hashlib
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.cache import cache
from django.utils.dateparse import parse_datetime

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.models import Team

from products.error_tracking.backend.facade.contracts import LifecycleFilterOutcome
from products.error_tracking.backend.temporal.alerts.filter_evaluation import (
    evaluate_lifecycle_filters,
    lifecycle_filter_properties,
)
from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs

logger = structlog.get_logger(__name__)
LOOKBACK = timedelta(days=7)


def _key(team_id: int, signal_id: str) -> str:
    return f"error_tracking:signal_filter_preview:v1:{team_id}:{signal_id}"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def remember_filter_inputs(signal_id: str, inputs: AlertDeliveryWorkflowInputs, properties: dict[str, object]) -> None:
    try:
        # Exception values remain in the event store. Per-property digests let a future filter verify
        # only its own inputs, including when emission read the ingestion cache before ClickHouse.
        cache.add(
            _key(inputs.team_id, signal_id),
            (asdict(inputs), {key: _digest(value) for key, value in properties.items()}),
            timeout=int(LOOKBACK.total_seconds()),
        )
    except Exception:
        logger.exception("error_tracking_filter_preview_snapshot_unavailable", team_id=inputs.team_id)


def _read_exceptions(team: Team, timestamps: dict[str, datetime]) -> dict[str, dict]:
    if not timestamps:
        return {}
    result = execute_hogql_query(
        query="""
            SELECT toString(uuid), properties FROM events
            WHERE uuid IN {ids} AND timestamp >= {start} AND timestamp <= {end}
            LIMIT {count}
        """,
        placeholders={
            "ids": ast.Tuple(exprs=[ast.Constant(value=value) for value in timestamps]),
            "start": ast.Constant(value=min(timestamps.values()) - timedelta(minutes=1)),
            "end": ast.Constant(value=max(timestamps.values()) + timedelta(minutes=1)),
            "count": ast.Constant(value=len(timestamps)),
        },
        team=team,
        query_type="ErrorTrackingSourceFilterPreviewExceptions",
        ch_user=ClickHouseUser.ERROR_TRACKING,
        workload=Workload.ONLINE,
    )
    return {key: json.loads(props) if isinstance(props, str) else props for key, props in result.results or []}


def replay_signal_filters(
    team: Team, signal_ids: list[str], compiled: dict[str, Any]
) -> dict[str, tuple[LifecycleFilterOutcome, dict[str, Any]]]:
    """Missing snapshots or unverifiable exception values have no verdict."""
    keys = {prop["key"] for prop in compiled.get("properties", [])}
    cached = cache.get_many([_key(team.pk, signal_id) for signal_id in signal_ids])
    snapshots = {}
    timestamps = {}
    for signal_id in signal_ids:
        snapshot = cached.get(_key(team.pk, signal_id))
        if snapshot is None:
            continue
        raw, digests = snapshot
        inputs = AlertDeliveryWorkflowInputs(**raw)
        fields = lifecycle_filter_properties(inputs)
        needed = keys.difference(fields).intersection(digests)
        snapshots[signal_id] = inputs, fields, digests, needed
        if (
            needed
            and inputs.event_uuid
            and inputs.event_timestamp
            and (stamp := parse_datetime(inputs.event_timestamp))
        ):
            timestamps[inputs.event_uuid] = stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)

    exceptions = _read_exceptions(team, timestamps)
    verdicts = {}
    for signal_id, (inputs, fields, digests, needed) in snapshots.items():
        properties = exceptions.get(inputs.event_uuid or "", {})
        if any(key not in properties or _digest(properties[key]) != digests[key] for key in needed):
            continue
        original = {key: properties[key] for key in needed}
        outcome = evaluate_lifecycle_filters(compiled, inputs, original, log_context={"preview": True})
        seen = {**original, **fields}
        verdicts[signal_id] = outcome, {key: seen[key] for key in sorted(keys) if key in seen}
    return verdicts
