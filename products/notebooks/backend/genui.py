import re
import json
import math
from collections.abc import Callable
from datetime import datetime, timedelta
from time import monotonic
from uuid import UUID

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen

from products.notebooks.backend.models import Notebook, NotebookGenUI, NotebookGenUIVersion, NotebookNodeRun
from products.notebooks.backend.sql_v2_state import extract_cells
from products.notebooks.backend.util import (
    _create_stable_markdown_node_id,
    _get_markdown_component_fingerprint,
    _get_markdown_notebook_markdown,
    _iter_markdown_component_blocks,
    _parse_markdown_component_props,
)

MAX_INPUT_NAME_LENGTH = 128
MAX_PROMPT_LENGTH = 20_000
MAX_COLUMNS = 100
MAX_ROWS = 100
MAX_CELL_STRING_LENGTH = 4_096
MAX_FRAME_BYTES = 512 * 1_024
MAX_GENERATIONS_PER_USER_PER_MINUTE = 5
GENERATION_CANCELLATION_TTL_SECONDS = 60 * 10

_INPUT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class GenUIError(Exception):
    def __init__(self, detail: str, code: str) -> None:
        super().__init__(detail)
        self.detail = detail
        self.code = code


class GenUIConflictError(GenUIError):
    pass


class GenUIRateLimitError(GenUIError):
    pass


@frozen
class GenUIResolvedInput:
    name: str
    run: NotebookNodeRun
    columns: list[dict[str, str]]
    total_row_count: int


@frozen
class GenUIInputInspection:
    resolved_inputs: list[GenUIResolvedInput]

    @property
    def schemas(self) -> list[dict[str, object]]:
        return [
            {
                "name": item.name,
                "columns": item.columns,
                "totalRowCount": item.total_row_count,
            }
            for item in self.resolved_inputs
        ]


@frozen
class GenUIFrameRead:
    run: NotebookNodeRun
    frame: dict[str, object]


@frozen
class GenUIStatus:
    lifecycle_status: str
    error_detail: str | None
    artifact_url: str | None
    frame_names: list[str]
    generation_started_at: datetime | None
    generation_id: UUID | None
    current_version_id: UUID | None
    versions: list["GenUIVersion"]


@frozen
class GenUIVersion:
    id: UUID
    parent_version_id: UUID | None
    version: int
    operation: str
    prompt: str
    effective_prompt: str
    model: str | None
    created_at: datetime
    build_status: str | None
    artifact_url: str | None


@frozen
class GenUISource:
    version_id: UUID
    current_version_id: UUID
    source: str


def normalize_prompt(prompt: str) -> str:
    normalized = prompt.strip()
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
    return normalized


def assert_genui_node_exists(notebook: Notebook, node_id: str) -> None:
    markdown = _get_markdown_notebook_markdown(notebook.content)
    if markdown is not None:
        occurrences: dict[str, int] = {}
        for tag_name, raw, _next_line_index in _iter_markdown_component_blocks(markdown):
            if tag_name != "GenUI":
                continue
            props = _parse_markdown_component_props(raw)
            fingerprint = _get_markdown_component_fingerprint(tag_name, props)
            occurrence = occurrences.get(fingerprint, 0)
            occurrences[fingerprint] = occurrence + 1
            explicit_node_id = props.get("nodeId")
            resolved_node_id = (
                explicit_node_id
                if isinstance(explicit_node_id, str) and explicit_node_id
                else _create_stable_markdown_node_id(fingerprint, occurrence)
            )
            if resolved_node_id == node_id:
                return
    raise GenUIError("This generated visualization is no longer in the notebook.", "node_not_found")


def _dataframe_owners(notebook: Notebook) -> dict[str, str]:
    cells = extract_cells(notebook.content)
    eligible_cells = [cell for cell in cells if _INPUT_NAME.fullmatch(cell.dataframe_name)]
    preferred_owners: dict[str, str] = {}
    for cell_type in ("sql", "python"):
        for cell in eligible_cells:
            if cell.cell_type == cell_type:
                preferred_owners.setdefault(cell.dataframe_name, cell.node_id)
    owners: dict[str, str] = {}
    for cell in eligible_cells:
        if preferred_owners[cell.dataframe_name] == cell.node_id:
            owners.setdefault(cell.dataframe_name, cell.node_id)
    return owners


