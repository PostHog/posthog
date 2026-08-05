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
uuid derived from `(run, batch index, subject, payload)`, so an identical resubmission
collapses at ingestion instead of double-firing downstream automation while in-batch
duplicate records still count separately. Events for a batch go out as ONE
`capture_batch_internal` POST, never one HTTP call per record.

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
from referencing import Registry
from referencing.exceptions import NoSuchResource

from posthog.api.capture import capture_batch_internal
from posthog.event_usage import groups
from posthog.models import Team

from products.signals.backend.models import (
    SignalScoutConfig,
    SignalScoutRun,
    SignalScoutStructuredOutput,
    SignalSourceConfig,
)
from products.signals.backend.scout_harness.tools.emit import SOURCE_PRODUCT, SOURCE_TYPE

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


def _refuse_retrieval(uri: str) -> Any:
    """Registry retrieval callback that always fails. The schema is user-controlled, so
    resolving a non-local reference must never turn into the worker fetching an arbitrary
    (possibly internal) URL — an SSRF vector. Local `#/...` refs resolve in-document and
    never reach this; anything else fails closed here as defense-in-depth behind the
    write-time local-refs-only rule."""
    raise NoSuchResource(ref=uri)  # type: ignore[call-arg]


# Explicit no-network resolution for every validator this module builds. `retrieve` is the
# documented keyword; the type stubs don't model the attrs alias, hence the ignore.
_NO_RETRIEVAL_REGISTRY: Registry = Registry(retrieve=_refuse_retrieval)  # type: ignore[call-arg]

