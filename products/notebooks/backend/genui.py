import re
import json
import math
from datetime import datetime, timedelta
from functools import partial
from hashlib import sha256
from typing import cast
from uuid import UUID

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.otel_metrics import OtelInstrumentFactory

from products.canvas.backend.facade import notebooks as canvas_facade
from products.notebooks.backend.analytics import (
    GENUI_BUILD_COMPLETED_EVENT,
    GENUI_GENERATION_COMPLETED_EVENT,
    GENUI_MATERIALIZATION_REQUESTED_EVENT,
    GENUI_RUN_COMPLETED_EVENT,
    capture_genui_lifecycle,
)
from products.notebooks.backend.genui_snapshot_store import (
    GenUISnapshotStoreError,
    build_snapshot_key,
    delete_snapshot,
    read_snapshot,
    write_snapshot,
)
from products.notebooks.backend.models import Notebook, NotebookGenUI, NotebookNodeRun
from products.notebooks.backend.sql_v2_state import NotebookCellState, build_notebook_cell_state
from products.notebooks.backend.tasks import process_genui_generation
from products.notebooks.backend.util import (
    _get_markdown_notebook_markdown,
    _iter_markdown_component_blocks,
    _parse_markdown_component_props,
)
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)
_otel = OtelInstrumentFactory("notebooks")

GENUI_GENERATOR_VERSION = "2"
MAX_INPUTS = 4
MAX_INPUT_NAME_LENGTH = 128
MAX_PROMPT_LENGTH = 20_000
MAX_ERROR_LENGTH = 2_000
MAX_COLUMNS = 100
MAX_ROWS = 100
MAX_CELL_STRING_LENGTH = 4_096
MAX_ACTIVE_GENERATIONS_PER_TEAM = 10
MAX_GENERATIONS_PER_USER_PER_MINUTE = 5
GENERATION_TIMEOUT = timedelta(minutes=30)

_INPUT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ACTIVE_LIFECYCLES = [NotebookGenUI.LifecycleStatus.GENERATING, NotebookGenUI.LifecycleStatus.BUILDING]


class GenUIError(Exception):
    def __init__(self, detail: str, code: str) -> None:
        self.detail = detail
        self.code = code
        super().__init__(detail)


class GenUIRateLimitError(GenUIError):
    pass


class GenUIConflictError(GenUIError):
    pass


@frozen
class GenUIInputInspection:
    states: list[dict[str, object]]
    schemas: list[dict[str, object]]
    frames: dict[str, object]
    schema_hash: str
    snapshot_hash: str
    snapshot_metadata: dict[str, object]
    ready: bool


@frozen
class GenUIStatus:
    node_id: str
    lifecycle_status: str
    staleness_reason: str | None
    error_code: str | None
    error_detail: str | None
    artifact_url: str | None
    frame_names: list[str]
    source_version_id: UUID | None
    build_id: UUID | None
    input_states: list[dict[str, object]]
    can_run: bool
    can_regenerate: bool
    can_retry: bool
    created_at: datetime
    updated_at: datetime
    generated_at: datetime | None
    snapshot_updated_at: datetime | None


@frozen
class GenUISource:
    version_id: UUID
    source: str


@frozen
class GenUIVersion:
    id: UUID
    prompt: str | None
    created_at: datetime
    is_current: bool


@frozen
class GenUIGenerationClaim:
    row: NotebookGenUI
    acquired: bool


def normalize_prompt(prompt: str) -> str:
    normalized = " ".join(prompt.split())
    if not normalized:
        raise GenUIError("Add a prompt before generating the visualization.", "missing_prompt")
    if len(normalized) > MAX_PROMPT_LENGTH:
        raise GenUIError("The visualization prompt is too long.", "prompt_too_long")
    return normalized


