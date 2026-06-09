"""Emit adapter: agent-authored findings -> emit_signal() with attribution baked in.

Each finding is forwarded to `emit_signal` with a deterministic `source_id`:
`f"run:{run.id}:finding:{finding_id}"`. This is for traceability only — it is NOT
an idempotency barrier. The downstream pipeline assigns every signal a fresh random
`document_id` and dedupes on that, never on `source_id` (which it only stores in
metadata), so a re-call with the same `finding_id` emits a *second* signal.

Post-success we bump a scout-side tally on the run row (`emitted_count` +
`emitted_finding_ids` via `_record_emit`) so "did this run surface anything?" is a
column lookup rather than a prose-`summary` parse or a ClickHouse scan. The tally write
is best-effort: a failure to record it never propagates out of the emit, because the
signal has already fired and the caller must not be told the emit failed. It is
observability only, NOT a dedupe layer — there is no scout-side idempotency, so callers
must not retry an emit that may have already succeeded; a retry double-counts here
exactly as it double-emits downstream.

Attribution (`scout_run_id`, `task_run_id`, `finding_id`, `skill_name`, `skill_version`)
is read off the run row so the agent never has to plumb it through. `task_run_id` is the
join key into the `signals_scouts_runs` LLM-analytics view (the `scout_run_id` bridge row
is not on that view). The `SignalsScoutSignalExtra`
shape (defined in `posthog.schema`) is what the existing `_SIGNAL_VARIANT_LOOKUP`
in `products/signals/backend/api.py` validates against.
"""

from __future__ import annotations

import uuid
import logging
from dataclasses import asdict, dataclass
from typing import Any

from django.db import transaction

from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun, SignalSourceConfig

logger = logging.getLogger(__name__)

SOURCE_PRODUCT = SignalSourceConfig.SourceProduct.SIGNALS_SCOUT.value
SOURCE_TYPE = SignalSourceConfig.SourceType.CROSS_SOURCE_ISSUE.value

# Defensive cap on evidence list length — the agent shouldn't ship hundreds of
# citations per finding. The pydantic schema accepts any length; this is a harness
# circuit breaker.
MAX_EVIDENCE_ENTRIES = 20


class InvalidEmitError(ValueError):
    """The agent tried to emit with an invalid shape (empty description, bad weight, etc)."""


@dataclass(frozen=True)
class EvidenceEntry:
    """One citation the agent attaches to a finding. Mirrors `SignalsScoutEvidenceEntry`."""

    source_product: str
    summary: str
    entity_id: str | None = None


@dataclass(frozen=True)
class EmitResult:
    """Outcome of an emit_finding call.

    `skipped_reason` is set when a preflight gate prevented the external emit;
    None means the call reached `emit_signal`. There is no dedupe — a repeat call
    with the same `finding_id` emits a second signal (see the module docstring).

    Possible `skipped_reason` values:
      - None: emit fired
      - "scout_config_missing": the run's dispatch-time config FK is null/gone — fail closed
      - "scout_emit_disabled": the scout's config has emit=False (dry-run)
      - "ai_processing_not_approved": team's organization has not approved AI processing
      - "source_disabled": SignalSourceConfig disables the signals_scout source for this team
    """

    finding_id: str
    emitted: bool
    skipped_reason: str | None