def infer_genui_inputs(notebook: Notebook, node_id: str) -> list[str]:
    assert_genui_node_exists(notebook, node_id)
    return list(_dataframe_owners(notebook))


def _columns_from_run(run: NotebookNodeRun) -> list[dict[str, str]]:
    envelope = run.envelope if isinstance(run.envelope, dict) else {}
    raw_types = envelope.get("types")
    columns: list[dict[str, str]] = []
    if isinstance(raw_types, list):
        for pair in raw_types[:MAX_COLUMNS]:
            if isinstance(pair, list | tuple) and len(pair) >= 2:
                columns.append({"name": str(pair[0])[:256], "type": str(pair[1])[:256]})
    if not columns and isinstance(raw_columns := envelope.get("columns"), list):
        columns = [{"name": str(column)[:256], "type": "unknown"} for column in raw_columns[:MAX_COLUMNS]]
    return columns


def _total_row_count(run: NotebookNodeRun) -> int:
    envelope = run.envelope if isinstance(run.envelope, dict) else {}
    row_count = envelope.get("row_count")
    if isinstance(row_count, int) and row_count >= 0:
        return row_count
    rows = envelope.get("first_page")
    return len(rows) if isinstance(rows, list) else 0


def inspect_genui_inputs(
    notebook: Notebook,
    inputs: list[str],
    authorize_run: Callable[[NotebookNodeRun], None],
    node_id: str | None = None,
    require_all: bool = True,
) -> GenUIInputInspection:
    normalized_inputs = normalize_inputs(inputs)
    if node_id is not None:
        assert_genui_node_exists(notebook, node_id)
    owners = _dataframe_owners(notebook)
    missing = [name for name in normalized_inputs if name not in owners]
    if missing:
        raise GenUIConflictError(
            f'Dataframe "{missing[0]}" is not exported by a SQL or Python cell.',
            "input_missing",
        )

    node_ids = [owners[name] for name in normalized_inputs]
    latest_runs = {
        run.node_id: run
        for run in NotebookNodeRun.objects.for_team(notebook.team_id)
        .filter(notebook=notebook, node_id__in=node_ids, status=NotebookNodeRun.Status.DONE)
        .order_by("node_id", "-created_at")
        .distinct("node_id")
    }
    unresolved = [name for name in normalized_inputs if owners[name] not in latest_runs]
    if unresolved and require_all:
        raise GenUIConflictError(
            f'Run the cell that exports "{unresolved[0]}" before generating this visualization.',
            "input_not_ready",
        )

    resolved_inputs = [
        GenUIResolvedInput(
            name=name,
            run=latest_runs[owners[name]],
            columns=_columns_from_run(latest_runs[owners[name]]),
            total_row_count=_total_row_count(latest_runs[owners[name]]),
        )
        for name in normalized_inputs
        if owners[name] in latest_runs
    ]
    for resolved in resolved_inputs:
        authorize_run(resolved.run)
    return GenUIInputInspection(resolved_inputs=resolved_inputs)


def _safe_cell(value: object) -> object:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:MAX_CELL_STRING_LENGTH]
    return json.dumps(value, default=str, separators=(",", ":"))[:MAX_CELL_STRING_LENGTH]


def _frame_from_run(name: str, run: NotebookNodeRun) -> dict[str, object]:
    envelope = run.envelope if isinstance(run.envelope, dict) else {}
    columns = _columns_from_run(run)
    raw_rows = envelope.get("first_page")
    candidates = raw_rows[:MAX_ROWS] if isinstance(raw_rows, list) else []
    rows: list[list[object]] = []
    base_size = len(json.dumps({"name": name, "columns": columns}, separators=(",", ":")).encode())
    used_bytes = base_size
    for raw_row in candidates:
        if not isinstance(raw_row, list):
            continue
        row = [_safe_cell(value) for value in raw_row[: len(columns)]]
        row_size = len(json.dumps(row, separators=(",", ":")).encode())
        if used_bytes + row_size > MAX_FRAME_BYTES:
            break
        rows.append(row)
        used_bytes += row_size

    total_row_count = _total_row_count(run)
    return {
        "name": name,
        "columns": columns,
        "rows": rows,
        "totalRowCount": total_row_count,
        "includedRowCount": len(rows),
        "truncated": len(rows) < total_row_count or len(rows) < len(candidates),
    }


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
        raise GenUIRateLimitError("Too many visualizations were generated. Try again in a minute.", "rate_limited")