def normalize_inputs(inputs: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_name in inputs:
        name = raw_name.strip()
        if not name or len(name) > MAX_INPUT_NAME_LENGTH or not _INPUT_NAME.fullmatch(name):
            raise GenUIError(f'"{raw_name}" is not a valid dataframe name.', "invalid_input_name")
        if name in seen:
            raise GenUIError(f'Dataframe "{name}" is listed more than once.', "duplicate_input_name")
        seen.add(name)
        normalized.append(name)
    if len(normalized) > MAX_INPUTS:
        raise GenUIError(f"Choose no more than {MAX_INPUTS} dataframes.", "too_many_inputs")
    return normalized


def _hash(value: object) -> str:
    return sha256(json.dumps(value, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def _safe_cell(value: object) -> object:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:MAX_CELL_STRING_LENGTH]
    serialized = json.dumps(value, default=str, separators=(",", ":"))
    return serialized[:MAX_CELL_STRING_LENGTH]


def _frame_from_run(name: str, run: NotebookNodeRun) -> dict[str, object]:
    envelope = run.envelope if isinstance(run.envelope, dict) else {}
    raw_columns = envelope.get("types")
    columns: list[dict[str, str]] = []
    if isinstance(raw_columns, list):
        for pair in raw_columns[:MAX_COLUMNS]:
            if isinstance(pair, list) and len(pair) >= 2:
                columns.append({"name": str(pair[0])[:256], "type": str(pair[1])[:256]})
    if not columns and isinstance(envelope.get("columns"), list):
        columns = [
            {"name": str(column)[:256], "type": "unknown"}
            for column in cast(list[object], envelope["columns"])[:MAX_COLUMNS]
        ]

    rows: list[list[object]] = []
    raw_rows = envelope.get("first_page")
    if isinstance(raw_rows, list):
        for raw_row in raw_rows[:MAX_ROWS]:
            if isinstance(raw_row, list):
                rows.append([_safe_cell(value) for value in raw_row[: len(columns)]])
    row_count = envelope.get("row_count")
    total_row_count = row_count if isinstance(row_count, int) and row_count >= 0 else len(rows)
    return {
        "name": name,
        "columns": columns,
        "rows": rows,
        "totalRowCount": total_row_count,
        "includedRowCount": len(rows),
        "truncated": len(rows) < total_row_count,
    }


def inspect_inputs(notebook: Notebook, inputs: list[str]) -> GenUIInputInspection:
    cells = build_notebook_cell_state(notebook.team_id, notebook)
    owners: dict[str, NotebookCellState] = {}
    for cell_type in ("sql", "python"):
        for cell in cells:
            if cell.cell_type == cell_type and _INPUT_NAME.fullmatch(cell.dataframe_name):
                owners.setdefault(cell.dataframe_name, cell)

    run_ids = [cast(dict[str, object], cell.last_run).get("run_id") for cell in owners.values() if cell.last_run]
    runs = {
        str(run.id): run
        for run in NotebookNodeRun.objects.for_team(notebook.team_id).filter(
            notebook=notebook, id__in=[run_id for run_id in run_ids if isinstance(run_id, str)]
        )
    }

    states: list[dict[str, object]] = []
    schemas: list[dict[str, object]] = []
    frames: dict[str, object] = {}
    ready = True
    for name in inputs:
        owner = owners.get(name)
        if owner is None:
            states.append({"name": name, "input_status": "missing", "error": "No cell exports this dataframe."})
            ready = False
            continue
        cell_status = str(owner.status)
        run_id = cast(dict[str, object], owner.last_run or {}).get("run_id")
        run = runs.get(str(run_id)) if run_id else None
        if cell_status != NotebookNodeRun.Status.DONE or run is None:
            mapped_status = "never_run" if cell_status == "never_run" else cell_status
            states.append(
                {
                    "name": name,
                    "input_status": mapped_status,
                    "producer_node_id": str(owner.node_id),
                    "run_id": str(run_id) if run_id else None,
                    "error": cast(dict[str, object], owner.last_run or {}).get("error"),
                }
            )
            ready = False
            continue

        frame = _frame_from_run(name, run)
        frames[name] = frame
        schema = {
            "name": name,
            "columns": frame["columns"],
            "totalRowCount": frame["totalRowCount"],
            "includedRowCount": frame["includedRowCount"],
            "truncated": frame["truncated"],
        }
        schemas.append(schema)
        states.append(
            {
                **schema,
                "input_status": "ready",
                "producer_node_id": str(owner.node_id),
                "run_id": str(run.id),
                "error": None,
            }
        )

    schema_hash = _hash([{"name": schema["name"], "columns": schema["columns"]} for schema in schemas])
    snapshot_hash = _hash(
        {
            "runs": [state.get("run_id") for state in states],
            "frames": frames,
        }
    )
    metadata: dict[str, object] = {
        "inputs": states,
        "schemas": schemas,
        "schema_hash": schema_hash,
        "captured_at": timezone.now().isoformat(),
    }
    return GenUIInputInspection(
        states=states,
        schemas=schemas,
        frames=frames,
        schema_hash=schema_hash,
        snapshot_hash=snapshot_hash,
        snapshot_metadata=metadata,
        ready=ready,
    )


def generation_hash(*, prompt: str, inputs: list[str], inspection: GenUIInputInspection) -> str:
    return _hash(
        {
            "prompt": prompt,
            "inputs": inputs,
            "schemas": [{"name": schema["name"], "columns": schema["columns"]} for schema in inspection.schemas],
            "generator_version": GENUI_GENERATOR_VERSION,
        }
    )


def _store_snapshot(
    notebook: Notebook, node_id: str, inspection: GenUIInputInspection
) -> tuple[str, dict[str, object]]:
    key = build_snapshot_key(
        team_id=notebook.team_id,
        notebook_id=notebook.id,
        node_id=node_id,
        snapshot_hash=inspection.snapshot_hash,
    )
    try:
        size = write_snapshot(key=key, frames=inspection.frames)
    except GenUISnapshotStoreError as error:
        raise GenUIError(
            "The dataframe previews could not be saved. Try running the visualization again.",
            "snapshot_write_failed",
        ) from error
    return key, {**inspection.snapshot_metadata, "size": size}


def _display_name(prompt: str) -> str:
    return prompt if len(prompt) <= 80 else f"{prompt[:77].rstrip()}..."


def _check_generation_rate(team_id: int, user_id: int) -> None:
    minute = int(timezone.now().timestamp() // 60)
    key = f"notebook_genui_generation:{team_id}:{user_id}:{minute}"
    if cache.add(key, 1, timeout=90):
        return
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=90)
        count = 1
    if count > MAX_GENERATIONS_PER_USER_PER_MINUTE:
        _otel.counter("notebooks.genui.generation.rejected").add(1, {"reason": "rate_limit"})
        raise GenUIRateLimitError("Too many visualization generations started. Try again in a minute.", "rate_limited")


def _is_ai_usage_limited(team_api_token: str) -> bool:
    from ee.billing.quota_limiting import (  # noqa: PLC0415 — keeps billing's query stack off Django startup
        is_team_over_ai_credit_budget,
    )

    return is_team_over_ai_credit_budget(team_api_token)


def _assert_generation_allowed(*, notebook: Notebook, user_id: int) -> None:
    _check_generation_rate(notebook.team_id, user_id)
    if _is_ai_usage_limited(notebook.team.api_token):
        _otel.counter("notebooks.genui.generation.rejected").add(1, {"reason": "usage_limit"})
        raise GenUIRateLimitError(
            "Visualization generation is unavailable because this project's AI usage limit has been reached.",
            "usage_limit_exceeded",
        )
    active = NotebookGenUI.objects.for_team(notebook.team_id).filter(lifecycle_status__in=_ACTIVE_LIFECYCLES).count()
    if active >= MAX_ACTIVE_GENERATIONS_PER_TEAM or not canvas_facade.active_build_capacity_available(
        team_id=notebook.team_id
    ):
        _otel.counter("notebooks.genui.generation.rejected").add(1, {"reason": "capacity"})
        raise GenUIRateLimitError(
            "Visualization generation capacity is full. Try again shortly.", "generation_capacity_exhausted"
        )


def _claim_generation(*, row: NotebookGenUI, inspection: GenUIInputInspection) -> GenUIGenerationClaim:
    with transaction.atomic():
        locked = NotebookGenUI.objects.for_team(row.team_id).select_for_update().get(id=row.id)
        if locked.lifecycle_status in _ACTIVE_LIFECYCLES or locked.generation_hash != row.generation_hash:
            return GenUIGenerationClaim(row=locked, acquired=False)
        locked.pending_generation_hash = locked.generation_hash
        locked.pending_schema_hash = inspection.schema_hash
        locked.lifecycle_status = NotebookGenUI.LifecycleStatus.GENERATING
        locked.last_error_code = None
        locked.last_error = None
        locked.generation_started_at = timezone.now()
        locked.save()
        return GenUIGenerationClaim(row=locked, acquired=True)


def _capture_lifecycle(
    *,
    event: str,
    row: NotebookGenUI,
    inspection: GenUIInputInspection,
    outcome: str,
    user_id: int | None = None,
    source_size_bytes: int | None = None,
    artifact_size_bytes: int | None = None,
) -> None:
    duration_seconds = (
        max(0.0, (timezone.now() - row.generation_started_at).total_seconds())
        if row.generation_started_at is not None and event != GENUI_MATERIALIZATION_REQUESTED_EVENT
        else None
    )
    try:
        capture_genui_lifecycle(
            event=event,
            team_id=row.team_id,
            notebook_short_id=row.notebook.short_id,
            node_id=row.node_id,
            outcome=outcome,
            dependency_count=len(inspection.states),
            input_row_count=sum(
                included_row_count
                for state in inspection.states
                if isinstance(included_row_count := state.get("includedRowCount"), int)
            ),
            truncated=any(state.get("truncated") is True for state in inspection.states),
            generator_version=row.generator_version,
            user_id=user_id,
            duration_seconds=duration_seconds,
            source_size_bytes=source_size_bytes,
            artifact_size_bytes=artifact_size_bytes,
        )
    except Exception:
        logger.exception(
            "notebook_genui_analytics_failed",
            team_id=row.team_id,
            notebook_id=str(row.notebook_id),
            node_id=row.node_id,
            event=event,
        )


def _start_generation(
    *, row: NotebookGenUI, notebook: Notebook, user_id: int, inspection: GenUIInputInspection
) -> NotebookGenUI:
    channel_id = tasks_facade.ensure_personal_channel_id(team_id=notebook.team_id, user_id=user_id)

    if row.canvas_id is None:
        canvas_id = canvas_facade.create_notebook_canvas(
            team_id=notebook.team_id,
            user_id=user_id,
            channel_id=channel_id,
            name=_display_name(row.prompt),
            context=row.prompt,
        )
        row.canvas_id = canvas_id
    elif not canvas_facade.update_notebook_canvas_generation(
        team_id=notebook.team_id,
        canvas_id=row.canvas_id,
        context=row.prompt,
    ):
        raise GenUIError("The generated visualization no longer exists.", "canvas_missing")

    row.lifecycle_status = NotebookGenUI.LifecycleStatus.GENERATING
    row.last_error_code = None
    row.last_error = None
    row.save()

    process_genui_generation.delay(notebook.team_id, str(row.id), user_id, row.pending_generation_hash)

    _otel.counter("notebooks.genui.generation.started").add(1, {"operation": "generation"})
    _capture_lifecycle(
        event=GENUI_MATERIALIZATION_REQUESTED_EVENT,
        row=row,
        inspection=inspection,
        outcome="started",
        user_id=user_id,
    )
    logger.info(
        "notebook_genui_generation_started",
        team_id=notebook.team_id,
        notebook_id=str(notebook.id),
        node_id=row.node_id,
        genui_id=str(row.id),
        canvas_id=str(row.canvas_id),
        dependency_count=len(inspection.states),
    )
    return row


def _run_claimed_generation(
    *, row: NotebookGenUI, notebook: Notebook, user_id: int, inspection: GenUIInputInspection
) -> NotebookGenUI:
    try:
        return _start_generation(row=row, notebook=notebook, user_id=user_id, inspection=inspection)
    except Exception as error:
        detail = error.detail if isinstance(error, GenUIError) else "Could not start visualization generation."
        NotebookGenUI.objects.for_team(row.team_id).filter(id=row.id).update(
            lifecycle_status=NotebookGenUI.LifecycleStatus.FAILED,
            last_error_code=error.code if isinstance(error, GenUIError) else "generation_start_failed",
            last_error=(detail or "Could not start visualization generation.")[:MAX_ERROR_LENGTH],
            updated_at=timezone.now(),
        )
        if isinstance(error, GenUIError):
            raise
        logger.exception(
            "notebook_genui_generation_start_failed",
            team_id=row.team_id,
            notebook_id=str(notebook.id),
            node_id=row.node_id,
            canvas_id=str(row.canvas_id),
        )
        raise GenUIError(detail, "generation_start_failed") from error


def _delete_old_snapshot(old_key: str | None, new_key: str | None, team_id: int) -> None:
    if not old_key or old_key == new_key:
        return
    try:
        delete_snapshot(key=old_key, team_id=team_id)
    except Exception:
        logger.warning("notebook_genui_snapshot_cleanup_failed", team_id=team_id, exc_info=True)


def _promote_pending_snapshot(row: NotebookGenUI) -> None:
    old_key: str | None = None
    if row.pending_snapshot_object_key:
        old_key = row.snapshot_object_key
        row.snapshot_object_key = row.pending_snapshot_object_key
        row.snapshot_hash = row.pending_snapshot_hash
        row.snapshot_metadata = row.pending_snapshot_metadata
        row.snapshot_updated_at = timezone.now()
    row.pending_snapshot_object_key = None
    row.pending_snapshot_hash = ""
    row.pending_snapshot_metadata = {}
    transaction.on_commit(lambda: _delete_old_snapshot(old_key, row.snapshot_object_key, row.team_id))


def reconcile_generation(row: NotebookGenUI, inspection: GenUIInputInspection) -> NotebookGenUI:
    if row.lifecycle_status == NotebookGenUI.LifecycleStatus.FAILED:
        return row
    if row.canvas_id is None:
        return row
    canvas = canvas_facade.get_canvas_generation_state(team_id=row.team_id, canvas_id=row.canvas_id)
    if canvas is None:
        if row.lifecycle_status != NotebookGenUI.LifecycleStatus.FAILED:
            row.lifecycle_status = NotebookGenUI.LifecycleStatus.FAILED
            row.last_error_code = "canvas_missing"
            row.last_error = "The generated visualization no longer exists."
            row.save(update_fields=["lifecycle_status", "last_error_code", "last_error", "updated_at"])
            _capture_lifecycle(
                event=GENUI_GENERATION_COMPLETED_EVENT,
                row=row,
                inspection=inspection,
                outcome="canvas_missing",
            )
        return row

    published_new_source = bool(
        row.pending_generation_hash
        and canvas.published_build_id
        and canvas.published_source_version_id == canvas.current_source_version_id
        and canvas.published_source_version_id != row.source_version_id
    )
    if published_new_source:
        with transaction.atomic():
            locked = NotebookGenUI.objects.for_team(row.team_id).select_for_update().get(id=row.id)
            locked.source_version_id = canvas.published_source_version_id
            locked.build_id = canvas.published_build_id
            locked.generated_hash = locked.pending_generation_hash
            locked.generated_schema_hash = locked.pending_schema_hash
            locked.pending_generation_hash = ""
            locked.pending_schema_hash = ""
            locked.generated_at = timezone.now()
            _promote_pending_snapshot(locked)
            if locked.generated_hash != locked.generation_hash:
                locked.lifecycle_status = NotebookGenUI.LifecycleStatus.INCOMPATIBLE
            else:
                locked.lifecycle_status = NotebookGenUI.LifecycleStatus.READY
            locked.last_error_code = None
            locked.last_error = None
            locked.save()
        _otel.counter("notebooks.genui.generation.completed").add(1, {"outcome": "ready"})
        _capture_lifecycle(
            event=GENUI_GENERATION_COMPLETED_EVENT,
            row=locked,
            inspection=inspection,
            outcome="ready",
            source_size_bytes=canvas.published_source_size,
            artifact_size_bytes=canvas.published_artifact_size,
        )
        _capture_lifecycle(
            event=GENUI_BUILD_COMPLETED_EVENT,
            row=locked,
            inspection=inspection,
            outcome="ready",
            source_size_bytes=canvas.published_source_size,
            artifact_size_bytes=canvas.published_artifact_size,
        )
        logger.info(
            "notebook_genui_generation_completed",
            team_id=row.team_id,
            notebook_id=str(row.notebook_id),
            node_id=row.node_id,
            canvas_id=str(row.canvas_id),
            build_id=str(locked.build_id),
            outcome="ready",
        )
        return locked

    if not row.pending_generation_hash:
        return row
    if row.generation_started_at and row.generation_started_at < timezone.now() - GENERATION_TIMEOUT:
        row.lifecycle_status = NotebookGenUI.LifecycleStatus.FAILED
        row.last_error_code = "generation_timeout"
        row.last_error = "Visualization generation timed out. Try again."
        row.save(update_fields=["lifecycle_status", "last_error_code", "last_error", "updated_at"])
        _otel.counter("notebooks.genui.generation.completed").add(1, {"outcome": "timed_out"})
        _capture_lifecycle(
            event=GENUI_GENERATION_COMPLETED_EVENT,
            row=row,
            inspection=inspection,
            outcome="timed_out",
        )
        return row

    if canvas.current_build_status in {"queued", "building"}:
        if row.lifecycle_status != NotebookGenUI.LifecycleStatus.BUILDING:
            row.lifecycle_status = NotebookGenUI.LifecycleStatus.BUILDING
            row.save(update_fields=["lifecycle_status", "updated_at"])
        return row
    if canvas.current_build_status == "failed":
        diagnostics = canvas.current_build_diagnostics
        message = next(
            (
                str(diagnostic.get("message"))
                for diagnostic in diagnostics
                if diagnostic.get("severity") == "error" and diagnostic.get("message")
            ),
            "Could not build this visualization. Try again.",
        )
        if row.lifecycle_status != NotebookGenUI.LifecycleStatus.FAILED:
            row.lifecycle_status = NotebookGenUI.LifecycleStatus.FAILED
            row.last_error_code = "build_failed"
            row.last_error = message[:MAX_ERROR_LENGTH]
            row.save(update_fields=["lifecycle_status", "last_error_code", "last_error", "updated_at"])
            _otel.counter("notebooks.genui.generation.completed").add(1, {"outcome": "build_failed"})
            _capture_lifecycle(
                event=GENUI_GENERATION_COMPLETED_EVENT,
                row=row,
                inspection=inspection,
                outcome="build_failed",
            )
            _capture_lifecycle(
                event=GENUI_BUILD_COMPLETED_EVENT,
                row=row,
                inspection=inspection,
                outcome="failed",
            )
            logger.info(
                "notebook_genui_generation_completed",
                team_id=row.team_id,
                notebook_id=str(row.notebook_id),
                node_id=row.node_id,
                canvas_id=str(row.canvas_id),
                build_id=str(canvas.current_build_id),
                outcome="build_failed",
            )
        return row

    return row


def _apply_current_state(
    *, row: NotebookGenUI, inspection: GenUIInputInspection, promote_snapshot: bool
) -> NotebookGenUI:
    if row.lifecycle_status == NotebookGenUI.LifecycleStatus.FAILED or row.lifecycle_status in _ACTIVE_LIFECYCLES:
        return row
    if not inspection.ready:
        if row.lifecycle_status != NotebookGenUI.LifecycleStatus.AWAITING_INPUTS:
            row.lifecycle_status = NotebookGenUI.LifecycleStatus.AWAITING_INPUTS
            row.save(update_fields=["lifecycle_status", "updated_at"])
        return row
    if not row.generated_hash:
        if row.lifecycle_status != NotebookGenUI.LifecycleStatus.AWAITING_GENERATION:
            row.lifecycle_status = NotebookGenUI.LifecycleStatus.AWAITING_GENERATION
            row.save(update_fields=["lifecycle_status", "updated_at"])
        return row
    if row.generated_hash != row.generation_hash or row.generated_schema_hash != inspection.schema_hash:
        if row.lifecycle_status != NotebookGenUI.LifecycleStatus.INCOMPATIBLE:
            row.lifecycle_status = NotebookGenUI.LifecycleStatus.INCOMPATIBLE
            row.save(update_fields=["lifecycle_status", "updated_at"])
        return row
    if row.snapshot_hash != inspection.snapshot_hash:
        if promote_snapshot:
            _promote_pending_snapshot(row)
            row.lifecycle_status = NotebookGenUI.LifecycleStatus.READY
            row.last_error_code = None
            row.last_error = None
            row.save()
            _otel.counter("notebooks.genui.snapshot.reused_source").add(1)
        else:
            if row.lifecycle_status != NotebookGenUI.LifecycleStatus.STALE:
                row.lifecycle_status = NotebookGenUI.LifecycleStatus.STALE
                row.save(update_fields=["lifecycle_status", "updated_at"])
        return row
    if row.lifecycle_status not in _ACTIVE_LIFECYCLES:
        row.lifecycle_status = NotebookGenUI.LifecycleStatus.READY
        row.save(update_fields=["lifecycle_status", "updated_at"])
    return row


def ensure_genui(
    *,
    notebook: Notebook,
    node_id: str,
    prompt: str,
    inputs: list[str],
    user_id: int,
    can_generate: bool,
    legacy_canvas_id: UUID | None = None,
) -> tuple[NotebookGenUI, GenUIInputInspection]:
    normalized_prompt = normalize_prompt(prompt)
    normalized_inputs = normalize_inputs(inputs)
    inspection = inspect_inputs(notebook, normalized_inputs)
    desired_hash = generation_hash(prompt=normalized_prompt, inputs=normalized_inputs, inspection=inspection)
    existing = (
        NotebookGenUI.objects.for_team(notebook.team_id)
        .filter(notebook=notebook, node_id=node_id)
        .only("snapshot_hash", "pending_snapshot_hash", "lifecycle_status")
        .first()
    )
    snapshot_key: str | None = None
    snapshot_metadata: dict[str, object] = {}
    snapshot_is_saved = existing is not None and inspection.snapshot_hash in {
        existing.snapshot_hash,
        existing.pending_snapshot_hash,
    }
    generation_in_flight = existing is not None and existing.lifecycle_status in _ACTIVE_LIFECYCLES
    if inspection.ready and not snapshot_is_saved and not generation_in_flight:
        snapshot_key, snapshot_metadata = _store_snapshot(notebook, node_id, inspection)

    legacy_canvas = (
        canvas_facade.get_owned_canvas_generation_state(
            team_id=notebook.team_id,
            canvas_id=legacy_canvas_id,
            user_id=user_id,
        )
        if existing is None and legacy_canvas_id
        else None
    )
    adopted_legacy = bool(
        legacy_canvas and legacy_canvas.published_build_id and legacy_canvas.published_source_version_id
    )
    legacy_source_version_id = legacy_canvas.published_source_version_id if legacy_canvas else None
    legacy_build_id = legacy_canvas.published_build_id if legacy_canvas else None

    superseded_pending_snapshot_key: str | None = None
    retained_pending_snapshot_key: str | None = None
    with transaction.atomic():
        row, created = (
            NotebookGenUI.objects.for_team(notebook.team_id)
            .select_for_update()
            .get_or_create(
                notebook=notebook,
                node_id=node_id,
                defaults={
                    "team_id": notebook.team_id,
                    "prompt": normalized_prompt,
                    "inputs": normalized_inputs,
                    "generator_version": GENUI_GENERATOR_VERSION,
                    "generation_hash": desired_hash,
                    "generated_hash": desired_hash if adopted_legacy else "",
                    "generated_schema_hash": inspection.schema_hash if adopted_legacy else "",
                    "canvas_id": legacy_canvas.canvas_id if legacy_canvas else None,
                    "source_version_id": legacy_source_version_id if adopted_legacy else None,
                    "build_id": legacy_build_id if adopted_legacy else None,
                    "snapshot_object_key": snapshot_key if adopted_legacy else None,
                    "snapshot_hash": inspection.snapshot_hash if adopted_legacy else "",
                    "snapshot_metadata": snapshot_metadata if adopted_legacy else {},
                    "snapshot_updated_at": timezone.now() if adopted_legacy else None,
                    "generated_at": timezone.now() if adopted_legacy else None,
                },
            )
        )
        row.prompt = normalized_prompt
        row.inputs = normalized_inputs
        row.generator_version = GENUI_GENERATOR_VERSION
        row.generation_hash = desired_hash
        if row.lifecycle_status in _ACTIVE_LIFECYCLES and row.pending_generation_hash:
            if snapshot_key and snapshot_key != row.pending_snapshot_object_key:
                superseded_pending_snapshot_key = snapshot_key
        elif row.snapshot_hash == inspection.snapshot_hash and row.pending_snapshot_hash != inspection.snapshot_hash:
            superseded_pending_snapshot_key = row.pending_snapshot_object_key
            row.pending_snapshot_object_key = None
            row.pending_snapshot_hash = ""
            row.pending_snapshot_metadata = {}
        elif snapshot_key and row.snapshot_hash != inspection.snapshot_hash:
            superseded_pending_snapshot_key = row.pending_snapshot_object_key
            row.pending_snapshot_object_key = snapshot_key
            row.pending_snapshot_hash = inspection.snapshot_hash
            row.pending_snapshot_metadata = snapshot_metadata
        retained_pending_snapshot_key = row.pending_snapshot_object_key
        row.save()
        if not created:
            _otel.counter("notebooks.genui.ensure.idempotent").add(1)
        if superseded_pending_snapshot_key:
            transaction.on_commit(
                partial(
                    _delete_old_snapshot,
                    superseded_pending_snapshot_key,
                    retained_pending_snapshot_key,
                    notebook.team_id,
                )
            )

    row = reconcile_generation(row, inspection)
    row = _apply_current_state(row=row, inspection=inspection, promote_snapshot=False)
    if inspection.ready and can_generate and row.lifecycle_status == NotebookGenUI.LifecycleStatus.AWAITING_GENERATION:
        _assert_generation_allowed(notebook=notebook, user_id=user_id)
        claimed = _claim_generation(row=row, inspection=inspection)
        row = claimed.row
        if claimed.acquired:
            row = _run_claimed_generation(row=row, notebook=notebook, user_id=user_id, inspection=inspection)
    return row, inspection


def refresh_genui(*, notebook: Notebook, node_id: str) -> tuple[NotebookGenUI, GenUIInputInspection]:
    row = NotebookGenUI.objects.for_team(notebook.team_id).filter(notebook=notebook, node_id=node_id).first()
    if row is None:
        raise GenUIError("This custom visualization has not been initialized.", "not_initialized")
    inspection = inspect_inputs(notebook, cast(list[str], row.inputs))
    row = reconcile_generation(row, inspection)
    row = _apply_current_state(row=row, inspection=inspection, promote_snapshot=False)
    return row, inspection


def run_stale_genui(*, notebook: Notebook, node_id: str) -> tuple[NotebookGenUI, GenUIInputInspection]:
    row, inspection = refresh_genui(notebook=notebook, node_id=node_id)
    if not inspection.ready:
        raise GenUIConflictError(
            "Run the required dataframe cells before refreshing this visualization.", "inputs_unready"
        )
    if row.generated_hash != row.generation_hash or row.generated_schema_hash != inspection.schema_hash:
        raise GenUIConflictError(
            "The prompt or dataframe schema changed. Regenerate the visualization to update its code.",
            "generation_incompatible",
        )
    snapshot_key, metadata = _store_snapshot(notebook, node_id, inspection)
    row.pending_snapshot_object_key = snapshot_key
    row.pending_snapshot_hash = inspection.snapshot_hash
    row.pending_snapshot_metadata = metadata
    row = _apply_current_state(row=row, inspection=inspection, promote_snapshot=True)
    _capture_lifecycle(
        event=GENUI_RUN_COMPLETED_EVENT,
        row=row,
        inspection=inspection,
        outcome="ready",
    )
    logger.info(
        "notebook_genui_run_completed",
        team_id=row.team_id,
        notebook_id=str(row.notebook_id),
        node_id=row.node_id,
        canvas_id=str(row.canvas_id),
        build_id=str(row.build_id),
        outcome="ready",
    )
    return row, inspection


def regenerate_genui(
    *, notebook: Notebook, node_id: str, prompt: str, inputs: list[str], user_id: int
) -> tuple[NotebookGenUI, GenUIInputInspection]:
    row, inspection = ensure_genui(
        notebook=notebook,
        node_id=node_id,
        prompt=prompt,
        inputs=inputs,
        user_id=user_id,
        can_generate=False,
        legacy_canvas_id=None,
    )
    if not inspection.ready:
        raise GenUIConflictError(
            "Run the required dataframe cells before regenerating this visualization.", "inputs_unready"
        )
    if row.lifecycle_status in _ACTIVE_LIFECYCLES:
        return row, inspection
    _assert_generation_allowed(notebook=notebook, user_id=user_id)
    claimed = _claim_generation(row=row, inspection=inspection)
    row = claimed.row
    if not claimed.acquired:
        return row, inspection
    row = _run_claimed_generation(row=row, notebook=notebook, user_id=user_id, inspection=inspection)
    return row, inspection


def retry_genui(*, notebook: Notebook, node_id: str, user_id: int) -> tuple[NotebookGenUI, GenUIInputInspection]:
    row, inspection = refresh_genui(notebook=notebook, node_id=node_id)
    if row.lifecycle_status != NotebookGenUI.LifecycleStatus.FAILED:
        raise GenUIConflictError("Only a failed visualization can be retried.", "retry_not_available")
    if not inspection.ready:
        raise GenUIConflictError(
            "Run the required dataframe cells before retrying this visualization.", "inputs_unready"
        )
    if row.last_error_code == "canvas_missing":
        row.canvas_id = None
        row.save(update_fields=["canvas_id", "updated_at"])
    _assert_generation_allowed(notebook=notebook, user_id=user_id)
    claimed = _claim_generation(row=row, inspection=inspection)
    row = claimed.row
    if not claimed.acquired:
        return row, inspection
    row = _run_claimed_generation(row=row, notebook=notebook, user_id=user_id, inspection=inspection)
    return row, inspection


def read_genui_source(*, notebook: Notebook, node_id: str, version_id: UUID | None = None) -> GenUISource:
    row = NotebookGenUI.objects.for_team(notebook.team_id).filter(notebook=notebook, node_id=node_id).first()
    if row is None or row.canvas_id is None or row.source_version_id is None:
        raise GenUIError("Generate this visualization before viewing its source.", "source_missing")
    try:
        source = canvas_facade.get_notebook_canvas_source(
            team_id=notebook.team_id,
            canvas_id=row.canvas_id,
            version_id=version_id or row.source_version_id,
        )
    except canvas_facade.NotebookCanvasNotFoundError as error:
        raise GenUIError("This visualization version is no longer available.", "version_missing") from error
    except canvas_facade.NotebookCanvasSourceUnavailableError as error:
        raise GenUIError(
            "The visualization source is temporarily unavailable. Try again.", "source_unavailable"
        ) from error
    return GenUISource(version_id=source.version_id, source=source.source)


def list_genui_versions(*, notebook: Notebook, node_id: str) -> list[GenUIVersion]:
    row = NotebookGenUI.objects.for_team(notebook.team_id).filter(notebook=notebook, node_id=node_id).first()
    if row is None or row.canvas_id is None:
        return []
    try:
        versions = canvas_facade.list_notebook_canvas_versions(team_id=notebook.team_id, canvas_id=row.canvas_id)
    except canvas_facade.NotebookCanvasNotFoundError as error:
        raise GenUIError("This visualization is no longer available.", "canvas_missing") from error
    return [
        GenUIVersion(
            id=version.id,
            prompt=version.prompt,
            created_at=version.created_at,
            is_current=version.id == row.source_version_id,
        )
        for version in versions
    ]


def restore_genui_version(
    *, notebook: Notebook, node_id: str, version_id: UUID, user_id: int
) -> tuple[NotebookGenUI, GenUIInputInspection]:
    row, inspection = refresh_genui(notebook=notebook, node_id=node_id)
    if row.lifecycle_status in _ACTIVE_LIFECYCLES:
        raise GenUIConflictError("Wait for the current visualization update to finish.", "update_in_progress")
    if row.canvas_id is None or row.source_version_id is None or not row.generated_hash:
        raise GenUIConflictError("Generate this visualization before choosing a version.", "source_missing")
    if version_id == row.source_version_id:
        return row, inspection
    try:
        canvas_facade.restore_notebook_canvas_version(
            team_id=notebook.team_id,
            canvas_id=row.canvas_id,
            version_id=version_id,
            expected_current_version_id=row.source_version_id,
            user_id=user_id,
        )
    except canvas_facade.NotebookCanvasNotFoundError as error:
        raise GenUIError("This visualization version is no longer available.", "version_missing") from error
    except canvas_facade.NotebookCanvasVersionConflictError as error:
        raise GenUIConflictError(
            "The visualization changed while this version was selected. Reload the versions and try again.",
            "version_conflict",
        ) from error
    except canvas_facade.NotebookCanvasBuildCapacityError as error:
        raise GenUIRateLimitError(
            "Visualization builds are busy. Try switching versions again shortly.", "build_capacity_exhausted"
        ) from error

    row.pending_generation_hash = row.generated_hash
    row.pending_schema_hash = row.generated_schema_hash or inspection.schema_hash
    row.lifecycle_status = NotebookGenUI.LifecycleStatus.BUILDING
    row.generation_started_at = timezone.now()
    row.last_error_code = None
    row.last_error = None
    row.save(
        update_fields=[
            "pending_generation_hash",
            "pending_schema_hash",
            "lifecycle_status",
            "generation_started_at",
            "last_error_code",
            "last_error",
            "updated_at",
        ]
    )
    return row, inspection


def read_genui_frame(*, notebook: Notebook, node_id: str, frame_name: str) -> dict[str, object]:
    row = NotebookGenUI.objects.for_team(notebook.team_id).filter(notebook=notebook, node_id=node_id).first()
    if row is None or not row.snapshot_object_key:
        _otel.counter("notebooks.genui.frame_read.rejected").add(1, {"reason": "snapshot_missing"})
        raise GenUIError(
            "The visualization data snapshot is unavailable. Run the visualization again.", "snapshot_missing"
        )
    if frame_name not in cast(list[str], row.inputs):
        _otel.counter("notebooks.genui.frame_read.rejected").add(1, {"reason": "frame_not_allowed"})
        raise GenUIError("This visualization is not allowed to read that dataframe.", "frame_not_allowed")
    try:
        snapshot = read_snapshot(key=row.snapshot_object_key, team_id=notebook.team_id)
    except GenUISnapshotStoreError as error:
        _otel.counter("notebooks.genui.frame_read.rejected").add(1, {"reason": "snapshot_unavailable"})
        raise GenUIError(str(error), "snapshot_unavailable") from error
    frame = snapshot.get(frame_name)
    if not isinstance(frame, dict):
        raise GenUIError("The requested dataframe is not in this snapshot.", "frame_missing")
    return cast(dict[str, object], frame)


def status_payload(
    row: NotebookGenUI, inspection: GenUIInputInspection, *, artifact_url: str | None = None
) -> GenUIStatus:
    canvas = (
        canvas_facade.get_canvas_generation_state(team_id=row.team_id, canvas_id=row.canvas_id)
        if row.canvas_id
        else None
    )
    resolved_artifact_url = artifact_url or (canvas.published_artifact_url if canvas else None)
    staleness_reason: str | None = None
    if row.lifecycle_status == NotebookGenUI.LifecycleStatus.STALE:
        staleness_reason = "upstream_runs_changed"
    elif row.lifecycle_status == NotebookGenUI.LifecycleStatus.INCOMPATIBLE:
        staleness_reason = "prompt_or_schema_changed"
    return GenUIStatus(
        node_id=row.node_id,
        lifecycle_status=row.lifecycle_status,
        staleness_reason=staleness_reason,
        error_code=row.last_error_code,
        error_detail=row.last_error,
        artifact_url=resolved_artifact_url,
        frame_names=cast(list[str], row.inputs),
        source_version_id=row.source_version_id,
        build_id=row.build_id,
        input_states=inspection.states,
        can_run=row.lifecycle_status == NotebookGenUI.LifecycleStatus.STALE,
        can_regenerate=row.lifecycle_status
        in {
            NotebookGenUI.LifecycleStatus.READY,
            NotebookGenUI.LifecycleStatus.STALE,
            NotebookGenUI.LifecycleStatus.INCOMPATIBLE,
            NotebookGenUI.LifecycleStatus.FAILED,
        },
        can_retry=row.lifecycle_status == NotebookGenUI.LifecycleStatus.FAILED,
        created_at=row.created_at,
        updated_at=row.updated_at,
        generated_at=row.generated_at,
        snapshot_updated_at=row.snapshot_updated_at,
    )


def _cleanup_external_genui_state(*, team_id: int, snapshot_keys: list[str], canvas_id: UUID | None) -> None:
    for key in snapshot_keys:
        try:
            delete_snapshot(key=key, team_id=team_id)
        except Exception:
            logger.warning("notebook_genui_snapshot_cleanup_failed", team_id=team_id, exc_info=True)
    if canvas_id:
        canvas_facade.soft_delete_notebook_canvas(team_id=team_id, canvas_id=canvas_id)


def cleanup_removed_genui_nodes(notebook: Notebook, *, delete_all: bool = False) -> None:
    markdown = _get_markdown_notebook_markdown(notebook.content)
    live_node_ids: set[str] = set()
    if not delete_all and not notebook.deleted:
        if markdown is None:
            return
        for tag_name, raw, _next_line_index in _iter_markdown_component_blocks(markdown):
            if tag_name != "GenUI":
                continue
            node_id = _parse_markdown_component_props(raw).get("nodeId")
            if isinstance(node_id, str) and node_id:
                live_node_ids.add(node_id)

    rows = NotebookGenUI.objects.for_team(notebook.team_id).filter(notebook=notebook)
    if live_node_ids:
        rows = rows.exclude(node_id__in=live_node_ids)
    for row in rows:
        snapshot_keys = [
            cast(str, key) for key in {row.snapshot_object_key, row.pending_snapshot_object_key} if key is not None
        ]
        canvas_id = row.canvas_id
        if not delete_all:
            row.delete()
        transaction.on_commit(
            partial(
                _cleanup_external_genui_state,
                team_id=notebook.team_id,
                snapshot_keys=snapshot_keys,
                canvas_id=canvas_id,
            )
        )