async def emit_finding(
    *,
    team: Team,
    run: SignalScoutRun,
    description: str,
    weight: float,
    confidence: float,
    evidence: list[EvidenceEntry],
    hypothesis: str | None = None,
    severity: str | None = None,
    dedupe_keys: list[str] | None = None,
    time_range: tuple[str, str] | None = None,
    mcp_trace_id: str | None = None,
    finding_id: str | None = None,
) -> EmitResult:
    """Async entry: route DB calls through `database_sync_to_async` so async callers
    (the harness runner inside Temporal) don't block the event loop.

    Same (non-idempotent) emit behavior as `emit_finding_sync`.
    """
    _assert_team_owns_run(team, run)
    _validate_inputs(description, weight, confidence, evidence)
    finding_id = finding_id or _new_finding_id()
    extra = _build_extra(
        run_id=str(run.id),
        task_run_id=str(run.task_run_id),
        finding_id=finding_id,
        skill_name=run.skill_name,
        skill_version=run.skill_version,
        confidence=confidence,
        evidence=evidence,
        hypothesis=hypothesis,
        severity=severity,
        dedupe_keys=dedupe_keys,
        time_range=time_range,
        mcp_trace_id=mcp_trace_id,
    )
    attempt_extra = _log_extra(
        team_id=team.id,
        run_id=str(run.id),
        finding_id=finding_id,
        skill_name=run.skill_name,
        skill_version=run.skill_version,
        weight=weight,
        confidence=confidence,
        severity=severity,
        evidence_count=len(evidence),
    )
    logger.info("signals_scout.emit: attempt", extra=attempt_extra)

    preflight = await database_sync_to_async(_preflight_emit_gates, thread_sensitive=False)(team, run)
    if preflight is not None:
        logger.warning(
            "signals_scout.emit: skipped %s",
            preflight,
            extra={**attempt_extra, "skipped_reason": preflight},
        )
        return EmitResult(finding_id=finding_id, emitted=False, skipped_reason=preflight)

    # Deferred to keep the harness module import lightweight — emitting is an opt-in path here.
    from products.signals.backend.facade.api import emit_signal

    source_id = f"run:{run.id}:finding:{finding_id}"
    await emit_signal(
        team=team,
        source_product=SOURCE_PRODUCT,
        source_type=SOURCE_TYPE,
        source_id=source_id,
        description=description,
        weight=weight,
        extra=extra,
    )
    await database_sync_to_async(_record_emit, thread_sensitive=False)(run_id=run.id, finding_id=finding_id)
    logger.info(
        "signals_scout.emit: emitted",
        extra={**attempt_extra, "source_id": source_id},
    )
    return EmitResult(finding_id=finding_id, emitted=True, skipped_reason=None)


def emit_finding_sync(
    *,
    team: Team,
    run: SignalScoutRun,
    description: str,
    weight: float,
    confidence: float,
    evidence: list[EvidenceEntry],
    hypothesis: str | None = None,
    severity: str | None = None,
    dedupe_keys: list[str] | None = None,
    time_range: tuple[str, str] | None = None,
    mcp_trace_id: str | None = None,
    finding_id: str | None = None,
) -> EmitResult:
    """Sync entry used by the DRF view path.

    `time_range` is a `(date_from, date_to)` tuple; the harness normalizes it into
    the `{"date_from", "date_to"}` shape that `SignalsScoutSignalExtra` expects.
    """
    from asgiref.sync import async_to_sync

    _assert_team_owns_run(team, run)
    _validate_inputs(description, weight, confidence, evidence)
    finding_id = finding_id or _new_finding_id()
    extra = _build_extra(
        run_id=str(run.id),
        task_run_id=str(run.task_run_id),
        finding_id=finding_id,
        skill_name=run.skill_name,
        skill_version=run.skill_version,
        confidence=confidence,
        evidence=evidence,
        hypothesis=hypothesis,
        severity=severity,
        dedupe_keys=dedupe_keys,
        time_range=time_range,
        mcp_trace_id=mcp_trace_id,
    )
    attempt_extra = _log_extra(
        team_id=team.id,
        run_id=str(run.id),
        finding_id=finding_id,
        skill_name=run.skill_name,
        skill_version=run.skill_version,
        weight=weight,
        confidence=confidence,
        severity=severity,
        evidence_count=len(evidence),
    )
    logger.info("signals_scout.emit: attempt", extra=attempt_extra)

    preflight = _preflight_emit_gates(team, run)
    if preflight is not None:
        logger.warning(
            "signals_scout.emit: skipped %s",
            preflight,
            extra={**attempt_extra, "skipped_reason": preflight},
        )
        return EmitResult(finding_id=finding_id, emitted=False, skipped_reason=preflight)

    from products.signals.backend.facade.api import emit_signal

    source_id = f"run:{run.id}:finding:{finding_id}"
    async_to_sync(emit_signal)(
        team=team,
        source_product=SOURCE_PRODUCT,
        source_type=SOURCE_TYPE,
        source_id=source_id,
        description=description,
        weight=weight,
        extra=extra,
    )
    _record_emit(run_id=run.id, finding_id=finding_id)
    logger.info(
        "signals_scout.emit: emitted",
        extra={**attempt_extra, "source_id": source_id},
    )
    return EmitResult(finding_id=finding_id, emitted=True, skipped_reason=None)


