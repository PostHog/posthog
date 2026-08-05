"""Structured-output adapter: schema-validated records a scout submits during a run.

The third output channel, next to signals (`emit.py`) and reports (`report.py`). A scout
whose job is a recurring *measurement* — judging, scoring, classifying entities on a
schedule — produces data, not prose: its output only becomes useful when it can be
filtered and charted per record. This channel gives that shape a contract: the scout's
`SignalScoutConfig.structured_output_schema` (a JSON Schema describing ONE record) is the
opt-in, every submitted record is validated against it, and each accepted record lands in
two places:

- a `SignalScoutStructuredOutput` row (Postgres, queryable via the `scout-*` MCP tools),
- a customer-facing `$scout_structured_output` event in the team's own project (via
  `capture_internal`), so the records are chartable in PostHog — trend a `verdict`
  breakdown, alert on a rate — with no export step.

Validation is all-or-nothing per call: if any record fails the schema, nothing is written
and the error names the failing records, so the agent can fix and resubmit the batch
without deduping a partial write. Accepted calls are NOT idempotent at the row layer (a
resubmitted batch writes new rows), but the customer-facing events carry a deterministic
uuid derived from `(run, subject, payload)`, so an identical resubmission collapses at
ingestion instead of double-firing downstream automation.

Cardinality is deliberately the scout's call, not a config mode: the schema describes one
record, and the scout may submit one per run, one per judged entity, or a batch per call
(`MAX_RECORDS_PER_CALL`), bounded per run by `MAX_RECORDS_PER_RUN`.
"""

from __future__ import annotations

import json
import uuid
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from django.db import transaction

import posthoganalytics
from jsonschema import Draft202012Validator

from posthog.api.capture import capture_internal
from posthog.event_usage import groups
from posthog.models import Team

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun, SignalScoutStructuredOutput

logger = logging.getLogger(__name__)

# Per-call batch bound: large enough for "judge 100 sampled entities" in one call, small
# enough that a single request body stays well-bounded.
MAX_RECORDS_PER_CALL = 100
# Per-run ceiling across calls — a circuit breaker against a looping agent flooding the
# table, far above any sane per-run record count.
MAX_RECORDS_PER_RUN = 1000
# Serialized size cap per record. Records are data points, not documents; a judgment with
# a reason fits in a fraction of this.
MAX_RECORD_BYTES = 16_384
# Mirrors the `subject` column width on `SignalScoutStructuredOutput`.
MAX_SUBJECT_LENGTH = 200
# Serialized size cap on the configured schema, enforced by the config serializers. Kept
# here so the schema validator and the write path agree on one constant.
MAX_SCHEMA_BYTES = 20_000

# Customer-facing per-record event (see `tools/report.py` for the `$`-prefix convention:
# a PostHog-generated event kept out of the customer's own custom-event namespace).
CUSTOMER_STRUCTURED_OUTPUT_EVENT = "$scout_structured_output"
_STRUCTURED_OUTPUT_EVENT_SOURCE = "signals_scout_structured_output"


class InvalidStructuredOutputError(ValueError):
    """The submission is malformed: no schema configured, batch/record caps exceeded, or a
    record failed validation against the configured schema."""


class StructuredOutputSchemaError(ValueError):
    """The supplied JSON Schema itself is invalid (raised at config-write time)."""


@dataclass(frozen=True, kw_only=True)
class StructuredOutputRecord:
    """One record the agent submits: the schema-validated `payload` plus an optional
    `subject` naming what the record is about (a report id, URL, account key, ...)."""

    payload: dict[str, Any]
    subject: str | None = None


@dataclass(frozen=True, kw_only=True)
class RecordStructuredOutputResult:
    """Outcome of an accepted `record_structured_output` call — validation failures raise
    `InvalidStructuredOutputError` instead, so an instance always means rows were written."""

    recorded_count: int
    record_ids: list[str]


def validate_structured_output_schema(schema: Any) -> dict[str, Any]:
    """Validate a user-supplied JSON Schema for the config field and return it.

    Called by the config serializers at write time so a broken schema is rejected at the
    boundary rather than failing every run's record call. Requires a JSON object rooted at
    `"type": "object"` — the record endpoint stores dict payloads, and an object root is
    what keeps each record breakdown-friendly downstream — and bounds serialized size so
    the schema stays a cheap per-record validation, not a document."""
    if not isinstance(schema, dict) or not schema:
        raise StructuredOutputSchemaError("structured_output_schema must be a non-empty JSON object")
    if schema.get("type") != "object":
        raise StructuredOutputSchemaError('structured_output_schema must declare "type": "object" at its root')
    encoded = json.dumps(schema)
    if len(encoded.encode("utf-8")) > MAX_SCHEMA_BYTES:
        raise StructuredOutputSchemaError(f"structured_output_schema exceeds {MAX_SCHEMA_BYTES} bytes serialized")
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise StructuredOutputSchemaError(f"structured_output_schema is not a valid JSON Schema: {exc}") from exc
    return schema


