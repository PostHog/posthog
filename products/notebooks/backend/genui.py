import re
import json
import math
from collections.abc import Callable
from time import monotonic
from uuid import UUID

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen

from products.notebooks.backend.models import Notebook, NotebookGenUI, NotebookNodeRun
from products.notebooks.backend.sql_v2_state import extract_cells
from products.notebooks.backend.util import (
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
    return normalized


def assert_genui_node_exists(notebook: Notebook, node_id: str) -> None:
    markdown = _get_markdown_notebook_markdown(notebook.content)
    if markdown is not None:
        for tag_name, raw, _next_line_index in _iter_markdown_component_blocks(markdown):
            if tag_name == "GenUI" and _parse_markdown_component_props(raw).get("nodeId") == node_id:
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
) -> GenUIStatus:
    from products.canvas.backend import (
        notebook_integration as canvas_facade,  # noqa: PLC0415 — keeps Canvas build imports off the notebook API import path
    )
    from products.notebooks.backend.genui_generation import (  # noqa: PLC0415 — keeps the OpenAI SDK off the notebook API import path
        GenUISourceGenerationCancelled,
        GenUISourceGenerationError,
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
                prompt=normalized_prompt,
                schemas=inspection.schemas,
                input_names=normalized_inputs,
                model=model,
                is_cancelled=is_cancelled,
            )
        except GenUISourceGenerationCancelled as error:
            raise GenUIError("Visualization generation was canceled.", "generation_canceled") from error
        except GenUISourceGenerationError as error:
            raise GenUIError("The visualization could not be generated. Try again.", "generation_failed") from error

        if cache.get(cancellation_key):
            raise GenUIError("Visualization generation was canceled.", "generation_canceled")
        assert_genui_node_exists(notebook, node_id)
        row = _get_or_create_canvas(
            notebook=notebook,
            node_id=node_id,
            inputs=normalized_inputs,
            prompt=normalized_prompt,
            user_id=user_id,
        )
        canvas_id = row.canvas_id
        if canvas_id is None:
            raise GenUIError("The visualization could not be prepared. Try again.", "canvas_missing")
        state = canvas_facade.get_canvas_generation_state(team_id=notebook.team_id, canvas_id=canvas_id)
        if state is None:
            raise GenUIError("The visualization could not be prepared. Try again.", "canvas_missing")
        if cache.get(cancellation_key):
            raise GenUIError("Visualization generation was canceled.", "generation_canceled")
        try:
            canvas_facade.publish_notebook_canvas_source(
                team_id=notebook.team_id,
                canvas_id=canvas_id,
                user_id=user_id,
                source=source,
                input_names=normalized_inputs,
                prompt=normalized_prompt,
                name=_display_name(normalized_prompt),
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
        return get_genui_status(notebook=notebook, node_id=node_id)
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
        )
    state = canvas_facade.get_canvas_generation_state(team_id=notebook.team_id, canvas_id=row.canvas_id)
    if state is None:
        return GenUIStatus(
            lifecycle_status="failed",
            error_detail="The visualization no longer exists. Generate it again.",
            artifact_url=None,
            frame_names=row.inputs,
        )
    if (
        state.current_source_version_id is not None
        and state.current_source_version_id == state.published_source_version_id
        and state.artifact_url is not None
    ):
        return GenUIStatus(
            lifecycle_status="ready",
            error_detail=None,
            artifact_url=state.artifact_url,
            frame_names=row.inputs,
        )
    if state.build_status == "failed":
        return GenUIStatus(
            lifecycle_status="failed",
            error_detail="The visualization could not be built. Generate it again.",
            artifact_url=None,
            frame_names=row.inputs,
        )
    return GenUIStatus(
        lifecycle_status="building",
        error_detail=None,
        artifact_url=None,
        frame_names=row.inputs,
    )


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
