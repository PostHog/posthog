"""Seed synthetic ClickHouse product telemetry for one self-driving eval task.

Materializes a task's `seed` spec (see ../TASK_SPEC.md) into real rows in
`sharded_events`, so the research agent's HogQL queries over `events` find
plausible telemetry: funnels with drop-offs, $exception bursts, custom events.

Rows are inserted directly with sync_execute + BULK_INSERT_EVENT_SQL — the same
mechanism as posthog.models.event.util.bulk_create_events — bypassing Kafka and
the ingestion pipeline. Person-on-events columns (person_id, person_properties,
person_mode='full') are populated so HogQL person expressions work.

Run through Django:
    DEBUG=1 python manage.py shell -c "
    from products.signals.eval.self_driving.harness.seed import seed_task_events
    print(seed_task_events(team_id, task['seed']))"
"""

import json
import uuid
import random
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.clickhouse.client import sync_execute
from posthog.models.event.sql import BULK_INSERT_EVENT_SQL

# Local dev writes land in sharded_events; sharded_events_recent is cleared too
# for parity with clear_eval_data, in case anything ever mirrors rows there.
EVENTS_DATA_TABLES = ("sharded_events", "sharded_events_recent")

INSERT_CHUNK_SIZE = 500
CLICKHOUSE_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
ZERO_TIMESTAMP = "1970-01-01 00:00:00"

MIN_USERS = 50
MAX_USERS = 300

_VALUES_TEMPLATE = """(
    %(uuid_{i})s, %(event_{i})s, %(properties_{i})s, %(timestamp_{i})s,
    %(team_id_{i})s, %(distinct_id_{i})s, %(elements_chain_{i})s,
    %(person_id_{i})s, %(person_properties_{i})s, %(person_created_at_{i})s,
    %(group0_properties_{i})s, %(group1_properties_{i})s, %(group2_properties_{i})s,
    %(group3_properties_{i})s, %(group4_properties_{i})s,
    %(group0_created_at_{i})s, %(group1_created_at_{i})s, %(group2_created_at_{i})s,
    %(group3_created_at_{i})s, %(group4_created_at_{i})s,
    %(person_mode_{i})s, %(created_at_{i})s, %(_timestamp_{i})s, 0
)"""


@dataclass(frozen=True)
class _SeedUser:
    distinct_id: str
    person_id: str
    person_created_at: datetime


@dataclass(frozen=True)
class _SeedEvent:
    event: str
    properties: dict[str, Any]
    timestamp: datetime
    user: _SeedUser


def _rng_uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _build_population(rng: random.Random, size: int, window_start: datetime) -> tuple[list[_SeedUser], list[float]]:
    users = [
        _SeedUser(
            distinct_id=_rng_uuid(rng),
            person_id=_rng_uuid(rng),
            person_created_at=window_start - timedelta(days=rng.uniform(1, 120)),
        )
        for _ in range(size)
    ]
    # Zipf-ish activity distribution: a heavy head of power users, a long tail.
    weights = [(rank + 1) ** -0.7 for rank in range(size)]
    return users, weights


def _pick_user(rng: random.Random, users: list[_SeedUser], weights: list[float]) -> _SeedUser:
    return rng.choices(users, weights=weights, k=1)[0]


def _day_anchor(now: datetime, days_ago: int) -> datetime:
    return (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)


def _working_hours_ts(rng: random.Random, day: datetime, now: datetime) -> datetime:
    # Cluster around mid-afternoon UTC with jitter; never emit future timestamps.
    for _ in range(8):
        hour = min(22, max(7, round(rng.gauss(14.0, 3.2))))
        ts = day.replace(
            hour=hour, minute=rng.randrange(60), second=rng.randrange(60), microsecond=rng.randrange(1_000_000)
        )
        if ts <= now:
            return ts
    return max(day, now - timedelta(minutes=rng.uniform(1, 240)))