def _generation_cancellation_key(
    *, team_id: int, user_id: int, notebook_id: UUID, node_id: str, generation_id: UUID
) -> str:
    return f"notebook_genui_cancel:{team_id}:{user_id}:{notebook_id}:{node_id}:{generation_id}"


def cancel_genui_generation(*, notebook: Notebook, node_id: str, generation_id: UUID, user_id: int) -> None:
    assert_genui_node_exists(notebook, node_id)
    cache.set(
        _generation_cancellation_key(
            team_id=notebook.team_id,
            user_id=user_id,
            notebook_id=notebook.id,
            node_id=node_id,
            generation_id=generation_id,
        ),
        True,
        timeout=GENERATION_CANCELLATION_TTL_SECONDS,
    )


def _is_ai_usage_limited(team_api_token: str) -> bool:
    from ee.billing.quota_limiting import (  # noqa: PLC0415 — avoids loading the billing query stack at startup
        is_team_over_ai_credit_budget,
    )

    return is_team_over_ai_credit_budget(team_api_token)


def _display_name(prompt: str) -> str:
    return prompt if len(prompt) <= 80 else f"{prompt[:77].rstrip()}..."


def _get_or_create_canvas(
    *, notebook: Notebook, node_id: str, inputs: list[str], prompt: str, user_id: int
) -> NotebookGenUI:
    from products.canvas.backend import (
        notebook_integration as canvas_facade,  # noqa: PLC0415 — keeps Canvas build imports off the notebook API import path
    )
    from products.tasks.backend.facade import (  # noqa: PLC0415 — keeps the Tasks facade off the notebook API import path
        api as tasks_facade,
    )

    channel_id = tasks_facade.ensure_personal_channel_id(team_id=notebook.team_id, user_id=user_id)
    with transaction.atomic():
        row, _created = (
            NotebookGenUI.objects.for_team(notebook.team_id)
            .select_for_update()
            .get_or_create(
                notebook=notebook,
                node_id=node_id,
                defaults={
                    "team_id": notebook.team_id,
                    "inputs": inputs,
                    "generator_version": "3",
                    "generation_hash": "",
                },
            )
        )
        if row.canvas_id is None or not canvas_facade.update_notebook_canvas(
            team_id=notebook.team_id,
            canvas_id=row.canvas_id,
            context=prompt,
        ):
            row.canvas_id = canvas_facade.create_notebook_canvas(
                team_id=notebook.team_id,
                user_id=user_id,
                channel_id=channel_id,
                name=_display_name(prompt),
                context=prompt,
            )
        row.inputs = inputs
        row.save(update_fields=["canvas_id", "inputs", "updated_at"])
        return row


def _combined_prompt(base_prompt: str, addition: str) -> str:
    if not base_prompt:
        return addition
    if not addition:
        return base_prompt
    return f"{base_prompt}\n\nAdditional change:\n{addition}"


def _version_effective_prompt(row: NotebookGenUI, version_id: UUID) -> str:
    metadata = (
        NotebookGenUIVersion.objects.for_team(row.team_id)
        .filter(genui=row, canvas_source_version_id=version_id)
        .first()
    )
    if metadata is not None:
        return metadata.effective_prompt
    if row.canvas_id is not None:
        from products.canvas.backend import (
            notebook_integration as canvas_facade,  # noqa: PLC0415 — keeps Canvas source storage imports off the notebook API import path
        )

        for version in canvas_facade.list_notebook_canvas_versions(team_id=row.team_id, canvas_id=row.canvas_id):
            if version.id == version_id:
                return version.prompt or ""
    return row.prompt