def record_structured_output_sync(
    *,
    team: Team,
    run: SignalScoutRun,
    records: list[StructuredOutputRecord],
) -> RecordStructuredOutputResult:
    """Validate `records` against the run's configured schema and persist them.

    All-or-nothing: any invalid record fails the whole call with nothing written, so the
    agent never has to dedupe a partial batch. Rows are written in one transaction; the
    per-record customer-facing events and the internal telemetry event are fired
    best-effort after commit and never fail the call.
    """
    _assert_team_owns_run(team, run)
    schema = _resolve_schema(team, run)
    _validate_records(records, schema)

    rows = _write_rows(team=team, run=run, records=records)
    result = RecordStructuredOutputResult(
        recorded_count=len(rows),
        record_ids=[str(row.id) for row in rows],
    )
    _capture_recorded(team=team, run=run, recorded_count=len(rows))
    forwards = _build_forwards(team=team, run=run, records=records)
    for forward in forwards:
        _forward_structured_output_event(team=team, forward=forward)
    return result


async def record_structured_output(
    *,
    team: Team,
    run: SignalScoutRun,
    records: list[StructuredOutputRecord],
) -> RecordStructuredOutputResult:
    """Async entry mirroring `record_structured_output_sync`, offloading DB writes to the
    sync thread pool and the blocking event forwards to a worker thread."""
    from posthog.sync import database_sync_to_async

    _assert_team_owns_run(team, run)
    schema = await database_sync_to_async(_resolve_schema, thread_sensitive=False)(team, run)
    _validate_records(records, schema)
    rows = await database_sync_to_async(_write_rows, thread_sensitive=False)(team=team, run=run, records=records)
    result = RecordStructuredOutputResult(
        recorded_count=len(rows),
        record_ids=[str(row.id) for row in rows],
    )
    await database_sync_to_async(_capture_recorded, thread_sensitive=False)(
        team=team, run=run, recorded_count=len(rows)
    )
    forwards = await database_sync_to_async(_build_forwards, thread_sensitive=False)(
        team=team, run=run, records=records
    )
    for forward in forwards:
        await asyncio.to_thread(_forward_structured_output_event, team=team, forward=forward)
    return result


def _assert_team_owns_run(team: Team, run: SignalScoutRun) -> None:
    """Defense-in-depth mirroring `emit._assert_team_owns_run`: the view path already
    filters the run lookup by team, so a mismatch here is a server-side wiring bug (500,
    not 400)."""
    if team.id != run.team_id:
        raise RuntimeError(f"record_structured_output: team {team.id} does not own run {run.id} (team {run.team_id})")


def _resolve_schema(team: Team, run: SignalScoutRun) -> dict[str, Any]:
    """The schema governing this run's records, re-read live from the run's dispatch-time
    config (by pk, mirroring `emit._preflight_emit_gates`): a deleted config or a null
    schema fails closed — the channel is opt-in via the schema's presence, and a schema
    removed mid-run must stop further writes."""
    config_id = (
        SignalScoutRun.all_teams.filter(pk=run.pk, team_id=team.id).values_list("scout_config_id", flat=True).first()
    )
    config = SignalScoutConfig.all_teams.filter(pk=config_id).first() if config_id else None
    schema = config.structured_output_schema if config else None
    if not schema:
        raise InvalidStructuredOutputError(
            "This scout has no structured_output_schema configured, so structured output cannot be "
            "recorded. Set a schema on the scout's config (scout-config-update) to enable this channel."
        )
    return schema


def _validate_records(records: list[StructuredOutputRecord], schema: dict[str, Any]) -> None:
    if not records:
        raise InvalidStructuredOutputError("records must not be empty")
    if len(records) > MAX_RECORDS_PER_CALL:
        raise InvalidStructuredOutputError(
            f"records has {len(records)} entries, max is {MAX_RECORDS_PER_CALL} per call"
        )
    try:
        validator = Draft202012Validator(schema)
    except Exception as exc:
        # The serializer validates schemas at write time, so this only fires for rows that
        # predate the guard or were written outside the API. The agent can't fix it; the
        # config owner can.
        raise InvalidStructuredOutputError(
            f"The configured structured_output_schema is not a valid JSON Schema ({exc}). "
            "Ask the scout's owner to fix it via scout-config-update."
        ) from exc
    problems: list[str] = []
    for index, record in enumerate(records):
        if record.subject is not None and len(record.subject) > MAX_SUBJECT_LENGTH:
            problems.append(f"records[{index}].subject exceeds {MAX_SUBJECT_LENGTH} chars")
            continue
        encoded = json.dumps(record.payload)
        if len(encoded.encode("utf-8")) > MAX_RECORD_BYTES:
            problems.append(f"records[{index}].payload exceeds {MAX_RECORD_BYTES} bytes serialized")
            continue
        error = next(iter(validator.iter_errors(record.payload)), None)
        if error is not None:
            path = "".join(f"[{part!r}]" for part in error.absolute_path)
            problems.append(f"records[{index}].payload{path}: {error.message}")
    if problems:
        shown = problems[:5]
        suffix = f" (+{len(problems) - len(shown)} more)" if len(problems) > len(shown) else ""
        raise InvalidStructuredOutputError(
            f"{len(problems)} of {len(records)} records failed schema validation; nothing was recorded. "
            + "; ".join(shown)
            + suffix
        )