# Keys whose value is a reference the validator would try to resolve.
_REFERENCE_KEYS = ("$ref", "$dynamicRef", "$recursiveRef")
# Regex-bearing keywords. Python's `re` backtracks, so a pathological pattern (`^(a+)+$`)
# against a near-matching payload can pin a worker for minutes, and nothing can interrupt a
# match in flight — the size caps bound bytes, not regex time. Measurement records don't
# need regex (enums, types, ranges, required cover the channel), so these fail closed.
_REGEX_KEYWORDS = ("pattern", "patternProperties")
# Keys whose immediate child keys are user-chosen names (e.g. property names), not JSON
# Schema keywords — a property legitimately named `pattern` must not read as the keyword.
_NAME_MAP_KEYS = ("properties", "$defs", "definitions", "dependentSchemas")
# Keys whose value is data, not schema — an example payload may contain a `pattern` key.
_DATA_KEYS = ("default", "const", "enum", "examples")


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
    _assert_supported_constructs(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise StructuredOutputSchemaError(f"structured_output_schema is not a valid JSON Schema: {exc}") from exc
    return schema


def _assert_supported_constructs(node: Any) -> None:
    """Reject schema constructs that would let a schema author attack the validating worker.

    Two families, both walked recursively. Non-fragment `$ref` / `$dynamicRef` /
    `$recursiveRef` would ask the validator to fetch an arbitrary URL at record time
    (SSRF) — only in-document `#...` references are supported, with the no-retrieval
    registry as the fail-closed backstop for schemas that predate this rule. Regex keywords
    (`pattern`, `patternProperties`) are rejected outright: a catastrophic expression pins
    the worker during `iter_errors` and cannot be interrupted (see `_REGEX_KEYWORDS`).
    Name-map containers (`properties`, `$defs`, ...) and data positions (`default`,
    `enum`, ...) are walked without reading their user-chosen keys as keywords."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _DATA_KEYS:
                continue
            if key in _NAME_MAP_KEYS and isinstance(value, dict):
                for subschema in value.values():
                    _assert_supported_constructs(subschema)
                continue
            if key in _REFERENCE_KEYS and isinstance(value, str) and not value.startswith("#"):
                raise StructuredOutputSchemaError(
                    f"structured_output_schema must not use remote references ({key}: {value!r}); "
                    "only in-document '#/...' references are supported"
                )
            if key in _REGEX_KEYWORDS:
                raise StructuredOutputSchemaError(
                    f"structured_output_schema must not use regex keywords ({key}): a pathological "
                    "pattern can stall validation indefinitely. Express the constraint with enum, "
                    "type, length, or numeric bounds instead."
                )
            _assert_supported_constructs(value)
    elif isinstance(node, list):
        for item in node:
            _assert_supported_constructs(item)


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
    _forward_structured_output_events(team=team, run=run, records=records)
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
    # The forward helper does one DB read (`_build_forwards`) plus one blocking batch HTTP
    # POST; `to_thread` keeps both off the event loop without occupying the DB-thread pool
    # for the HTTP leg.
    await asyncio.to_thread(_forward_structured_output_events, team=team, run=run, records=records)
    return result


def _assert_team_owns_run(team: Team, run: SignalScoutRun) -> None:
    """Defense-in-depth mirroring `emit._assert_team_owns_run`: the view path already
    filters the run lookup by team, so a mismatch here is a server-side wiring bug (500,
    not 400)."""
    if team.id != run.team_id:
        raise RuntimeError(f"record_structured_output: team {team.id} does not own run {run.id} (team {run.team_id})")


def _resolve_schema(team: Team, run: SignalScoutRun) -> dict[str, Any]:
    """The schema governing this run's records.

    Two reads, each load-bearing. The run's dispatch-time config is re-read live (by pk,
    mirroring `emit._preflight_emit_gates`): a deleted config or a null schema fails closed —
    the channel is opt-in via the schema's presence, and a schema *cleared* mid-run is the
    kill switch that must stop further writes. But the schema records validate against is
    the dispatch-time snapshot the runner stamped on the run row (when present): the prompt
    rendered that exact schema, so a mid-run schema *edit* must not reject records that
    match what the run was shown, nor silently persist records under a contract the scout
    never saw. Runs predating the stamp fall back to the live value."""
    row = SignalScoutRun.all_teams.filter(pk=run.pk, team_id=team.id).values_list("scout_config_id", "metadata").first()
    config_id, metadata = row if row else (None, None)
    config = SignalScoutConfig.all_teams.filter(pk=config_id).first() if config_id else None
    live_schema = config.structured_output_schema if config else None
    if not live_schema:
        raise _no_schema_error()
    snapshot = (metadata or {}).get("structured_output_schema")
    return snapshot if isinstance(snapshot, dict) and snapshot else live_schema


def _no_schema_error() -> InvalidStructuredOutputError:
    return InvalidStructuredOutputError(
        "This scout has no structured_output_schema configured, so structured output cannot be "
        "recorded. Set a schema on the scout's config (scout-config-update) to enable this channel."
    )


def _validate_records(records: list[StructuredOutputRecord], schema: dict[str, Any]) -> None:
    if not records:
        raise InvalidStructuredOutputError("records must not be empty")
    if len(records) > MAX_RECORDS_PER_CALL:
        raise InvalidStructuredOutputError(
            f"records has {len(records)} entries, max is {MAX_RECORDS_PER_CALL} per call"
        )
    try:
        validator = Draft202012Validator(schema, registry=_NO_RETRIEVAL_REGISTRY)
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
        try:
            error = next(iter(validator.iter_errors(record.payload)), None)
        except Exception as exc:
            # A reference the no-retrieval registry refused (or any other resolution failure)
            # is a config problem, not a record problem — fail the call closed with the reason.
            raise InvalidStructuredOutputError(
                f"The configured structured_output_schema could not be evaluated ({exc}). "
                "Ask the scout's owner to fix it via scout-config-update."
            ) from exc
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
    unscoped manager because ownership was already validated by the caller.

    The kill switch is re-checked here with the config row locked: `_resolve_schema`'s
    earlier read and this insert are separate operations, so without this a clear
    committing between them would let rows land after the channel was switched off. The
    lock serializes a concurrent clear against the insert — whichever commits first wins
    cleanly."""
    with transaction.atomic():
        locked_run = SignalScoutRun.all_teams.select_for_update(of=("self",)).filter(pk=run.pk).first()
        if locked_run is None:
            raise InvalidStructuredOutputError("The run row is gone; nothing was recorded.")
        live_schema = (
            SignalScoutConfig.all_teams.select_for_update()
            .filter(pk=locked_run.scout_config_id)
            .values_list("structured_output_schema", flat=True)
            .first()
            if locked_run.scout_config_id
            else None
        )
        if not live_schema:
            raise _no_schema_error()
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
    # Same inactive-skip rule as the emit/report channels: a project that disabled the
    # signals_scout source has opted out of scout output, so no customer-facing,
    # automation-driving event may fire — rows still persist as internal run data.
    if not SignalSourceConfig.is_source_enabled(run.team_id, SOURCE_PRODUCT, SOURCE_TYPE):
        return []
    forwards: list[_StructuredOutputForward] = []
    base = {
        "skill_name": run.skill_name,
        "skill_version": run.skill_version,
        "run_id": str(run.id),
        "task_run_id": str(run.task_run_id) if run.task_run_id else None,
    }
    for index, record in enumerate(records):
        flattened = {
            f"output_{key}": value
            for key, value in record.payload.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
        payload_key = json.dumps(record.payload, sort_keys=True, separators=(",", ":"))
        forwards.append(
            _StructuredOutputForward(
                distinct_id=f"signals_scout:{run.skill_name}",
                # `index` keeps in-batch duplicates (two records with identical subject +
                # payload that are meant to count separately) as distinct events, while a
                # resubmitted identical batch — same records at the same positions — still
                # collapses at ingestion instead of double-firing downstream automation.
                event_uuid=str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        "signals_scout_structured_output:"
                        + json.dumps(
                            [str(run.id), str(index), record.subject or "", payload_key], separators=(",", ":")
                        ),
                    )
                ),
                properties={**base, "subject": record.subject, "output": record.payload, **flattened},
            )
        )
    return forwards


def _forward_structured_output_events(
    *, team: Team, run: SignalScoutRun, records: list[StructuredOutputRecord]
) -> None:
    """Mirror the accepted batch into the team's own event stream through the sanctioned
    `capture_batch_internal` path — one batch POST (auto-chunked with bounded concurrency
    above 200 events), never one HTTP call per record, so a slow capture endpoint costs one
    bounded round-trip instead of a timeout per record after the rows already committed.
    Person processing is OFF with a synthetic per-scout `distinct_id` — a record is the
    scout's output, not an end-user action. Best-effort: a forward failure must never fail
    the record call (the rows are the durable record either way)."""
    forwards = _build_forwards(team=team, run=run, records=records)
    if not forwards:
        return
    try:
        capture_batch_internal(
            events=[
                {
                    "event": CUSTOMER_STRUCTURED_OUTPUT_EVENT,
                    "distinct_id": forward.distinct_id,
                    "properties": forward.properties,
                    "event_uuid": forward.event_uuid,
                }
                for forward in forwards
            ],
            token=team.api_token,
            event_source=_STRUCTURED_OUTPUT_EVENT_SOURCE,
            process_person_profile=False,
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to forward structured-output events to team project",
            extra={"team_id": team.id, "run_id": str(run.id), "event_count": len(forwards)},
        )