def _version_history(row: NotebookGenUI) -> list[GenUIVersion]:
    from products.canvas.backend import (
        notebook_integration as canvas_facade,  # noqa: PLC0415 — keeps Canvas build imports off the notebook API import path
    )

    if row.canvas_id is None:
        return []
    canvas_versions = canvas_facade.list_notebook_canvas_versions(team_id=row.team_id, canvas_id=row.canvas_id)
    metadata_by_version = {
        item.canvas_source_version_id: item
        for item in NotebookGenUIVersion.objects.for_team(row.team_id).filter(genui=row)
    }
    history: list[GenUIVersion] = []
    for index, canvas_version in enumerate(canvas_versions, start=1):
        metadata = metadata_by_version.get(canvas_version.id)
        prompt = metadata.prompt if metadata is not None else canvas_version.prompt or ""
        history.append(
            GenUIVersion(
                id=canvas_version.id,
                parent_version_id=canvas_version.parent_version_id,
                version=index,
                operation=(
                    metadata.operation
                    if metadata is not None
                    else NotebookGenUIVersion.Operation.INITIAL
                    if index == 1
                    else NotebookGenUIVersion.Operation.REGENERATE
                ),
                prompt=prompt,
                effective_prompt=metadata.effective_prompt if metadata is not None else prompt,
                model=metadata.model if metadata is not None and metadata.model else None,
                created_at=canvas_version.created_at,
                build_status=canvas_version.build_status,
                artifact_url=canvas_version.artifact_url,
            )
        )
    return history


def _record_generation_failure(row: NotebookGenUI, generation_id: UUID, error: GenUIError) -> None:
    NotebookGenUI.objects.for_team(row.team_id).filter(id=row.id, generation_task_id=generation_id).update(
        lifecycle_status=NotebookGenUI.LifecycleStatus.FAILED,
        last_error_code=error.code,
        last_error=error.detail,
        generation_task_id=None,
        updated_at=timezone.now(),
    )