def _assert_team_owns_run(team: Team, run: SignalScoutRun) -> None:
    """Defense-in-depth: confirm `team` actually owns `run`.

    The view path (`SignalScoutRunViewSet.emit_signal`) already filters the run
    lookup by `team_id`, so a foreign-team `run_id` returns 404 before this
    function is reached. This guard catches a future direct caller (in-process
    MCP path, management command, ...) that bypasses that filter, rather than
    relying on every caller to pre-validate the (team, run) pair.

    Raises `RuntimeError` (not `InvalidEmitError`) because a mismatch here is a
    server-side wiring bug, not a user-input shape issue — we want a 500, not
    a 400.
    """
    if team.id != run.team_id:
        raise RuntimeError(f"emit_finding: team {team.id} does not own run {run.id} (team {run.team_id})")


def _validate_inputs(
    description: str,
    weight: float,
    confidence: float,
    evidence: list[EvidenceEntry],
) -> None:
    if not description or not description.strip():
        raise InvalidEmitError("description must not be empty")
    if not 0.0 <= weight <= 1.0:
        raise InvalidEmitError(f"weight must be in [0.0, 1.0], got {weight}")
    if not 0.0 <= confidence <= 1.0:
        raise InvalidEmitError(f"confidence must be in [0.0, 1.0], got {confidence}")
    if len(evidence) > MAX_EVIDENCE_ENTRIES:
        raise InvalidEmitError(f"evidence has {len(evidence)} entries, max is {MAX_EVIDENCE_ENTRIES}")


def _build_extra(
    *,
    run_id: str,
    task_run_id: str,
    finding_id: str,
    skill_name: str,
    skill_version: int,
    confidence: float,
    evidence: list[EvidenceEntry],
    hypothesis: str | None,
    severity: str | None,
    dedupe_keys: list[str] | None,
    time_range: tuple[str, str] | None,
    mcp_trace_id: str | None,
) -> dict[str, Any]:
    """Shape the extra payload to match `SignalsScoutSignalExtra` (extra='forbid'),
    omitting optional fields when not provided so pydantic doesn't see a `None` for
    fields that don't accept it."""
    extra: dict[str, Any] = {
        "scout_run_id": run_id,
        "task_run_id": task_run_id,
        "finding_id": finding_id,
        "skill_name": skill_name,
        "skill_version": float(skill_version),
        "confidence": confidence,
        "evidence": [asdict(e) for e in evidence],
    }
    if hypothesis is not None:
        extra["hypothesis"] = hypothesis
    if severity is not None:
        extra["severity"] = severity
    if dedupe_keys is not None:
        extra["dedupe_keys"] = list(dedupe_keys)
    if time_range is not None:
        extra["time_range"] = {"date_from": time_range[0], "date_to": time_range[1]}
    if mcp_trace_id is not None:
        extra["mcp_trace_id"] = mcp_trace_id
    return extra


def _new_finding_id() -> str:
    return str(uuid.uuid4())


