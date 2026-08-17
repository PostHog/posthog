"""Per-case seeders for the replay-attribution eval.

Each case needs the events around its recording moment to exist in its own team. Without them the
window query the agent is steered to run comes back empty, every case degrades to attributing by
route, and the suite scores the fallback path instead of the recipe.

Events go straight to ClickHouse, the way the error-tracking seeder does, so the seed depends on
neither Kafka nor the demo matrix having produced anything. The session replay row goes through
``produce_replay_summary`` so a session lookup finds a real recording rather than nothing, which
would send the agent down a "this session does not exist" path for reasons unrelated to what the
suite measures. That helper writes through ``ClickhouseProducer``, which only bypasses Kafka while
``settings.TEST`` holds — true under the harness, which runs with ``TEST=1``.

One function per case: the seeder contract passes only the context, so case-specific data cannot
arrive as a parameter.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, timedelta
from typing import Any

from posthog.clickhouse.client import sync_execute
from posthog.models.event.sql import INSERT_EVENT_SQL
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from products.signals.evals.constants import (
    ELEMENT_TEXT_CASE,
    EXCEPTION_CASE,
    HEDGEBOX_ORIGIN,
    ROUTE_ONLY_CASE,
    SCANNER_ELEMENT_CASE,
    AttributionCase,
    SeededEvent,
)
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

__all__ = [
    "seed_element_text_attribution",
    "seed_exception_attribution",
    "seed_route_only_attribution",
    "seed_scanner_element_attribution",
]

_DISTINCT_ID = "eval-replay-attribution"
# Stable namespace, so the same distinct id resolves to the same synthetic person every run.
_PERSON_NAMESPACE = uuid.UUID("6b1f0d92-4c88-4a1b-9f0e-7c2d5a3e1b40")
_ZERO_CLICKHOUSE_TIMESTAMP = "1970-01-01 00:00:00.000000"
# Recordings run past the finding; the length only has to cover the case's start_time so the
# anchor lands inside the recording rather than after it ends.
_RECORDING_PADDING_SECONDS = 60


def _clickhouse_timestamp(value: Any) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def _insert_event(*, team_id: int, case: AttributionCase, seeded: SeededEvent) -> None:
    moment = case.recording_start_time + timedelta(seconds=case.start_time + seeded.offset_seconds)
    timestamp = _clickhouse_timestamp(moment)
    properties: dict[str, Any] = {
        "$session_id": case.session_id,
        "$current_url": f"{HEDGEBOX_ORIGIN}{seeded.pathname}",
        "$pathname": seeded.pathname,
        **seeded.properties,
    }
    sync_execute(
        INSERT_EVENT_SQL(),
        {
            "uuid": str(uuid.uuid4()),
            "event": seeded.event,
            "properties": json.dumps(properties),
            "timestamp": timestamp,
            "team_id": team_id,
            "distinct_id": _DISTINCT_ID,
            "elements_chain": seeded.elements_chain,
            "created_at": timestamp,
            "person_id": str(uuid.uuid5(_PERSON_NAMESPACE, _DISTINCT_ID)),
            "person_properties": "{}",
            "person_created_at": _ZERO_CLICKHOUSE_TIMESTAMP,
            "group0_properties": "{}",
            "group1_properties": "{}",
            "group2_properties": "{}",
            "group3_properties": "{}",
            "group4_properties": "{}",
            "group0_created_at": _ZERO_CLICKHOUSE_TIMESTAMP,
            "group1_created_at": _ZERO_CLICKHOUSE_TIMESTAMP,
            "group2_created_at": _ZERO_CLICKHOUSE_TIMESTAMP,
            "group3_created_at": _ZERO_CLICKHOUSE_TIMESTAMP,
            "group4_created_at": _ZERO_CLICKHOUSE_TIMESTAMP,
            "person_mode": "full",
        },
    )


def _install(context: CustomPromptSandboxContext, case: AttributionCase) -> dict[str, Any]:
    for seeded in case.events:
        _insert_event(team_id=context.team_id, case=case, seeded=seeded)

    recording_end = case.recording_start_time + timedelta(seconds=case.start_time + _RECORDING_PADDING_SECONDS)
    produce_replay_summary(
        team_id=context.team_id,
        session_id=case.session_id,
        distinct_id=_DISTINCT_ID,
        first_timestamp=case.recording_start_time,
        last_timestamp=recording_end,
        first_url=case.url,
        click_count=sum(1 for event in case.events if event.elements_chain),
        mouse_activity_count=len(case.events),
        active_milliseconds=(case.start_time + _RECORDING_PADDING_SECONDS) * 1000,
        console_error_count=sum(1 for event in case.events if event.event == "$exception"),
        snapshot_source="web",
        # The case writes its own events above; the helper's filler event would add an unrelated
        # row to the same session.
        ensure_analytics_event_in_session=False,
    )
    return {
        "session_id": case.session_id,
        "anchor": _clickhouse_timestamp(case.recording_start_time + timedelta(seconds=case.start_time)),
        "expected_path": case.expected_path,
        "seeded_events": [event.event for event in case.events],
    }


def seed_exception_attribution(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return _install(context, EXCEPTION_CASE)


def seed_element_text_attribution(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return _install(context, ELEMENT_TEXT_CASE)


def seed_route_only_attribution(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return _install(context, ROUTE_ONLY_CASE)


def seed_scanner_element_attribution(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return _install(context, SCANNER_ELEMENT_CASE)