def generate_genui(
    *,
    notebook: Notebook,
    node_id: str,
    prompt: str,
    inputs: list[str],
    user_id: int,
    inspection: GenUIInputInspection,
    model: str,
    generation_id: UUID,
    operation: str,
) -> GenUIStatus:
    from products.canvas.backend import (
        notebook_integration as canvas_facade,  # noqa: PLC0415 — keeps Canvas build imports off the notebook API import path
    )
    from products.notebooks.backend.genui_generation import (  # noqa: PLC0415 — keeps the OpenAI SDK off the notebook API import path
        GenUISourceGenerationCancelled,
        GenUISourceGenerationError,
        GenUISourceGenerationTimedOut,
        generate_genui_source,
    )

    assert_genui_node_exists(notebook, node_id)
    normalized_prompt = normalize_prompt(prompt)
    normalized_inputs = normalize_inputs(inputs)
    if [item.name for item in inspection.resolved_inputs] != normalized_inputs:
        raise GenUIConflictError("The visualization inputs changed. Try generating it again.", "inputs_changed")
    _check_generation_rate(notebook.team_id, user_id)
    if _is_ai_usage_limited(notebook.team.api_token):
        raise GenUIRateLimitError(
            "Visualization generation is unavailable because this project's AI usage limit has been reached.",
            "usage_limit_exceeded",
        )

    row = _get_or_create_canvas(
        notebook=notebook,
        node_id=node_id,
        inputs=normalized_inputs,
        prompt=normalized_prompt,
        user_id=user_id,
    )
    now = timezone.now()
    with transaction.atomic():
        locked_row = NotebookGenUI.objects.for_team(notebook.team_id).select_for_update().get(id=row.id)
        if (
            locked_row.lifecycle_status == NotebookGenUI.LifecycleStatus.GENERATING
            and locked_row.generation_task_id is not None
            and locked_row.generation_task_id != generation_id
            and locked_row.generation_started_at is not None
            and locked_row.generation_started_at > now - timedelta(minutes=10)
        ):
            raise GenUIConflictError(
                "This visualization is already being generated. Cancel it before starting another generation.",
                "generation_in_progress",
            )
        locked_row.lifecycle_status = NotebookGenUI.LifecycleStatus.GENERATING
        locked_row.generation_task_id = generation_id
        locked_row.generation_started_at = now
        locked_row.last_error_code = None
        locked_row.last_error = None
        locked_row.save(
            update_fields=[
                "lifecycle_status",
                "generation_task_id",
                "generation_started_at",
                "last_error_code",
                "last_error",
                "updated_at",
            ]
        )
        row = locked_row

    base_source: str | None = None
    change_prompt: str | None = None
    effective_prompt = normalized_prompt
    resolved_operation = operation
    if row.canvas_id is None:
        error = GenUIError("The visualization could not be prepared. Try again.", "canvas_missing")
        _record_generation_failure(row, generation_id, error)
        raise error
    state = canvas_facade.get_canvas_generation_state(team_id=notebook.team_id, canvas_id=row.canvas_id)
    if operation == NotebookGenUIVersion.Operation.IMPROVE:
        if state is None or state.current_source_version_id is None or row.canvas_id is None:
            error = GenUIError("Generate the visualization before improving it.", "version_missing")
            _record_generation_failure(row, generation_id, error)
            raise error
        try:
            base_source = canvas_facade.get_notebook_canvas_source(
                team_id=notebook.team_id,
                canvas_id=row.canvas_id,
                version_id=state.current_source_version_id,
            ).source
        except canvas_facade.NotebookCanvasError as source_error:
            error = GenUIError("The visualization source is unavailable. Regenerate it instead.", "source_unavailable")
            _record_generation_failure(row, generation_id, error)
            raise error from source_error
        change_prompt = normalized_prompt
        effective_prompt = _combined_prompt(
            _version_effective_prompt(row, state.current_source_version_id),
            change_prompt,
        )
    elif state is None or state.current_source_version_id is None:
        resolved_operation = NotebookGenUIVersion.Operation.INITIAL
    else:
        resolved_operation = NotebookGenUIVersion.Operation.REGENERATE

    cancellation_key = _generation_cancellation_key(
        team_id=notebook.team_id,
        user_id=user_id,
        notebook_id=notebook.id,
        node_id=node_id,
        generation_id=generation_id,
    )
    cancellation_checked_at = 0.0
    cancellation_requested = False

    def is_cancelled() -> bool:
        nonlocal cancellation_checked_at, cancellation_requested
        checked_at = monotonic()
        if checked_at - cancellation_checked_at >= 0.25:
            cancellation_requested = bool(cache.get(cancellation_key))
            cancellation_checked_at = checked_at
        return cancellation_requested

    try:
        try:
            source = generate_genui_source(
                team_id=notebook.team_id,
                trace_id=f"notebook-genui-{notebook.id}-{node_id}-{generation_id}",
                prompt=effective_prompt,
                schemas=inspection.schemas,
                input_names=normalized_inputs,
                model=model,
                is_cancelled=is_cancelled,
                base_source=base_source,
                change_prompt=change_prompt,
            )
        except GenUISourceGenerationCancelled as error:
            raise GenUIError("Visualization generation was canceled.", "generation_canceled") from error
        except GenUISourceGenerationTimedOut as error:
            raise GenUIError(
                "Visualization generation took too long. Try a faster model or a more focused prompt.",
                "generation_timed_out",
            ) from error
        except GenUISourceGenerationError as error:
            raise GenUIError("The visualization could not be generated. Try again.", "generation_failed") from error

        if cache.get(cancellation_key):
            raise GenUIError("Visualization generation was canceled.", "generation_canceled")
        assert_genui_node_exists(notebook, node_id)
        canvas_id = row.canvas_id
        if canvas_id is None:
            raise GenUIError("The visualization could not be prepared. Try again.", "canvas_missing")
        state = canvas_facade.get_canvas_generation_state(team_id=notebook.team_id, canvas_id=canvas_id)
        if state is None:
            raise GenUIError("The visualization could not be prepared. Try again.", "canvas_missing")
        if cache.get(cancellation_key):
            raise GenUIError("Visualization generation was canceled.", "generation_canceled")
        try:
            source_version_id, build_id = canvas_facade.publish_notebook_canvas_source(
                team_id=notebook.team_id,
                canvas_id=canvas_id,
                user_id=user_id,
                source=source,
                input_names=normalized_inputs,
                prompt=normalized_prompt,
                name=_display_name(effective_prompt),
                expected_current_version_id=state.current_source_version_id,
            )
        except canvas_facade.NotebookCanvasVersionConflictError as error:
            raise GenUIConflictError(
                "This visualization changed while it was being generated. Try again.", "generation_conflict"
            ) from error
        except canvas_facade.NotebookCanvasBuildCapacityError as error:
            raise GenUIRateLimitError(
                "Visualization build capacity is full. Try again shortly.", "build_capacity"
            ) from error
        except canvas_facade.NotebookCanvasError as error:
            raise GenUIError("The visualization could not be built. Try again.", "build_failed") from error
        NotebookGenUIVersion.objects.for_team(notebook.team_id).create(
            team_id=notebook.team_id,
            genui=row,
            canvas_source_version_id=source_version_id,
            operation=resolved_operation,
            prompt=normalized_prompt,
            effective_prompt=effective_prompt,
            model=model,
        )
        NotebookGenUI.objects.for_team(notebook.team_id).filter(id=row.id, generation_task_id=generation_id).update(
            prompt=effective_prompt,
            inputs=normalized_inputs,
            lifecycle_status=NotebookGenUI.LifecycleStatus.BUILDING,
            generation_task_id=None,
            source_version_id=source_version_id,
            build_id=build_id,
            last_error_code=None,
            last_error=None,
            updated_at=timezone.now(),
        )
        return get_genui_status(notebook=notebook, node_id=node_id)
    except GenUIError as error:
        _record_generation_failure(row, generation_id, error)
        raise
    finally:
        cache.delete(cancellation_key)


