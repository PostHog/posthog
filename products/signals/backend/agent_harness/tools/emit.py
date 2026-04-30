"""Emit adapter: agent-authored findings -> emit_signal() with attribution baked in.

The harness owns idempotency. Each finding is recorded on `SignalAgentRun.findings`
under `select_for_update` *before* the external `emit_signal` call, then marked
`emitted=True` post-success. A re-call with the same `finding_id` short-circuits
without firing the pipeline a second time. Shadow-mode runs persist findings to the
run row but do not fire the external emit.

Attribution (`agent_run_id`, `finding_id`, `skill_name`, `skill_version`) is read
off the run row so the agent never has to plumb it through. The `SignalsAgentSignalExtra`
shape (defined in `posthog.schema`) is what the existing `_SIGNAL_VARIANT_LOOKUP`
in `products/signals/backend/api.py` validates against.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalAgentRun

SOURCE_PRODUCT = "signals_agent"
SOURCE_TYPE = "cross_source_issue"

# Defensive cap on evidence list length — the agent shouldn't ship hundreds of
# citations per finding. The pydantic schema accepts any length; this is a harness
# circuit breaker.
MAX_EVIDENCE_ENTRIES = 20


class InvalidEmitError(ValueError):
    """The agent tried to emit with an invalid shape (empty description, bad weight, etc)."""


@dataclass(frozen=True)
class EvidenceEntry:
    """One citation the agent attaches to a finding. Mirrors `SignalsAgentEvidenceEntry`."""

    source_product: str
    summary: str
    entity_id: str | None = None


@dataclass(frozen=True)
class EmitResult:
    """Outcome of an emit_finding call. `skipped_reason` distinguishes idempotent
    no-ops from actual emits — useful for the runner's run-row finalization."""

    finding_id: str
    emitted: bool
    skipped_reason: str | None  # "shadow_mode" | "already_emitted" | None


async def emit_finding(
    *,
    team: Team,
    run: SignalAgentRun,
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
    shadow_mode: bool = False,
) -> EmitResult:
    """Async entry: route DB calls through `database_sync_to_async` so async callers
    (the harness runner inside Temporal) don't block the event loop.

    Same idempotency + shadow-mode semantics as `emit_finding_sync` — see that
    function's docstring for the contract.
    """
    _validate_inputs(description, weight, confidence, evidence)
    finding_id = finding_id or _new_finding_id()
    extra = _build_extra(
        run_id=str(run.id),
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

    already_emitted = await database_sync_to_async(_record_finding_pre_emit, thread_sensitive=False)(
        run_id=str(run.id),
        finding_id=finding_id,
        description=description,
        weight=weight,
        extra=extra,
    )
    if already_emitted:
        return EmitResult(finding_id=finding_id, emitted=True, skipped_reason="already_emitted")

    if shadow_mode:
        return EmitResult(finding_id=finding_id, emitted=False, skipped_reason="shadow_mode")

    # Defer the import: products.signals.backend.api transitively imports temporal
    # workflows, which we don't want loaded at module import time inside the harness.
    from products.signals.backend.api import emit_signal

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

    await database_sync_to_async(_mark_finding_emitted, thread_sensitive=False)(
        run_id=str(run.id), finding_id=finding_id
    )
    return EmitResult(finding_id=finding_id, emitted=True, skipped_reason=None)


def emit_finding_sync(
    *,
    team: Team,
    run: SignalAgentRun,
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
    shadow_mode: bool = False,
) -> EmitResult:
    """Sync entry used by the DRF view path. Idempotent on `(run.id, finding_id)`.

    Shadow-mode persists the finding to `run.findings` but does not call `emit_signal`.
    If the external `emit_signal` raises, the finding row stays `emitted=False` so the
    failure is visible on the run row when the runner reads it back.

    `time_range` is a `(date_from, date_to)` tuple; the harness normalizes it into
    the `{"date_from", "date_to"}` shape that `SignalsAgentSignalExtra` expects.
    """
    from asgiref.sync import async_to_sync

    _validate_inputs(description, weight, confidence, evidence)
    finding_id = finding_id or _new_finding_id()
    extra = _build_extra(
        run_id=str(run.id),
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

    already_emitted = _record_finding_pre_emit(
        run_id=str(run.id),
        finding_id=finding_id,
        description=description,
        weight=weight,
        extra=extra,
    )
    if already_emitted:
        return EmitResult(finding_id=finding_id, emitted=True, skipped_reason="already_emitted")

    if shadow_mode:
        return EmitResult(finding_id=finding_id, emitted=False, skipped_reason="shadow_mode")

    from products.signals.backend.api import emit_signal

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

    _mark_finding_emitted(run_id=str(run.id), finding_id=finding_id)
    return EmitResult(finding_id=finding_id, emitted=True, skipped_reason=None)


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
    """Shape the extra payload to match `SignalsAgentSignalExtra` (extra='forbid'),
    omitting optional fields when not provided so pydantic doesn't see a `None` for
    fields that don't accept it."""
    # SignalsAgentSignalExtra.skill_version is float in the schema; cast explicitly.
    extra: dict[str, Any] = {
        "agent_run_id": run_id,
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


def _record_finding_pre_emit(
    *,
    run_id: str,
    finding_id: str,
    description: str,
    weight: float,
    extra: dict[str, Any],
) -> bool:
    """Persist the finding to `run.findings` under select_for_update.

    Returns True if a prior successful emit is recorded (caller short-circuits).
    Otherwise inserts/updates a `emitted=False` row and returns False.
    """
    with transaction.atomic():
        run = SignalAgentRun.objects.select_for_update().get(id=run_id)
        findings: list[dict[str, Any]] = list(run.findings or [])
        now_iso = timezone.now().isoformat()
        for entry in findings:
            if entry.get("finding_id") == finding_id:
                if entry.get("emitted"):
                    return True
                # A previous attempt failed before marking emitted — overwrite the
                # payload so any agent-side rewrite (e.g. weight tweak on retry) sticks.
                entry["description"] = description
                entry["weight"] = weight
                entry["extra"] = extra
                entry["last_attempt_at"] = now_iso
                run.findings = findings
                run.save(update_fields=["findings"])
                return False
        findings.append(
            {
                "finding_id": finding_id,
                "description": description,
                "weight": weight,
                "extra": extra,
                "emitted": False,
                "first_attempt_at": now_iso,
                "last_attempt_at": now_iso,
            }
        )
        run.findings = findings
        run.save(update_fields=["findings"])
    return False


def _mark_finding_emitted(*, run_id: str, finding_id: str) -> None:
    with transaction.atomic():
        run = SignalAgentRun.objects.select_for_update().get(id=run_id)
        findings: list[dict[str, Any]] = list(run.findings or [])
        now_iso = timezone.now().isoformat()
        for entry in findings:
            if entry.get("finding_id") == finding_id:
                entry["emitted"] = True
                entry["emitted_at"] = now_iso
                break
        run.findings = findings
        run.save(update_fields=["findings"])


def _new_finding_id() -> str:
    return str(uuid.uuid4())
