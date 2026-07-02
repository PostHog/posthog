"""Direct report-authoring write paths for the scout `emit_report` / `edit_report` channel.

This is the second emit channel for Signals scouts. The first one (`scout_harness/tools/emit.py`)
forwards a weak signal through `emit_signal()` and lets the grouping pipeline decide whether it
becomes a report. Here an opted-in scout has already done the research and authors the `SignalReport`
itself — so we write the report directly (like `custom_agent/persistence.py`), bypassing the
embedding-NN matcher and the promotion state machine.

The report is NOT signal-less, though. Writing it WITHOUT backing signals would break every read-side
consumer that derives state from a report's signals (source filter/chips, the `/signals/` tab, the
inbox-validation scout, snooze accounting). So we reuse the grouping pipeline's *storage substrate* —
not its matcher: each constituent observation the agent supplies is written to `document_embeddings`
as a normal `signals/signal` row with `report_id` pre-set in `metadata`, exactly the shape
`assign_and_emit_signal_activity` writes (minus the match step). The embedding worker generates the
vectors from the Kafka message, same as the pipeline. This makes an agentic report indistinguishable
from a pipeline report to read-side machinery.

Consistency caveat (documented, accepted): the signal rows go Kafka -> MV -> ClickHouse and are NOT
atomic with the Postgres report write. A read immediately after `create_scout_report` may see
`signal_count=N` in Postgres but zero rows in ClickHouse for ~1s. Callers (and the emit-and-inspect
test loop) must tolerate this lag.
"""

from __future__ import annotations

import uuid
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from posthog.schema import EmbeddingModelName

from posthog.api.embedding_worker import emit_embedding_request