def get_genui_status(*, notebook: Notebook, node_id: str) -> GenUIStatus:
    from products.canvas.backend import (
        notebook_integration as canvas_facade,  # noqa: PLC0415 — keeps Canvas build imports off the notebook API import path
    )

    assert_genui_node_exists(notebook, node_id)
    row = NotebookGenUI.objects.for_team(notebook.team_id).filter(notebook=notebook, node_id=node_id).first()
    if row is None or row.canvas_id is None:
        return GenUIStatus(
            lifecycle_status="awaiting_generation",
            error_detail=None,
            artifact_url=None,
            frame_names=[],
            generation_started_at=None,
            generation_id=None,
            current_version_id=None,
            versions=[],
        )
    state = canvas_facade.get_canvas_generation_state(team_id=notebook.team_id, canvas_id=row.canvas_id)
    if state is None:
        return GenUIStatus(
            lifecycle_status="failed",
            error_detail="The visualization no longer exists. Generate it again.",
            artifact_url=None,
            frame_names=row.inputs,
            generation_started_at=row.generation_started_at,
            generation_id=row.generation_task_id,
            current_version_id=None,
            versions=[],
        )
    versions = _version_history(row)
    generation_is_active = (
        row.lifecycle_status == NotebookGenUI.LifecycleStatus.GENERATING
        and row.generation_task_id is not None
        and row.generation_started_at is not None
        and row.generation_started_at > timezone.now() - timedelta(minutes=10)
    )
    if generation_is_active:
        return GenUIStatus(
            lifecycle_status="generating",
            error_detail=None,
            artifact_url=state.artifact_url,
            frame_names=row.inputs,
            generation_started_at=row.generation_started_at,
            generation_id=row.generation_task_id,
            current_version_id=state.current_source_version_id,
            versions=versions,
        )
    if row.lifecycle_status == NotebookGenUI.LifecycleStatus.FAILED and row.last_error:
        return GenUIStatus(
            lifecycle_status="failed",
            error_detail=row.last_error,
            artifact_url=state.artifact_url,
            frame_names=row.inputs,
            generation_started_at=row.generation_started_at,
            generation_id=None,
            current_version_id=state.current_source_version_id,
            versions=versions,
        )
    if (
        state.current_source_version_id is not None
        and state.current_source_version_id == state.published_source_version_id
        and state.build_status == "ready"
    ):
        return GenUIStatus(
            lifecycle_status="ready",
            error_detail=None,
            artifact_url=state.artifact_url,
            frame_names=row.inputs,
            generation_started_at=row.generation_started_at,
            generation_id=None,
            current_version_id=state.current_source_version_id,
            versions=versions,
        )
    if state.build_status == "failed":
        error_detail = "The visualization could not be built. Edit the source or improve the current version."
        if state.build_error:
            error_detail = (
                f"The visualization could not be built: {state.build_error} "
                "Edit the source or improve the current version."
            )
        return GenUIStatus(
            lifecycle_status="failed",
            error_detail=error_detail,
            artifact_url=state.artifact_url,
            frame_names=row.inputs,
            generation_started_at=row.generation_started_at,
            generation_id=None,
            current_version_id=state.current_source_version_id,
            versions=versions,
        )
    return GenUIStatus(
        lifecycle_status="building",
        error_detail=None,
        artifact_url=state.artifact_url,
        frame_names=row.inputs,
        generation_started_at=row.generation_started_at,
        generation_id=None,
        current_version_id=state.current_source_version_id,
        versions=versions,
    )