def _seed_funnel_stream(
    rng: random.Random,
    stream: dict[str, Any],
    users: list[_SeedUser],
    weights: list[float],
    days: int,
    now: datetime,
) -> list[_SeedEvent]:
    event_names: list[str] = stream["events"]
    daily: list[int] = stream["daily"]
    drop: dict[str, Any] | None = stream.get("drop_after")
    drop_cutoff = now - timedelta(hours=float(drop["from_hours_ago"])) if drop else None
    drop_index = event_names.index(drop["event"]) if drop else -1

    out: list[_SeedEvent] = []
    for days_ago in range(days):
        day = _day_anchor(now, days_ago)
        for _ in range(daily[0]):
            user = _pick_user(rng, users, weights)
            session_id = _rng_uuid(rng)
            ts = _working_hours_ts(rng, day, now)
            in_drop = drop_cutoff is not None and ts >= drop_cutoff
            for step, event_name in enumerate(event_names):
                # Chain conditional pass-through rates so per-event daily volumes
                # land near the spec; the drop modifier rewrites one step's rate.
                prev_daily = daily[step - 1] if step > 0 else daily[0]
                step_daily = float(drop["to_daily"]) if drop and in_drop and step == drop_index else float(daily[step])
                p = min(1.0, step_daily / prev_daily) if prev_daily else 0.0
                if rng.random() > p:
                    break
                out.append(
                    _SeedEvent(
                        event=event_name,
                        properties={"$lib": "web", "$session_id": session_id},
                        timestamp=min(ts, now),
                        user=user,
                    )
                )
                ts += timedelta(seconds=rng.uniform(20, 240))
    return out


def _seed_exception_stream(
    rng: random.Random,
    stream: dict[str, Any],
    users: list[_SeedUser],
    weights: list[float],
    days: int,
    now: datetime,
) -> list[_SeedEvent]:
    properties = {
        "$exception_type": stream.get("type", "Error"),
        "$exception_message": stream["message"],
        "$exception_source": stream.get("source", ""),
        "$lib": "posthog-node",
    }

    out: list[_SeedEvent] = []
    for days_ago in range(days):
        day = _day_anchor(now, days_ago)
        for _ in range(int(stream.get("daily", 0))):
            out.append(
                _SeedEvent(
                    event="$exception",
                    properties=dict(properties),
                    timestamp=_working_hours_ts(rng, day, now),
                    user=_pick_user(rng, users, weights),
                )
            )

    burst: dict[str, Any] | None = stream.get("burst")
    if burst:
        window_start = now - timedelta(hours=float(burst["from_hours_ago"]))
        window_seconds = (now - window_start).total_seconds()
        for _ in range(int(burst["count"])):
            # Front-loaded spread: the errors pile up right after the trigger.
            ts = window_start + timedelta(seconds=window_seconds * rng.betavariate(1.5, 2.5))
            out.append(
                _SeedEvent(
                    event="$exception",
                    properties=dict(properties),
                    timestamp=min(ts, now),
                    user=_pick_user(rng, users, weights),
                )
            )
    return out


def _seed_custom_stream(
    rng: random.Random,
    stream: dict[str, Any],
    users: list[_SeedUser],
    weights: list[float],
    days: int,
    now: datetime,
) -> list[_SeedEvent]:
    out: list[_SeedEvent] = []
    for days_ago in range(days):
        day = _day_anchor(now, days_ago)
        for _ in range(int(stream.get("daily", 0))):
            out.append(
                _SeedEvent(
                    event=stream["event"],
                    properties={"$lib": "web", **stream.get("properties", {})},
                    timestamp=_working_hours_ts(rng, day, now),
                    user=_pick_user(rng, users, weights),
                )
            )
    burst: dict[str, Any] | None = stream.get("burst")
    if burst:
        window_start = now - timedelta(hours=float(burst["from_hours_ago"]))
        window_seconds = (now - window_start).total_seconds()
        for _ in range(int(burst["count"])):
            ts = window_start + timedelta(seconds=window_seconds * rng.betavariate(1.5, 2.5))
            out.append(
                _SeedEvent(
                    event=stream["event"],
                    properties={"$lib": "web", **stream.get("properties", {})},
                    timestamp=min(ts, now),
                    user=_pick_user(rng, users, weights),
                )
            )
    return out