def _record_emit(*, run_id: Any, finding_id: str) -> None:
    """Bump the run's post-success emit tally: append `finding_id` and recount.

    Best-effort and observability only — not a dedupe barrier (see the module docstring).
    The emit has already fired by the time this runs, so **any** failure here (row gone,
    lock timeout, transient DB error) is swallowed: surfacing it would make a succeeded
    emit look failed and invite a double-emitting retry. Runs under `select_for_update` so
    the read-modify-write on `emitted_finding_ids` is safe even though emits within a single
    run are sequential today, and keeps `emitted_count` exactly `len(emitted_finding_ids)`
    so the two never drift. Uses the unscoped `all_teams` manager because the caller already
    validated `team`/`run` ownership and emit can run with no team scope set (Temporal
    activity)."""
    try:
        with transaction.atomic():
            run = SignalScoutRun.all_teams.select_for_update().filter(pk=run_id).first()
            if run is None:
                logger.warning("signals_scout.emit: run %s gone, skipping emit tally", run_id)
                return
            finding_ids = [*(run.emitted_finding_ids or []), finding_id]
            run.emitted_finding_ids = finding_ids
            run.emitted_count = len(finding_ids)
            run.save(update_fields=["emitted_finding_ids", "emitted_count"])
    except Exception:
        # Tally is best-effort; the signal already emitted. Log and move on so the emit
        # call returns success rather than a false failure the caller might retry.
        logger.exception("signals_scout.emit: failed to record emit tally for run %s", run_id)


def _log_extra(
    *,
    team_id: int,
    run_id: str,
    finding_id: str,
    skill_name: str,
    skill_version: int,
    weight: float,
    confidence: float,
    severity: str | None,
    evidence_count: int,
) -> dict[str, Any]:
    """Structured log fields for emit-lifecycle events. Description text is
    deliberately omitted — it can carry customer-derived strings."""
    return {
        "team_id": team_id,
        "run_id": run_id,
        "finding_id": finding_id,
        "skill_name": skill_name,
        "skill_version": skill_version,
        "weight": weight,
        "confidence": confidence,
        "severity": severity,
        "evidence_count": evidence_count,
    }


def _preflight_emit_gates(team: Team, run: SignalScoutRun) -> str | None:
    """Return the matching skipped_reason if a gate would drop the emit; else None.

    `emit_signal()` returns silently when the team's organization has not approved
    AI processing or when `SignalSourceConfig.is_source_enabled(...)` is False.
    Surfacing the gate result here lets the view return a useful skipped_reason
    instead of "emitted" for an emit the pipeline silently dropped. The per-scout
    `emit` toggle is checked first: a dry-run scout runs and logs but emits nothing.

    Anchored on the run's own config FK, re-read live from the DB (not the in-memory `run`,
    which may be stale, and not re-resolved by `skill_name`). `scout_config` is `SET_NULL`,
    so if the config the run was dispatched with is deleted mid-run the FK goes NULL and we
    fail closed — even if a same-`(team, skill_name)` config was recreated in the meantime. A
    stale run must emit only against the config it was dispatched with. This keeps the gate
    fail-closed independent of the `emit` default (now `True`); re-reading the row by pk still
    honors a mid-run `emit` flip on that same config.
    """
    config_id = (
        SignalScoutRun.all_teams.filter(pk=run.pk, team_id=team.id).values_list("scout_config_id", flat=True).first()
    )
    if config_id is None:
        return "scout_config_missing"
    config = SignalScoutConfig.all_teams.filter(pk=config_id).first()
    if config is None:
        return "scout_config_missing"
    if not config.emit:
        return "scout_emit_disabled"
    organization = team.organization
    if not organization.is_ai_data_processing_approved:
        return "ai_processing_not_approved"
    if not SignalSourceConfig.is_source_enabled(team.id, SOURCE_PRODUCT, SOURCE_TYPE):
        return "source_disabled"
    return None