def get_genui_source(*, notebook: Notebook, node_id: str, version_id: UUID | None = None) -> GenUISource:
    from products.canvas.backend import (
        notebook_integration as canvas_facade,  # noqa: PLC0415 — keeps Canvas source storage imports off the notebook API import path
    )

    assert_genui_node_exists(notebook, node_id)
    row = NotebookGenUI.objects.for_team(notebook.team_id).filter(notebook=notebook, node_id=node_id).first()
    if row is None or row.canvas_id is None:
        raise GenUIError("Generate the visualization before viewing its source.", "version_missing")
    state = canvas_facade.get_canvas_generation_state(team_id=notebook.team_id, canvas_id=row.canvas_id)
    if state is None or state.current_source_version_id is None:
        raise GenUIError("The visualization source is unavailable. Generate it again.", "source_unavailable")
    try:
        result = canvas_facade.get_notebook_canvas_source(
            team_id=notebook.team_id,
            canvas_id=row.canvas_id,
            version_id=version_id,
        )
    except canvas_facade.NotebookCanvasError as error:
        raise GenUIError("The visualization source is unavailable. Try again.", "source_unavailable") from error
    return GenUISource(
        version_id=result.version_id,
        current_version_id=state.current_source_version_id,
        source=result.source,
    )


def save_genui_source(
    *,
    notebook: Notebook,
    node_id: str,
    source: str,
    prompt: str,
    expected_current_version_id: UUID,
    inputs: list[str],
    user_id: int,
) -> GenUIStatus:
    from products.canvas.backend import (
        notebook_integration as canvas_facade,  # noqa: PLC0415 — keeps Canvas source storage imports off the notebook API import path
    )

    assert_genui_node_exists(notebook, node_id)
    normalized_prompt = normalize_prompt(prompt)
    normalized_inputs = normalize_inputs(inputs)
    row = NotebookGenUI.objects.for_team(notebook.team_id).filter(notebook=notebook, node_id=node_id).first()
    if row is None or row.canvas_id is None:
        raise GenUIError("Generate the visualization before editing its source.", "version_missing")
    state = canvas_facade.get_canvas_generation_state(team_id=notebook.team_id, canvas_id=row.canvas_id)
    if state is None or state.current_source_version_id != expected_current_version_id:
        raise GenUIConflictError(
            "This visualization changed while you were editing it. Reload the source and try again.",
            "generation_conflict",
        )
    try:
        source_version_id, build_id = canvas_facade.publish_notebook_canvas_source(
            team_id=notebook.team_id,
            canvas_id=row.canvas_id,
            user_id=user_id,
            source=source,
            input_names=normalized_inputs,
            prompt=normalized_prompt,
            name=_display_name(row.prompt or normalized_prompt),
            expected_current_version_id=expected_current_version_id,
        )
    except canvas_facade.NotebookCanvasVersionConflictError as error:
        raise GenUIConflictError(
            "This visualization changed while you were editing it. Reload the source and try again.",
            "generation_conflict",
        ) from error
    except canvas_facade.NotebookCanvasBuildCapacityError as error:
        raise GenUIRateLimitError(
            "Visualization build capacity is full. Try again shortly.", "build_capacity"
        ) from error
    except canvas_facade.NotebookCanvasError as error:
        raise GenUIError(
            "The visualization source could not be saved. Check the source and try again.", "source_invalid"
        ) from error

    parent_metadata = (
        NotebookGenUIVersion.objects.for_team(notebook.team_id)
        .filter(genui=row, canvas_source_version_id=expected_current_version_id)
        .first()
    )
    effective_prompt = (
        parent_metadata.effective_prompt
        if parent_metadata is not None
        else _version_effective_prompt(row, expected_current_version_id)
    )
    NotebookGenUIVersion.objects.for_team(notebook.team_id).create(
        team_id=notebook.team_id,
        genui=row,
        canvas_source_version_id=source_version_id,
        operation=NotebookGenUIVersion.Operation.SOURCE_EDIT,
        prompt=normalized_prompt,
        effective_prompt=effective_prompt,
        model=parent_metadata.model if parent_metadata is not None else "",
    )
    NotebookGenUI.objects.for_team(notebook.team_id).filter(id=row.id).update(
        inputs=normalized_inputs,
        lifecycle_status=NotebookGenUI.LifecycleStatus.BUILDING,
        source_version_id=source_version_id,
        build_id=build_id,
        generation_started_at=timezone.now(),
        last_error_code=None,
        last_error=None,
        updated_at=timezone.now(),
    )
    return get_genui_status(notebook=notebook, node_id=node_id)