_STREAM_SEEDERS = {
    "funnel": _seed_funnel_stream,
    "exception": _seed_exception_stream,
    "custom": _seed_custom_stream,
}


def _stream_head_daily(stream: dict[str, Any], days: int) -> float:
    if stream["kind"] == "funnel":
        return float(stream["daily"][0])
    burst_daily = float(stream["burst"]["count"]) / max(days, 1) if stream.get("burst") else 0.0
    return float(stream.get("daily", 0)) + burst_daily


def _insert_chunk(team_id: int, rows: list[_SeedEvent], now: datetime) -> None:
    inserted_at = now.strftime("%Y-%m-%d %H:%M:%S")
    values: list[str] = []
    params: dict[str, Any] = {}
    for i, row in enumerate(rows):
        values.append(_VALUES_TEMPLATE.format(i=i))
        ts = row.timestamp.strftime(CLICKHOUSE_TIMESTAMP_FORMAT)
        row_params: dict[str, Any] = {
            "uuid": str(uuid.uuid4()),
            "event": row.event,
            "properties": json.dumps(row.properties),
            "timestamp": ts,
            "team_id": team_id,
            "distinct_id": row.user.distinct_id,
            "elements_chain": "",
            "person_id": row.user.person_id,
            "person_properties": "{}",
            "person_created_at": row.user.person_created_at.strftime(CLICKHOUSE_TIMESTAMP_FORMAT),
            "group0_properties": "",
            "group1_properties": "",
            "group2_properties": "",
            "group3_properties": "",
            "group4_properties": "",
            "group0_created_at": ZERO_TIMESTAMP,
            "group1_created_at": ZERO_TIMESTAMP,
            "group2_created_at": ZERO_TIMESTAMP,
            "group3_created_at": ZERO_TIMESTAMP,
            "group4_created_at": ZERO_TIMESTAMP,
            "person_mode": "full",
            "created_at": ts,
            "_timestamp": inserted_at,
        }
        params.update({f"{key}_{i}": value for key, value in row_params.items()})
    sync_execute(BULK_INSERT_EVENT_SQL() + ", ".join(values), params, flush=False)


def seed_task_events(team_id: int, seed_spec: dict[str, Any], now: datetime | None = None) -> dict[str, int]:
    """Materialize a task's seed spec into events in ClickHouse; returns counts per event name."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    days = int(seed_spec["days"])
    streams: list[dict[str, Any]] = seed_spec["streams"]

    # Deterministic per (team, spec), so re-seeding a task universe is reproducible.
    rng = random.Random(f"{team_id}:{json.dumps(seed_spec, sort_keys=True)}")

    total_head_daily = sum(_stream_head_daily(stream, days) for stream in streams)
    population_size = max(MIN_USERS, min(MAX_USERS, int(total_head_daily)))
    users, weights = _build_population(rng, population_size, now - timedelta(days=days))

    rows: list[_SeedEvent] = []
    for stream in streams:
        kind = stream["kind"]
        seeder = _STREAM_SEEDERS.get(kind)
        if seeder is None:
            raise ValueError(f"Unknown seed stream kind: {kind!r}")
        rows.extend(seeder(rng, stream, users, weights, days, now))

    rows.sort(key=lambda row: row.timestamp)
    for start in range(0, len(rows), INSERT_CHUNK_SIZE):
        _insert_chunk(team_id, rows[start : start + INSERT_CHUNK_SIZE], now)

    return dict(Counter(row.event for row in rows))


def clear_task_events(team_id: int) -> None:
    """Delete all events for the task's (dedicated) team from the events data tables."""
    for table in EVENTS_DATA_TABLES:
        sync_execute(
            f"ALTER TABLE {table} DELETE WHERE team_id = %(team_id)s",
            {"team_id": team_id},
            settings={"mutations_sync": 1},
        )