from products.signals.backend.artefact_schemas import (
    ActionabilityAssessment,
    NoteArtefact,
    PriorityAssessment,
    SafetyJudgment,
    SuggestedReviewers,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact, SignalScoutRun
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.scout_harness.tools.emit import SCOUT_SIGNAL_WEIGHT, SOURCE_PRODUCT, SOURCE_TYPE

logger = logging.getLogger(__name__)

# Matches the grouping pipeline's signal rows (`assign_and_emit_signal_activity`): a scout-authored
# report's backing rows live in the same `document_embeddings` space so read-side queries that filter
# by `(product, document_type)` see them identically.
_EMBEDDING_PRODUCT = "signals"
_EMBEDDING_DOCUMENT_TYPE = "signal"
_EMBEDDING_RENDERING = "plain"

# Defensive cap: a single authored report shouldn't carry an unbounded evidence list. The agent groups
# its own observations; this is a harness circuit breaker, mirroring `MAX_EVIDENCE_ENTRIES` on emit.
MAX_REPORT_SIGNALS = 50


class InvalidScoutReportError(ValueError):
    """The caller tried to author/edit a report with an invalid shape (empty title, no signals, ...)."""


@dataclass(frozen=True)
class ScoutReportSignal:
    """One observation backing an authored report — written as a `signals/signal` embedding row.

    `description` is the text that gets embedded and rendered to the research/safety surfaces.
    `source_id` is a stable identifier for the observation within the report (so a later
    `edit_report` can address it for soft-delete). `document_id` is the ClickHouse row id; left
    unset it is generated, but an edit that soft-deletes a prior signal must pass the original
    `document_id` so the ReplacingMergeTree supersedes the live row rather than adding a sibling.
    """

    description: str
    source_id: str
    weight: float = SCOUT_SIGNAL_WEIGHT
    timestamp: datetime | None = None
    extra: dict = field(default_factory=dict)
    document_id: str | None = None


@dataclass(frozen=True)
class PersistedScoutReport:
    report_id: str
    signal_count: int
    total_weight: float
    # The ClickHouse `document_id`s written for the backing signals, in input order. Lets a caller
    # (and the run tally) tie the report back to its signal rows without a scan, and gives a later
    # `edit_report` the ids it needs to soft-delete a specific observation.
    signal_document_ids: list[str]


def create_scout_report(
    *,
    team_id: int,
    title: str,
    summary: str,
    signals: Sequence[ScoutReportSignal],
    attribution: ArtefactAttribution,
    status: SignalReport.Status = SignalReport.Status.READY,
    safety: SafetyJudgment | None = None,
    actionability: ActionabilityAssessment | None = None,
    repo_selection: RepoSelectionResult | None = None,
    priority: PriorityAssessment | None = None,
    suggested_reviewers: SuggestedReviewers | None = None,
    emit_signals: bool = True,
    run: SignalScoutRun | None = None,
) -> PersistedScoutReport:
    """Author a `SignalReport` directly plus its backing signal rows, in one report-owning transaction.

    The Postgres report row (with `signal_count`/`total_weight` set to match the supplied signals) is
    written inside `transaction.atomic()`. The backing signal rows are emitted to Kafka *after* the
    block commits — never inside it — so a rolled-back report never leaves orphan signals pointing at
    a `report_id` that doesn't exist. This function owns its transaction boundary; do not wrap it in an
    outer atomic block (that would defer the commit and the emits past your control).

    `status` is the status the report is born at. It defaults to READY (the custom-agent precedent);
    the safety/actionability judge (`judge.py`) is what chooses READY vs SUPPRESSED vs PENDING_INPUT
    and passes the resolved status here. `safety` / `actionability`, when provided, are written as the
    report's status artefacts (the same `safety_judgment` / `actionability_judgment` types the pipeline
    writes) so the verdict that set the status is auditable on the report, not just implicit in it.

    `repo_selection` / `priority` / `suggested_reviewers`, when provided, are written as the same
    status artefacts a pipeline report carries (`repo_selection` / `priority_judgment` /
    `suggested_reviewers`). They are what `auto_start.maybe_autostart_from_report_artefacts` reads to
    open a draft PR — the autostart hook itself is fired by the caller *after* this returns (never
    in-txn, since it spawns a Task), so the `suggested_reviewers` append opts out of the model's
    autostart re-evaluation hook, mirroring `create_custom_agent_ready_report`.

    `emit_signals` gates whether the backing observations are written to `document_embeddings`. It
    defaults to True; callers pass False for a report the safety judge marked unsafe (born SUPPRESSED)
    so the adversarial-looking descriptions are never indexed — an unsafe report's signals must not
    become semantic-search candidates or matching context for unrelated signals, mirroring how the
    pipeline buffer drops unsafe signals before grouping. The report row still records the authored
    `signal_count`/`total_weight`; it just stays invisible with no indexed evidence.
    """
    _validate_create_inputs(title, summary, signals)
    # Defense-in-depth: refuse to author against a run another team owns, so the tally write below
    # can't corrupt a foreign team's `emitted_report_ids`. The harness tool already gates this with
    # `_assert_team_owns_run`; this guards a future direct caller that bypasses it (mirrors `emit`).
    if run is not None and run.team_id != team_id:
        raise RuntimeError(f"create_scout_report: team {team_id} does not own run {run.id} (team {run.team_id})")

    document_ids = [s.document_id or str(uuid.uuid4()) for s in signals]
    total_weight = sum(s.weight for s in signals)

    with transaction.atomic():
        report = SignalReport.objects.create(
            team_id=team_id,
            status=status,
            title=title,
            summary=summary,
            signal_count=len(signals),
            total_weight=total_weight,
        )
        report_id = str(report.id)
        # Provenance: every authored report carries a note marking it scout-authored, attributed to
        # the scout's task. This keeps an agentic report auditable as NOT pipeline-generated (a
        # concern raised by edit_report's any-report reach) and gives it a non-empty work log so it
        # isn't evidence-less in the UI. Written in-txn with the report so the two never diverge.
        SignalReportArtefact.append(
            team_id=team_id,
            report_id=report_id,
            content=NoteArtefact(note=_provenance_note_text(run), author=_provenance_author(run)),
            attribution=attribution,
            reevaluate_autostart=False,
        )
        # The judge verdicts that set `status`, recorded as the report's status artefacts so the
        # decision is auditable on the report (and so the inbox derives the same actionability/safety
        # state a pipeline report would). Written in-txn with the report for the same no-divergence reason.
        if safety is not None:
            SignalReportArtefact.append_status(
                team_id=team_id, report_id=report_id, content=safety, attribution=attribution
            )
        if actionability is not None:
            SignalReportArtefact.append_status(
                team_id=team_id, report_id=report_id, content=actionability, attribution=attribution
            )
        # Autostart inputs (mirroring `create_custom_agent_ready_report`): the repo the fix lands in,
        # the priority, and the suggested reviewers. The reviewers append opts out of the autostart
        # re-eval hook — autostart is fired explicitly by the caller after commit, never in-txn.
        if repo_selection is not None:
            SignalReportArtefact.append_status(
                team_id=team_id, report_id=report_id, content=repo_selection, attribution=attribution
            )
        if priority is not None:
            SignalReportArtefact.append_status(
                team_id=team_id, report_id=report_id, content=priority, attribution=attribution
            )
        if suggested_reviewers is not None and len(suggested_reviewers.root) > 0:
            SignalReportArtefact.append_status(
                team_id=team_id,
                report_id=report_id,
                content=suggested_reviewers,
                attribution=attribution,
                reevaluate_autostart=False,
            )

    # Committed: now emit the backing signals (unless suppressed-unsafe — see `emit_signals`).
    # Sequential (not on_commit) so the call is observable and so a Kafka failure surfaces to the
    # caller rather than being swallowed by a commit hook.
    if emit_signals:
        # Stamp the authoring scout onto every backing signal so the inbox can render "Scout · <name>"
        # on the evidence card + header, matching the emit_signal path. `run` is the single place the
        # skill_name is available (bound signals otherwise ship empty extra, see `_build_signals`).
        skill_name = run.skill_name if run is not None else None
        for signal, document_id in zip(signals, document_ids):
            _emit_bound_signal(
                team_id=team_id, report_id=report_id, signal=signal, document_id=document_id, skill_name=skill_name
            )

    if run is not None:
        _record_report_emit(team_id=team_id, run_id=run.id, report_id=report_id)

    logger.info(
        "signals_scout.emit_report: created",
        extra={"team_id": team_id, "report_id": report_id, "signal_count": len(signals)},
    )
    return PersistedScoutReport(
        report_id=report_id,
        signal_count=len(signals),
        total_weight=total_weight,
        signal_document_ids=document_ids,
    )


def update_scout_report(
    *,
    team_id: int,
    report_id: str,
    title: str | None = None,
    summary: str | None = None,
    attribution: ArtefactAttribution | None = None,
    author: str | None = None,
) -> list[str]:
    """Rewrite an existing report's `title`/`summary` in place (the `edit_report` content path).

    Team-scoped fail-closed: a `report_id` the team doesn't own raises, never silently no-ops. Returns
    the modified field names. Title/summary edits are best-effort authorship — the pipeline may later
    re-research and overwrite them (decision #6); that is documented in the scout-facing contract.

    When `attribution` is supplied and the content actually changes, an audit note is appended to the
    report's work log recording who rewrote what — `edit_report` can target ANY inbox report (pipeline-
    authored included), so a core-content rewrite must leave a durable, attributable trail, not just a
    silent field mutation.
    """
    if title is None and summary is None:
        return []
    _validate_report_id(report_id)
    _validate_optional_text("title", title)
    _validate_optional_text("summary", summary)

    with transaction.atomic():
        report = SignalReport.objects.select_for_update().filter(team_id=team_id, id=report_id).first()
        if report is None:
            raise InvalidScoutReportError(f"report {report_id} not found for team {team_id}")
        updated_fields = report.update_authored_content(title=title, summary=summary)
        if updated_fields:
            report.save(update_fields=updated_fields)
            if attribution is not None:
                SignalReportArtefact.add_log(
                    team_id=team_id,
                    report_id=report_id,
                    content=NoteArtefact(note=_content_edit_note(updated_fields), author=author),
                    attribution=attribution,
                )

    logger.info(
        "signals_scout.edit_report: content updated",
        extra={"team_id": team_id, "report_id": report_id, "fields": updated_fields},
    )
    return updated_fields


def append_report_note(
    *,
    team_id: int,
    report_id: str,
    note: str,
    attribution: ArtefactAttribution,
    author: str | None = None,
) -> str:
    """Append a free-form `note` artefact to an existing report (the `edit_report` annotate path).

    Team-scoped fail-closed: a `report_id` the team doesn't own raises. `edit_report` can target ANY
    inbox report (decision #2), pipeline-authored ones included, so the note is attributed (to the
    scout's task) to keep the edit auditable and distinguishable from pipeline output. Returns the
    report_id on success.
    """
    if not note or not note.strip():
        raise InvalidScoutReportError("note must not be empty")
    _validate_report_id(report_id)
    with transaction.atomic():
        # Existence is the team-scoped gate; the artefact append itself is keyed by report_id.
        if not SignalReport.objects.filter(team_id=team_id, id=report_id).exists():
            raise InvalidScoutReportError(f"report {report_id} not found for team {team_id}")
        SignalReportArtefact.add_log(
            team_id=team_id,
            report_id=report_id,
            content=NoteArtefact(note=note, author=author),
            attribution=attribution,
        )
    logger.info("signals_scout.edit_report: note appended", extra={"team_id": team_id, "report_id": report_id})
    return report_id


def set_scout_report_reviewers(
    *,
    team_id: int,
    report_id: str,
    suggested_reviewers: SuggestedReviewers,
    attribution: ArtefactAttribution,
    author: str | None = None,
) -> bool:
    """Replace an existing report's `suggested_reviewers` status artefact (latest-wins) — the
    `edit_report` reviewer path. Returns True when reviewers were written, False when the supplied list
    is empty (a no-op that leaves any existing reviewers untouched, never silently clears them).

    Team-scoped fail-closed: a `report_id` the team doesn't own raises. `edit_report` can target ANY
    inbox report (pipeline-authored included), so the change is attributed (to the scout's task) and an
    audit note is logged, keeping it auditable and distinguishable from pipeline output.

    The append opts out of the model's autostart re-eval hook (`reevaluate_autostart=False`); the caller
    (`_do_edit_report`) fires `maybe_autostart_from_report_artefacts` after this returns — never in-txn,
    since it spawns a Task — mirroring `create_scout_report`. Autostart is idempotent, so re-running it
    for an already-started report no-ops, while a report that lacked a qualifying reviewer can now open a
    draft PR."""
    _validate_report_id(report_id)
    if len(suggested_reviewers.root) == 0:
        return False
    logins = [entry.github_login for entry in suggested_reviewers.root]
    with transaction.atomic():
        # Existence is the team-scoped gate; the artefact append itself is keyed by report_id.
        if not SignalReport.objects.filter(team_id=team_id, id=report_id).exists():
            raise InvalidScoutReportError(f"report {report_id} not found for team {team_id}")
        SignalReportArtefact.append_status(
            team_id=team_id,
            report_id=report_id,
            content=suggested_reviewers,
            attribution=attribution,
            reevaluate_autostart=False,
        )
        SignalReportArtefact.add_log(
            team_id=team_id,
            report_id=report_id,
            content=NoteArtefact(note=f"Set suggested reviewers: {', '.join(logins)}", author=author),
            attribution=attribution,
        )
    logger.info(
        "signals_scout.edit_report: reviewers set",
        extra={"team_id": team_id, "report_id": report_id, "reviewers": logins},
    )
    return True


def soft_delete_scout_signal(
    *,
    team_id: int,
    report_id: str,
    document_id: str,
    description: str,
    timestamp: datetime,
    source_id: str,
    weight: float = SCOUT_SIGNAL_WEIGHT,
    extra: dict | None = None,
) -> None:
    """Soft-delete a backing signal by re-emitting its `document_id` with `metadata.deleted=True`.

    The embeddings table is a ReplacingMergeTree keyed on `document_id`; re-emitting the same id with a
    later `inserted_at` supersedes the live row. The original `timestamp` is preserved (the table
    partitions on it) so the tombstone lands in the same partition as the row it replaces — matching
    how the grouping pipeline soft-deletes stale signals on a deleted report.

    Team-scoped fail-closed, like the other edit paths: validate the `report_id` and confirm the team
    owns it before emitting the tombstone, so a caller with a foreign `report_id` + known `document_id`
    can't soft-delete another tenant's backing signal.
    """
    _validate_report_id(report_id)
    if not SignalReport.objects.filter(team_id=team_id, id=report_id).exists():
        raise InvalidScoutReportError(f"report {report_id} not found for team {team_id}")
    metadata = _signal_metadata(report_id=report_id, source_id=source_id, weight=weight, extra=extra)
    metadata["deleted"] = True
    emit_embedding_request(
        content=description,
        team_id=team_id,
        product=_EMBEDDING_PRODUCT,
        document_type=_EMBEDDING_DOCUMENT_TYPE,
        rendering=_EMBEDDING_RENDERING,
        document_id=document_id,
        models=[m.value for m in EmbeddingModelName],
        timestamp=timestamp,
        metadata=metadata,
    )


def _emit_bound_signal(
    *,
    team_id: int,
    report_id: str,
    signal: ScoutReportSignal,
    document_id: str,
    skill_name: str | None = None,
) -> None:
    """Write one backing signal row to `document_embeddings`, mirroring `assign_and_emit_signal_activity`
    minus the matcher. `report_id` in metadata is what binds it to the report on the read side.

    `skill_name`, when set, is merged into the signal's `extra` so the read side knows which scout
    authored the finding (the inbox renders it as "Scout · <name>")."""
    extra = {**signal.extra, "skill_name": skill_name} if skill_name else signal.extra
    metadata = _signal_metadata(report_id=report_id, source_id=signal.source_id, weight=signal.weight, extra=extra)
    emit_embedding_request(
        content=signal.description,
        team_id=team_id,
        product=_EMBEDDING_PRODUCT,
        document_type=_EMBEDDING_DOCUMENT_TYPE,
        rendering=_EMBEDDING_RENDERING,
        document_id=document_id,
        models=[m.value for m in EmbeddingModelName],
        timestamp=signal.timestamp or timezone.now(),
        metadata=metadata,
    )


def _signal_metadata(*, report_id: str, source_id: str, weight: float, extra: dict | None) -> dict:
    """The `metadata` JSON for a backing signal row. Keys match the grouping pipeline's so the same
    `JSONExtractString(metadata, ...)` read queries resolve a scout-authored signal identically.
    `match_metadata` is intentionally omitted — these rows never went through the matcher."""
    return {
        "source_product": SOURCE_PRODUCT,
        "source_type": SOURCE_TYPE,
        "source_id": source_id,
        "weight": weight,
        "report_id": report_id,
        "extra": extra or {},
        "remediation": None,
    }


def _record_report_emit(*, team_id: int, run_id: uuid.UUID, report_id: str) -> None:
    """Append `report_id` to the run's `emitted_report_ids` tally so "which reports did this run
    author?" is a column lookup. Best-effort and observability only (mirrors `emit._record_emit`):
    the report has already been created by the time this runs, so any failure here is swallowed rather
    than surfaced as a false emit failure. Runs under `select_for_update` so the read-modify-write on
    the JSON list is safe, and scopes the lookup to `team_id` via the fail-closed manager so the tally
    write can never touch a foreign team's run even if the caller's ownership guard regresses."""
    try:
        with transaction.atomic():
            run = SignalScoutRun.objects.for_team(team_id).select_for_update().filter(pk=run_id).first()
            if run is None:
                logger.warning("signals_scout.emit_report: run %s gone, skipping report tally", run_id)
                return
            report_ids = [*(run.emitted_report_ids or []), report_id]
            run.emitted_report_ids = report_ids
            run.save(update_fields=["emitted_report_ids"])
    except Exception:
        logger.exception("signals_scout.emit_report: failed to record report emit for run %s", run_id)


def record_report_edit(*, team_id: int, run_id: uuid.UUID, report_id: str) -> None:
    """Append `report_id` to the run's `edited_report_ids` tally so "which reports did this run edit?" is a
    column lookup — the edit-channel counterpart to `_record_report_emit`. Public (unlike its emit
    counterpart) because the edit channel records from the tool layer: one `edit_report` call is one
    logical "run edited this report" event, so `_do_edit_report` calls this across the module boundary
    rather than threading a run through `update_scout_report` / `append_report_note`. Deduped: a run that
    edits the same report twice records it once (the per-edit detail lives in the report's artefact log).
    Best-effort
    and observability only: the edit has already committed by the time this runs, so any failure here is
    swallowed rather than surfaced as a false edit failure. Runs under `select_for_update` so the
    read-modify-write on the JSON list is safe, and scopes the lookup to `team_id` via the fail-closed
    manager so the tally write can never touch a foreign team's run."""
    try:
        with transaction.atomic():
            run = SignalScoutRun.objects.for_team(team_id).select_for_update().filter(pk=run_id).first()
            if run is None:
                logger.warning("signals_scout.edit_report: run %s gone, skipping edit tally", run_id)
                return
            existing = run.edited_report_ids or []
            if report_id in existing:
                return
            run.edited_report_ids = [*existing, report_id]
            run.save(update_fields=["edited_report_ids"])
    except Exception:
        logger.exception("signals_scout.edit_report: failed to record report edit for run %s", run_id)


def _provenance_note_text(run: SignalScoutRun | None) -> str:
    if run is not None:
        return f"Authored directly by the `{run.skill_name}` Signals scout via emit_report."
    return "Authored directly by a Signals scout via emit_report."


def _provenance_author(run: SignalScoutRun | None) -> str:
    return run.skill_name if run is not None else "signals_scout"


def _validate_create_inputs(title: str, summary: str, signals: Sequence[ScoutReportSignal]) -> None:
    if not title or not title.strip():
        raise InvalidScoutReportError("title must not be empty")
    if not summary or not summary.strip():
        raise InvalidScoutReportError("summary must not be empty")
    if not signals:
        raise InvalidScoutReportError("a report must be backed by at least one signal")
    if len(signals) > MAX_REPORT_SIGNALS:
        raise InvalidScoutReportError(f"report has {len(signals)} signals, max is {MAX_REPORT_SIGNALS}")
    for signal in signals:
        if not signal.description or not signal.description.strip():
            raise InvalidScoutReportError("every backing signal must have a non-empty description")
        if signal.weight < 0.0:
            raise InvalidScoutReportError(f"signal weight must be non-negative, got {signal.weight}")
    # Reject duplicate caller-supplied `document_id`s. The embeddings table is a ReplacingMergeTree
    # keyed on `document_id`, so two rows sharing one id would collapse to one — the report would claim
    # `signal_count=N` while a read resolves fewer. Unset ids are generated fresh and never collide.
    supplied_ids = [s.document_id for s in signals if s.document_id is not None]
    if len(supplied_ids) != len(set(supplied_ids)):
        raise InvalidScoutReportError("backing signals must have unique document_ids")


def _validate_optional_text(field_name: str, value: str | None) -> None:
    if value is not None and not value.strip():
        raise InvalidScoutReportError(f"{field_name} must not be empty when provided")


def _content_edit_note(updated_fields: list[str]) -> str:
    return f"Edited report {' and '.join(updated_fields)} via edit_report."


def _validate_report_id(report_id: str) -> None:
    """Reject a malformed `report_id` at the service boundary with a caller error, so the later
    `id=report_id` filter doesn't raise Django's UUID `ValidationError` as an uncaught 500. Covers
    both the DRF path (CharField) and the async Temporal path, which don't go through a UUID field."""
    try:
        uuid.UUID(str(report_id))
    except (ValueError, AttributeError, TypeError):
        raise InvalidScoutReportError(f"report_id is not a valid UUID: {report_id!r}")