def revert_genui_version(
    *,
    notebook: Notebook,
    node_id: str,
    version_id: UUID,
    expected_current_version_id: UUID,
    user_id: int,
) -> GenUIStatus:
    from products.canvas.backend import (
        notebook_integration as canvas_facade,  # noqa: PLC0415 — keeps Canvas source storage imports off the notebook API import path
    )

    assert_genui_node_exists(notebook, node_id)
    row = NotebookGenUI.objects.for_team(notebook.team_id).filter(notebook=notebook, node_id=node_id).first()
    if row is None or row.canvas_id is None:
        raise GenUIError("Generate the visualization before restoring a version.", "version_missing")
    try:
        build_id = canvas_facade.revert_notebook_canvas(
            team_id=notebook.team_id,
            canvas_id=row.canvas_id,
            version_id=version_id,
            expected_current_version_id=expected_current_version_id,
            user_id=user_id,
        )
    except canvas_facade.NotebookCanvasVersionConflictError as error:
        raise GenUIConflictError(
            "This visualization changed before the version was restored. Reload and try again.",
            "generation_conflict",
        ) from error
    except canvas_facade.NotebookCanvasBuildCapacityError as error:
        raise GenUIRateLimitError(
            "Visualization build capacity is full. Try again shortly.", "build_capacity"
        ) from error
    except canvas_facade.NotebookCanvasError as error:
        raise GenUIError("That visualization version is no longer available.", "version_missing") from error

    NotebookGenUI.objects.for_team(notebook.team_id).filter(id=row.id).update(
        prompt=_version_effective_prompt(row, version_id),
        lifecycle_status=NotebookGenUI.LifecycleStatus.BUILDING,
        source_version_id=version_id,
        build_id=build_id,
        generation_started_at=timezone.now(),
        last_error_code=None,
        last_error=None,
        updated_at=timezone.now(),
    )
    return get_genui_status(notebook=notebook, node_id=node_id)


def read_genui_frame(
    *,
    notebook: Notebook,
    node_id: str,
    frame_name: str,
    authorize_run: Callable[[NotebookNodeRun], None],
) -> GenUIFrameRead:
    assert_genui_node_exists(notebook, node_id)
    row = NotebookGenUI.objects.for_team(notebook.team_id).filter(notebook=notebook, node_id=node_id).first()
    if row is None or frame_name not in row.inputs:
        raise GenUIError("This visualization cannot read that dataframe.", "frame_not_allowed")
    inspection = inspect_genui_inputs(notebook, [frame_name], authorize_run, node_id=node_id)
    resolved = inspection.resolved_inputs[0]
    return GenUIFrameRead(run=resolved.run, frame=_frame_from_run(frame_name, resolved.run))