def _write_rows(
    *, team: Team, run: SignalScoutRun, records: list[StructuredOutputRecord]
) -> list[SignalScoutStructuredOutput]:
    """Persist the batch in one transaction, enforcing the per-run ceiling under the same
    lock the row count is read at so concurrent calls can't overshoot it. Uses the
    unscoped manager because ownership was already validated by the caller."""
    with transaction.atomic():
        locked_run = SignalScoutRun.all_teams.select_for_update(of=("self",)).filter(pk=run.pk).first()
        if locked_run is None:
            raise InvalidStructuredOutputError("The run row is gone; nothing was recorded.")
        existing = SignalScoutStructuredOutput.all_teams.filter(scout_run_id=run.pk).count()
        if existing + len(records) > MAX_RECORDS_PER_RUN:
            raise InvalidStructuredOutputError(
                f"Recording {len(records)} more records would exceed the per-run cap of "
                f"{MAX_RECORDS_PER_RUN} (already recorded: {existing})."
            )
        return SignalScoutStructuredOutput.all_teams.bulk_create(
            SignalScoutStructuredOutput(
                team_id=run.team_id,
                scout_run_id=run.pk,
                skill_name=run.skill_name,
                subject=record.subject or "",
                payload=record.payload,
            )
            for record in records
        )


def _capture_recorded(*, team: Team, run: SignalScoutRun, recorded_count: int) -> None:
    """Internal (PostHog-side) telemetry: one event per accepted call, mirroring the
    other scout lifecycle events' shape so it joins on `run_id`. Best-effort."""
    try:
        posthoganalytics.capture(
            event="signals_scout_structured_output_recorded",
            distinct_id=str(team.uuid),
            properties={
                "skill_name": run.skill_name,
                "skill_version": run.skill_version,
                "scout_config_id": str(run.scout_config_id) if run.scout_config_id else None,
                "run_id": str(run.id),
                "task_run_id": str(run.task_run_id) if run.task_run_id else None,
                "recorded_count": recorded_count,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to capture structured-output analytics event",
            extra={"team_id": team.id, "run_id": str(run.id), "skill_name": run.skill_name},
        )


@dataclass(frozen=True, kw_only=True)
class _StructuredOutputForward:
    distinct_id: str
    event_uuid: str
    properties: dict[str, Any]


def _build_forwards(
    *, team: Team, run: SignalScoutRun, records: list[StructuredOutputRecord]
) -> list[_StructuredOutputForward]:
    """One customer-facing event per record, into the team's own project. Scalar top-level
    payload keys are flattened to `output_<key>` properties so trends can break down on
    them directly (nested access works too; the flat copy is the ergonomic path), and the
    full record rides under `output`. Suppressed entirely for a dry-run scout
    (`config.emit=False`): rows still record — that's how a scout is validated — but a
    dry-run must not drive customer-visible automation, matching the report channel's
    inactive-skip rule."""
    config = SignalScoutConfig.all_teams.filter(pk=run.scout_config_id).first() if run.scout_config_id else None
    if config is None or not config.emit:
        return []
    forwards: list[_StructuredOutputForward] = []
    base = {
        "skill_name": run.skill_name,
        "skill_version": run.skill_version,
        "run_id": str(run.id),
        "task_run_id": str(run.task_run_id) if run.task_run_id else None,
    }
    for record in records:
        flattened = {
            f"output_{key}": value
            for key, value in record.payload.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
        payload_key = json.dumps(record.payload, sort_keys=True, separators=(",", ":"))
        forwards.append(
            _StructuredOutputForward(
                distinct_id=f"signals_scout:{run.skill_name}",
                event_uuid=str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        "signals_scout_structured_output:"
                        + json.dumps([str(run.id), record.subject or "", payload_key], separators=(",", ":")),
                    )
                ),
                properties={**base, "subject": record.subject, "output": record.payload, **flattened},
            )
        )
    return forwards


def _forward_structured_output_event(*, team: Team, forward: _StructuredOutputForward) -> None:
    """Mirror one record into the team's own event stream through the sanctioned
    `capture_internal` path. Person processing is OFF with a synthetic per-scout
    `distinct_id` — a record is the scout's output, not an end-user action. Best-effort:
    a forward failure must never fail the record call (the rows already committed)."""
    try:
        capture_internal(
            token=team.api_token,
            event_name=CUSTOMER_STRUCTURED_OUTPUT_EVENT,
            event_source=_STRUCTURED_OUTPUT_EVENT_SOURCE,
            distinct_id=forward.distinct_id,
            properties=forward.properties,
            event_uuid=forward.event_uuid,
            process_person_profile=False,
        ).raise_for_status()
    except Exception:
        logger.warning(
            "signals_scout: failed to forward structured-output event to team project",
            extra={"team_id": team.id, "distinct_id": forward.distinct_id},
        )
