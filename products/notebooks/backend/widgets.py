import re
import json
import math
import hashlib
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from time import monotonic
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.notebooks.backend.models import (
    MAX_WIDGET_NODE_ID_LENGTH,
    GeneratedWidget,
    GeneratedWidgetGenerationJob,
    GeneratedWidgetVersion,
    Notebook,
    NotebookNodeRun,
    NotebookWidgetInstance,
)
from products.notebooks.backend.sql_v2 import SQLV2KernelNotRunning, SQLV2PageError, fetch_sql_v2_page
from products.notebooks.backend.sql_v2_state import extract_cells
from products.notebooks.backend.temporal.client import start_widget_generation_workflow
from products.notebooks.backend.util import (
    _create_stable_markdown_node_id,
    _get_markdown_component_fingerprint,
    _get_markdown_notebook_markdown,
    _iter_markdown_component_blocks,
    _parse_markdown_component_props,
)
from products.notebooks.backend.widget_models import MAX_WIDGET_EFFECTIVE_PROMPT_LENGTH, MAX_WIDGET_PROMPT_LENGTH

logger = logging.getLogger(__name__)

GENERATOR_VERSION = "4"
MAX_INPUT_NAME_LENGTH = 128
MAX_COLUMNS = 100
MAX_CELL_STRING_LENGTH = 4_096
MAX_FRAME_BYTES = 512 * 1_024
MAX_FRAME_PAGE_ROWS = 500
MAX_FRAME_TOTAL_ROWS = 5_000
MAX_GENERATIONS_PER_USER_PER_MINUTE = 5
MAX_ACTIVE_GENERATIONS_PER_TEAM = 3
JOB_STALE_AFTER = timedelta(minutes=10)
GENERATION_CANCELLATION_TTL_SECONDS = 60 * 15
MAX_SCHEMA_CONTEXT_BYTES = 64 * 1_024
MAX_INPUT_CONTRACT_BYTES = 512 * 1_024
NOTEBOOK_GENERATED_WIDGETS_FLAG = "notebook-generated-widgets"

_INPUT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class WidgetError(Exception):
    def __init__(self, detail: str, code: str) -> None:
        super().__init__(detail)
        self.detail = detail
        self.code = code


class WidgetConflictError(WidgetError):
    pass


class WidgetRateLimitError(WidgetError):
    pass


@frozen
class ResolvedWidgetInput:
    name: str
    run: NotebookNodeRun
    contract: dict[str, object]


@frozen
class WidgetInputInspection:
    resolved_inputs: list[ResolvedWidgetInput]

    @property
    def contract(self) -> list[dict[str, object]]:
        return [item.contract for item in self.resolved_inputs]

    @property
    def schema_hash(self) -> str:
        return _json_hash(self.contract)


@frozen
class WidgetJobState:
    id: UUID
    status: str
    phase: str
    model: str
    created_at: datetime
    started_at: datetime | None


@frozen
class WidgetSecurityFindingState:
    severity: str
    title: str
    details: str


@frozen
class WidgetSecurityReviewState:
    severity: str
    summary: str
    findings: list[WidgetSecurityFindingState]
    model: str
    review_version: str
    reviewed_at: datetime


@frozen
class WidgetStatus:
    lifecycle_status: str
    error_detail: str | None
    artifact_url: str | None
    frame_names: list[str]
    current_version_id: UUID | None
    widget_id: UUID | None
    instance_id: UUID | None
    has_versions: bool
    active_job: WidgetJobState | None
    security_review: WidgetSecurityReviewState | None
    error_code: str | None = None
    failure_phase: str | None = None
    build_hash: str | None = None


@frozen
class WidgetVersionSummary:
    id: UUID
    parent_version_id: UUID | None
    version: int
    operation: str
    prompt_delta: str
    effective_prompt: str
    model: str | None
    created_at: datetime
    build_status: str | None
    artifact_url: str | None
    frame_names: list[str]
    is_current: bool
    security_review: WidgetSecurityReviewState | None
    build_hash: str | None = None


@frozen
class WidgetVersionPage:
    results: list[WidgetVersionSummary]
    count: int
    next_offset: int | None


@frozen
class WidgetFrameRead:
    frame: dict[str, object]


def _json_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _json_size(value: object) -> int:
    return len(json.dumps(value, separators=(",", ":"), default=str).encode())


def _security_review_state(version: GeneratedWidgetVersion) -> WidgetSecurityReviewState | None:
    severity = version.security_review_severity
    reviewed_at = version.security_reviewed_at
    summary = version.security_review_summary
    model = version.security_review_model
    review_version = version.security_review_version
    raw_findings = version.security_review_findings
    severity_order = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    if (
        severity not in GeneratedWidgetVersion.SecurityReviewSeverity.values
        or reviewed_at is None
        or not isinstance(summary, str)
        or not summary
        or not isinstance(model, str)
        or not model
        or not isinstance(review_version, str)
        or not review_version
        or not isinstance(raw_findings, list)
    ):
        return None
    findings: list[WidgetSecurityFindingState] = []
    for item in raw_findings:
        if not isinstance(item, dict):
            return None
        finding_severity = item.get("severity")
        title = item.get("title")
        details = item.get("details")
        if (
            finding_severity not in severity_order
            or not isinstance(title, str)
            or not title
            or not isinstance(details, str)
            or not details
        ):
            return None
        findings.append(
            WidgetSecurityFindingState(
                severity=str(finding_severity),
                title=title,
                details=details,
            )
        )
    if severity == GeneratedWidgetVersion.SecurityReviewSeverity.NONE:
        if findings:
            return None
    elif not findings or max(severity_order[finding.severity] for finding in findings) != severity_order[severity]:
        return None
    return WidgetSecurityReviewState(
        severity=severity,
        summary=summary,
        findings=findings,
        model=model,
        review_version=review_version,
        reviewed_at=reviewed_at,
    )


def normalize_widget_prompt(prompt: str, operation: str) -> str:
    normalized = prompt.strip()
    if not normalized:
        raise WidgetError("Add instructions before generating the widget.", "missing_prompt")
    max_length = (
        MAX_WIDGET_EFFECTIVE_PROMPT_LENGTH
        if operation == GeneratedWidgetVersion.Operation.REGENERATE
        else MAX_WIDGET_PROMPT_LENGTH
    )
    if len(normalized) > max_length:
        raise WidgetError(f"Keep widget instructions to {max_length:,} characters or fewer.", "prompt_too_long")
    return normalized


def normalize_widget_inputs(inputs: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_name in inputs:
        name = raw_name.strip()
        if not name or len(name) > MAX_INPUT_NAME_LENGTH or not _INPUT_NAME.fullmatch(name):
            raise WidgetError(f'"{raw_name}" is not a valid dataframe name.', "invalid_input_name")
        if name in seen:
            raise WidgetError(f'Dataframe "{name}" is listed more than once.', "duplicate_input_name")
        seen.add(name)
        normalized.append(name)
    return normalized


def _widget_node_ids(content: object) -> set[str]:
    node_ids: set[str] = set()
    markdown = _get_markdown_notebook_markdown(content)
    if markdown is not None:
        occurrences: dict[str, int] = {}
        for tag_name, raw, _next_line_index in _iter_markdown_component_blocks(markdown):
            if tag_name != "Widget":
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
            node_ids.add(resolved_node_id)
    return node_ids


def assert_widget_node_exists(notebook: Notebook, node_id: str) -> None:
    if len(node_id) > MAX_WIDGET_NODE_ID_LENGTH:
        raise WidgetError("This widget identifier is invalid.", "invalid_node_id")
    if node_id in _widget_node_ids(notebook.content):
        return
    raise WidgetError("This generated widget is no longer in the notebook.", "node_not_found")


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
        if preferred_owners.get(cell.dataframe_name) == cell.node_id:
            owners.setdefault(cell.dataframe_name, cell.node_id)
    return owners


def infer_widget_inputs(notebook: Notebook, node_id: str) -> list[str]:
    assert_widget_node_exists(notebook, node_id)
    return list(_dataframe_owners(notebook))


def _columns_from_metadata(raw_types: object, raw_columns: object) -> list[dict[str, str]]:
    columns: list[dict[str, str]] = []
    if isinstance(raw_types, list):
        for pair in raw_types[:MAX_COLUMNS]:
            if isinstance(pair, list | tuple) and len(pair) >= 2:
                columns.append({"name": str(pair[0])[:256], "type": str(pair[1])[:256]})
    if not columns and isinstance(raw_columns, list):
        columns = [{"name": str(column)[:256], "type": "unknown"} for column in raw_columns[:MAX_COLUMNS]]
    return columns


def _row_count_from_metadata(raw_row_count: object, raw_first_page: object) -> int:
    if isinstance(raw_row_count, int) and raw_row_count >= 0:
        return raw_row_count
    return len(raw_first_page) if isinstance(raw_first_page, list) else 0


def inspect_widget_inputs(
    notebook: Notebook,
    inputs: list[str],
    authorize_run: Callable[[NotebookNodeRun], None],
    node_id: str | None = None,
) -> WidgetInputInspection:
    normalized_inputs = normalize_widget_inputs(inputs)
    if node_id is not None:
        assert_widget_node_exists(notebook, node_id)
    owners = _dataframe_owners(notebook)
    missing = [name for name in normalized_inputs if name not in owners]
    if missing:
        raise WidgetConflictError(f'Dataframe "{missing[0]}" is no longer in this notebook.', "input_missing")

    node_ids = [owners[name] for name in normalized_inputs]
    run_queryset = (
        NotebookNodeRun.objects.for_team(notebook.team_id)
        .filter(notebook=notebook, node_id__in=node_ids, status=NotebookNodeRun.Status.DONE)
        .order_by("node_id", "-created_at")
        .distinct("node_id")
    )
    runs = {run.node_id: run for run in run_queryset.defer("envelope")}
    unresolved = [name for name in normalized_inputs if owners[name] not in runs]
    if unresolved:
        raise WidgetConflictError(
            f'Run the cell that creates "{unresolved[0]}" before generating this widget.',
            "input_not_ready",
        )
    run_ids = [run.id for run in runs.values()]
    metadata_by_id = {
        row["id"]: row
        for row in NotebookNodeRun.objects.for_team(notebook.team_id)
        .filter(id__in=run_ids)
        .values("id", "envelope__types", "envelope__columns", "envelope__row_count")
    }
    resolved: list[ResolvedWidgetInput] = []
    for name in normalized_inputs:
        run = runs.get(owners[name])
        if run is None:
            continue
        authorize_run(run)
        metadata = metadata_by_id.get(run.id)
        columns = _columns_from_metadata(
            metadata["envelope__types"] if metadata is not None else None,
            metadata["envelope__columns"] if metadata is not None else None,
        )
        total_row_count = _row_count_from_metadata(
            metadata["envelope__row_count"] if metadata is not None else None, None
        )
        schema = {"columns": columns}
        resolved.append(
            ResolvedWidgetInput(
                name=name,
                run=run,
                contract={
                    "slot": name,
                    "sourceName": name,
                    "runId": str(run.id),
                    "columns": columns,
                    "totalRowCount": total_row_count,
                    "schemaHash": _json_hash(schema),
                },
            )
        )
    inspection = WidgetInputInspection(resolved_inputs=resolved)
    if _json_size(inspection.contract) > MAX_INPUT_CONTRACT_BYTES:
        raise WidgetError(
            "This notebook has too much dataframe schema to generate a widget. Use fewer or narrower dataframes.",
            "input_schema_too_large",
        )
    return inspection


def _bounded_schema_context(contract: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    used_bytes = 2
    for item in contract:
        candidate = {
            "name": item.get("slot"),
            "columns": item.get("columns"),
            "totalRowCount": item.get("totalRowCount"),
        }
        size = len(json.dumps(candidate, separators=(",", ":")).encode())
        if used_bytes + size > MAX_SCHEMA_CONTEXT_BYTES:
            result.append({"name": item.get("slot"), "schemaOmitted": True})
        else:
            result.append(candidate)
            used_bytes += size
    return result


def _version_input_contract(contract: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "slot": item.get("slot"),
            "sourceName": item.get("sourceName"),
            "schemaHash": item.get("schemaHash"),
        }
        for item in contract
    ]


def _check_generation_rate(team_id: int, user_id: int) -> None:
    minute = int(timezone.now().timestamp() // 60)
    key = f"notebook_widget_generation:{team_id}:{user_id}:{minute}"
    if cache.add(key, 1, timeout=90):
        return
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=90)
        count = 1
    if count > MAX_GENERATIONS_PER_USER_PER_MINUTE:
        raise WidgetRateLimitError("Too many widgets were started. Try again in a minute.", "rate_limited")


def _is_ai_usage_limited(team_api_token: str) -> bool:
    from ee.billing.quota_limiting import (  # noqa: PLC0415 — keeps the billing query stack off the API import path
        is_team_over_ai_credit_budget,
    )

    return is_team_over_ai_credit_budget(team_api_token)


def is_notebook_widget_enabled(user: User | None) -> bool:
    if settings.DEBUG or settings.TEST:
        return True
    if user is None or not user.distinct_id:
        return False
    organization = getattr(user, "organization", None)
    if organization is None:
        return bool(
            posthoganalytics.feature_enabled(
                NOTEBOOK_GENERATED_WIDGETS_FLAG,
                user.distinct_id,
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    organization_id = str(organization.id)
    return bool(
        posthoganalytics.feature_enabled(
            NOTEBOOK_GENERATED_WIDGETS_FLAG,
            user.distinct_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


def _display_name(prompt: str) -> str:
    return prompt if len(prompt) <= 80 else f"{prompt[:77].rstrip()}..."


def _ensure_widget_instance(*, notebook: Notebook, node_id: str, prompt: str, user_id: int) -> NotebookWidgetInstance:
    from products.canvas.backend import (  # noqa: PLC0415 — keeps Canvas build imports off notebook startup
        notebook_integration as canvas_facade,
    )
    from products.tasks.backend.facade import (  # noqa: PLC0415 — keeps Tasks imports off notebook startup
        api as tasks_facade,
    )

    with transaction.atomic():
        Notebook.objects.filter(team_id=notebook.team_id).select_for_update().only("id").get(id=notebook.id)
        instance = (
            NotebookWidgetInstance.objects.for_team(notebook.team_id)
            .select_for_update()
            .select_related("widget")
            .filter(notebook=notebook, node_id=node_id)
            .first()
        )
        if instance is not None:
            return instance
        channel_id = tasks_facade.ensure_personal_channel_id(team_id=notebook.team_id, user_id=user_id)
        canvas_id = canvas_facade.create_notebook_canvas(
            team_id=notebook.team_id,
            user_id=user_id,
            channel_id=channel_id,
            name=_display_name(prompt),
            context=prompt,
        )
        widget = GeneratedWidget.objects.for_team(notebook.team_id).create(
            team_id=notebook.team_id,
            name=_display_name(prompt),
            canvas_id=canvas_id,
            created_by_id=user_id,
        )
        return NotebookWidgetInstance.objects.for_team(notebook.team_id).create(
            team_id=notebook.team_id,
            notebook=notebook,
            node_id=node_id,
            widget=widget,
            created_by_id=user_id,
        )


def _cancellation_key(team_id: int, generation_id: UUID) -> str:
    return f"notebook_widget_cancel:{team_id}:{generation_id}"


def _dispatch_widget_generation(job_id: UUID, team_id: int) -> None:
    for attempt in range(2):
        try:
            start_widget_generation_workflow(str(job_id), team_id)
            return
        except Exception:
            if attempt == 1:
                logger.exception(
                    "notebook_widget_generation_dispatch_failed",
                    extra={"job_id": str(job_id), "attempt": attempt + 1},
                )


def _get_existing_generation_job(team_id: int, generation_id: UUID) -> GeneratedWidgetGenerationJob | None:
    return (
        GeneratedWidgetGenerationJob.objects.for_team(team_id)
        .select_related("instance", "instance__notebook")
        .filter(idempotency_key=generation_id)
        .first()
    )


def _validate_generation_retry(
    *,
    job: GeneratedWidgetGenerationJob,
    notebook: Notebook,
    node_id: str,
    prompt: str,
    model: str,
    operation: str,
    expected_current_version_id: UUID | None,
) -> None:
    if job.team_id != notebook.team_id or job.instance.notebook_id != notebook.id or job.instance.node_id != node_id:
        raise WidgetConflictError("This generation identifier belongs to another widget.", "generation_id_conflict")
    expected_operation = operation
    if job.base_version_id is None:
        expected_operation = GeneratedWidgetVersion.Operation.INITIAL
    elif operation == GeneratedWidgetVersion.Operation.INITIAL:
        expected_operation = GeneratedWidgetVersion.Operation.REGENERATE
    if job.prompt != prompt or job.model != model or job.operation != expected_operation:
        raise WidgetConflictError(
            "This generation identifier was already used with different instructions.",
            "generation_id_conflict",
        )
    if operation == GeneratedWidgetVersion.Operation.IMPROVE and job.base_version_id != expected_current_version_id:
        raise WidgetConflictError(
            "This generation identifier was already used for a different widget version.",
            "generation_id_conflict",
        )


def _fail_stale_generation_jobs(team_id: int) -> None:
    cutoff = timezone.now() - JOB_STALE_AFTER
    stale_jobs = GeneratedWidgetGenerationJob.objects.for_team(team_id).filter(
        status__in=GeneratedWidgetGenerationJob.ACTIVE_STATUSES
    )
    stale_jobs = stale_jobs.filter(
        Q(heartbeat_at__lt=cutoff)
        | Q(heartbeat_at__isnull=True, started_at__lt=cutoff)
        | Q(heartbeat_at__isnull=True, started_at__isnull=True, created_at__lt=cutoff)
    )
    failed_at = timezone.now()
    stale_jobs.filter(cancel_requested_at__isnull=False).update(
        status=GeneratedWidgetGenerationJob.Status.CANCELED,
        phase="canceled",
        error_code="generation_canceled",
        error_detail="Widget generation was canceled.",
        finished_at=failed_at,
    )
    stale_jobs.filter(cancel_requested_at__isnull=True).update(
        status=GeneratedWidgetGenerationJob.Status.FAILED,
        phase="failed",
        error_code="generation_abandoned",
        error_detail="Generation stopped unexpectedly. Start it again.",
        finished_at=failed_at,
    )


def _reconcile_stale_generation_job(job: GeneratedWidgetGenerationJob) -> None:
    if job.status not in GeneratedWidgetGenerationJob.ACTIVE_STATUSES:
        return
    last_active_at = job.heartbeat_at or job.started_at or job.created_at
    if last_active_at >= timezone.now() - JOB_STALE_AFTER:
        return
    failed_at = timezone.now()
    canceled = job.cancel_requested_at is not None
    updates: dict[str, object] = {
        "status": (
            GeneratedWidgetGenerationJob.Status.CANCELED if canceled else GeneratedWidgetGenerationJob.Status.FAILED
        ),
        "phase": "canceled" if canceled else "failed",
        "error_code": "generation_canceled" if canceled else "generation_abandoned",
        "error_detail": "Widget generation was canceled."
        if canceled
        else "Generation stopped unexpectedly. Start it again.",
        "finished_at": failed_at,
    }
    updated = (
        GeneratedWidgetGenerationJob.objects.for_team(job.team_id)
        .filter(
            id=job.id,
            status=job.status,
            started_at=job.started_at,
            heartbeat_at=job.heartbeat_at,
            cancel_requested_at=job.cancel_requested_at,
        )
        .update(**updates)
    )
    if updated:
        for field, value in updates.items():
            setattr(job, field, value)
    else:
        job.refresh_from_db()


def start_widget_generation(
    *,
    notebook: Notebook,
    node_id: str,
    prompt: str,
    user_id: int,
    inspection: WidgetInputInspection,
    model: str,
    generation_id: UUID,
    operation: str,
    expected_current_version_id: UUID | None = None,
) -> WidgetStatus:
    assert_widget_node_exists(notebook, node_id)
    normalized_prompt = normalize_widget_prompt(prompt, operation)
    if not Team.objects.filter(id=notebook.team_id, organization__is_ai_data_processing_approved=True).exists():
        raise WidgetError(
            "Approve AI data processing in organization settings before generating widgets.",
            "ai_data_processing_not_approved",
        )
    existing_job = _get_existing_generation_job(notebook.team_id, generation_id)
    if existing_job is not None:
        _validate_generation_retry(
            job=existing_job,
            notebook=notebook,
            node_id=node_id,
            prompt=normalized_prompt,
            model=model,
            operation=operation,
            expected_current_version_id=expected_current_version_id,
        )
        _dispatch_widget_generation(existing_job.id, existing_job.team_id)
        return get_widget_status(notebook=notebook, node_id=node_id)

    _check_generation_rate(notebook.team_id, user_id)
    if _is_ai_usage_limited(notebook.team.api_token):
        raise WidgetRateLimitError(
            "Widget generation is unavailable because this project's AI usage limit has been reached.",
            "usage_limit_exceeded",
        )
    with transaction.atomic():
        Team.objects.select_for_update().only("id").get(id=notebook.team_id)
        existing_job = _get_existing_generation_job(notebook.team_id, generation_id)
        if existing_job is not None:
            _validate_generation_retry(
                job=existing_job,
                notebook=notebook,
                node_id=node_id,
                prompt=normalized_prompt,
                model=model,
                operation=operation,
                expected_current_version_id=expected_current_version_id,
            )
            return get_widget_status(notebook=notebook, node_id=node_id)
        _fail_stale_generation_jobs(notebook.team_id)
        active_team_jobs = (
            GeneratedWidgetGenerationJob.objects.for_team(notebook.team_id)
            .filter(status__in=GeneratedWidgetGenerationJob.ACTIVE_STATUSES)
            .count()
        )
        if active_team_jobs >= MAX_ACTIVE_GENERATIONS_PER_TEAM:
            raise WidgetRateLimitError("Widget generation capacity is full. Try again shortly.", "generation_capacity")
        instance = _ensure_widget_instance(
            notebook=notebook,
            node_id=node_id,
            prompt=normalized_prompt,
            user_id=user_id,
        )
        locked_instance = (
            NotebookWidgetInstance.objects.for_team(notebook.team_id)
            .select_for_update(of=("self", "widget"))
            .select_related("widget", "widget__current_version")
            .get(id=instance.id)
        )
        if (
            GeneratedWidgetGenerationJob.objects.for_team(notebook.team_id)
            .filter(instance=locked_instance, status__in=GeneratedWidgetGenerationJob.ACTIVE_STATUSES)
            .exists()
        ):
            raise WidgetConflictError(
                "This widget is already being generated. Cancel it before starting another version.",
                "generation_in_progress",
            )
        base_version = locked_instance.widget.current_version
        if operation == GeneratedWidgetVersion.Operation.IMPROVE:
            if base_version is None:
                raise WidgetConflictError("Generate the widget before improving it.", "version_missing")
            if expected_current_version_id is None or base_version.id != expected_current_version_id:
                raise WidgetConflictError(
                    "This widget changed since you opened it. Reload the latest version before improving it.",
                    "generation_conflict",
                )
            next_prompt_history = _extend_prompt_history(_prompt_history(base_version), normalized_prompt)
            if len(_materialize_prompt_history(next_prompt_history)) > MAX_WIDGET_EFFECTIVE_PROMPT_LENGTH:
                raise WidgetError(
                    "The widget's full instructions are too long to improve. Regenerate it with shorter instructions first.",
                    "effective_prompt_too_long",
                )
        resolved_operation = operation
        if base_version is None:
            resolved_operation = GeneratedWidgetVersion.Operation.INITIAL
        elif operation == GeneratedWidgetVersion.Operation.INITIAL:
            resolved_operation = GeneratedWidgetVersion.Operation.REGENERATE
        job = GeneratedWidgetGenerationJob.objects.for_team(notebook.team_id).create(
            idempotency_key=generation_id,
            team_id=notebook.team_id,
            widget=locked_instance.widget,
            instance=locked_instance,
            requested_by_id=user_id,
            operation=resolved_operation,
            prompt=normalized_prompt,
            model=model,
            base_version=base_version,
            input_contract=inspection.contract,
            schema_hash=inspection.schema_hash,
        )
        transaction.on_commit(lambda: _dispatch_widget_generation(job.id, notebook.team_id))
    return get_widget_status(notebook=notebook, node_id=node_id)


def cancel_widget_generation(*, notebook: Notebook, node_id: str, generation_id: UUID) -> None:
    assert_widget_node_exists(notebook, node_id)
    canceled_at = timezone.now()
    job_id = (
        GeneratedWidgetGenerationJob.objects.for_team(notebook.team_id)
        .filter(
            idempotency_key=generation_id,
            instance__notebook=notebook,
            instance__node_id=node_id,
            status__in=GeneratedWidgetGenerationJob.ACTIVE_STATUSES,
        )
        .values_list("id", flat=True)
        .first()
    )
    if job_id is None:
        return
    updated = (
        GeneratedWidgetGenerationJob.objects.for_team(notebook.team_id)
        .filter(id=job_id, status__in=GeneratedWidgetGenerationJob.ACTIVE_STATUSES)
        .update(
            cancel_requested_at=canceled_at,
            status=GeneratedWidgetGenerationJob.Status.CANCELED,
            phase="canceled",
            error_code="generation_canceled",
            error_detail="Widget generation was canceled.",
            finished_at=canceled_at,
        )
    )
    if updated:
        cache.set(
            _cancellation_key(notebook.team_id, job_id),
            True,
            timeout=GENERATION_CANCELLATION_TTL_SECONDS,
        )


def _prompt_history(version: GeneratedWidgetVersion) -> list[str]:
    history = version.prompt_history
    if isinstance(history, list) and history and all(isinstance(item, str) for item in history):
        return history
    versions = {
        item.id: item
        for item in GeneratedWidgetVersion.objects.for_team(version.team_id).filter(widget_id=version.widget_id)
    }
    lineage: list[GeneratedWidgetVersion] = []
    current: GeneratedWidgetVersion | None = versions.get(version.id, version)
    seen: set[UUID] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        lineage.append(current)
        if current.operation in {
            GeneratedWidgetVersion.Operation.INITIAL,
            GeneratedWidgetVersion.Operation.REGENERATE,
        }:
            break
        next_version_id = (
            current.reverted_from_version_id
            if current.operation == GeneratedWidgetVersion.Operation.REVERT and current.reverted_from_version_id
            else current.parent_version_id
        )
        current = versions.get(next_version_id) if next_version_id else None
    result: list[str] = []
    for item in reversed(lineage):
        if item.operation in {
            GeneratedWidgetVersion.Operation.INITIAL,
            GeneratedWidgetVersion.Operation.REGENERATE,
        }:
            result = [item.prompt_delta]
        elif item.operation != GeneratedWidgetVersion.Operation.REVERT and item.prompt_delta:
            result.append(item.prompt_delta)
    return result or [version.prompt_delta]


def _materialize_prompt_history(history: list[str]) -> str:
    if not history:
        return ""
    return "\n\n".join([history[0], *(f"Additional change:\n{item}" for item in history[1:])])


def _extend_prompt_history(history: list[str], prompt: str) -> list[str]:
    bounded = [*history, prompt]
    while len(bounded) > 2 and len(_materialize_prompt_history(bounded)) > MAX_WIDGET_EFFECTIVE_PROMPT_LENGTH:
        del bounded[1]
    return bounded


def _materialize_effective_prompt(version: GeneratedWidgetVersion) -> str:
    return _materialize_prompt_history(_prompt_history(version))


def _mark_job_failed(job_id: UUID, team_id: int, error: WidgetError, failure_phase: str | None = None) -> None:
    GeneratedWidgetGenerationJob.objects.for_team(team_id).filter(
        id=job_id, status__in=GeneratedWidgetGenerationJob.ACTIVE_STATUSES
    ).update(
        status=(
            GeneratedWidgetGenerationJob.Status.CANCELED
            if error.code == "generation_canceled"
            else GeneratedWidgetGenerationJob.Status.FAILED
        ),
        phase=(
            "canceled"
            if error.code == "generation_canceled"
            else f"failed_{failure_phase}"
            if failure_phase
            else "failed"
        ),
        error_code=error.code,
        error_detail=error.detail,
        finished_at=timezone.now(),
        heartbeat_at=timezone.now(),
    )


def _record_job_step_failure(
    job: GeneratedWidgetGenerationJob,
    *,
    failure_phase: str,
    error: Exception,
    error_code: str,
    error_detail: str,
) -> None:
    logger.warning(
        "notebook_widget_generation_step_failed",
        extra={
            "job_id": str(job.id),
            "team_id": job.team_id,
            "failure_phase": failure_phase,
            "error_code": error_code,
            "exception_type": type(error).__name__,
            "upstream_status_code": getattr(error, "status_code", None),
            "upstream_request_id": getattr(error, "request_id", None),
        },
    )
    _mark_job_failed(
        job.id,
        job.team_id,
        WidgetError(error_detail, error_code),
        failure_phase=failure_phase,
    )


def _job_failure_phase(job: GeneratedWidgetGenerationJob | None) -> str | None:
    if job is None or job.status != GeneratedWidgetGenerationJob.Status.FAILED:
        return None
    failure_phase = job.phase.removeprefix("failed_")
    return (
        failure_phase if failure_phase in {"generating_source", "reviewing_source", "publishing_source"} else "unknown"
    )


def fail_widget_generation_job(job_id: UUID, team_id: int) -> None:
    job = GeneratedWidgetGenerationJob.objects.for_team(team_id).only("id", "team_id").filter(id=job_id).first()
    if job is not None:
        _mark_job_failed(
            job.id,
            job.team_id,
            WidgetError("Generation stopped unexpectedly. Start it again.", "generation_abandoned"),
        )


def fail_widget_generation_capacity_job(job_id: UUID, team_id: int) -> None:
    job = GeneratedWidgetGenerationJob.objects.for_team(team_id).only("id", "team_id").filter(id=job_id).first()
    if job is not None:
        _mark_job_failed(
            job.id,
            job.team_id,
            WidgetError("Widget generation capacity is full. Try again shortly.", "generation_capacity_exhausted"),
        )


def heartbeat_widget_generation_job(job_id: UUID, team_id: int) -> None:
    GeneratedWidgetGenerationJob.objects.for_team(team_id).filter(
        id=job_id, status=GeneratedWidgetGenerationJob.Status.QUEUED
    ).update(heartbeat_at=timezone.now())


def run_widget_generation_job(job_id: UUID, team_id: int) -> None:
    from products.canvas.backend import (  # noqa: PLC0415 — keeps Canvas and object storage off worker registration
        notebook_integration as canvas_facade,
    )
    from products.notebooks.backend.widget_generation import (  # noqa: PLC0415 — keeps the model client off Django startup
        WidgetSecurityReviewError,
        WidgetSourceGenerationCancelled,
        WidgetSourceGenerationError,
        WidgetSourceGenerationTimedOut,
        generate_widget_source,
        review_widget_source,
    )

    with transaction.atomic():
        job = (
            GeneratedWidgetGenerationJob.objects.for_team(team_id)
            .select_for_update(of=("self",))
            .select_related(
                "team",
                "team__organization",
                "widget",
                "instance",
                "instance__notebook",
                "requested_by",
                "base_version",
            )
            .filter(id=job_id)
            .first()
        )
        if job is None or job.status != GeneratedWidgetGenerationJob.Status.QUEUED:
            return
        if job.cancel_requested_at is not None:
            job.status = GeneratedWidgetGenerationJob.Status.CANCELED
            job.phase = "canceled"
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "phase", "finished_at"])
            return
        job.status = GeneratedWidgetGenerationJob.Status.GENERATING
        job.phase = "generating_source"
        job.started_at = timezone.now()
        job.heartbeat_at = timezone.now()
        job.save(update_fields=["status", "phase", "started_at", "heartbeat_at"])

    if job.requested_by is None:
        _mark_job_failed(
            job.id, job.team_id, WidgetError("The user who started this job no longer exists.", "user_missing")
        )
        return
    if not job.team.organization.is_ai_data_processing_approved:
        _mark_job_failed(
            job.id,
            job.team_id,
            WidgetError(
                "AI data processing approval was removed before generation started. "
                "Approve it in organization settings, then regenerate the widget.",
                "ai_data_processing_not_approved",
            ),
        )
        return
    try:
        assert_widget_node_exists(job.instance.notebook, job.instance.node_id)
    except WidgetError as error:
        _mark_job_failed(job.id, job.team_id, error)
        return
    checked_at = 0.0
    durable_checked_at = 0.0
    heartbeat_at = 0.0
    canceled = False

    def is_cancelled() -> bool:
        nonlocal checked_at, durable_checked_at, heartbeat_at, canceled
        now = monotonic()
        if now - checked_at >= 0.5:
            canceled = bool(cache.get(_cancellation_key(job.team_id, job.id)))
            checked_at = now
        if not canceled and now - durable_checked_at >= 15:
            canceled = (
                GeneratedWidgetGenerationJob.objects.for_team(job.team_id)
                .filter(id=job.id, cancel_requested_at__isnull=False)
                .exists()
            )
            durable_checked_at = now
        if now - heartbeat_at >= 15:
            GeneratedWidgetGenerationJob.objects.for_team(job.team_id).filter(
                id=job.id, status=GeneratedWidgetGenerationJob.Status.GENERATING
            ).update(heartbeat_at=timezone.now())
            heartbeat_at = now
        return canceled

    try:
        base_source: str | None = None
        change_prompt: str | None = None
        effective_prompt = job.prompt
        if job.operation == GeneratedWidgetVersion.Operation.IMPROVE:
            if job.base_version is None:
                raise WidgetConflictError("The version being improved no longer exists.", "version_missing")
            base_source = canvas_facade.get_notebook_canvas_source(
                team_id=job.team_id,
                canvas_id=job.widget.canvas_id,
                version_id=job.base_version.canvas_source_version_id,
            )
            change_prompt = job.prompt
            effective_prompt = _materialize_effective_prompt(job.base_version)
        frames = _bounded_schema_context(job.input_contract)
        frame_names = [str(item.get("slot")) for item in job.input_contract if item.get("slot")]
        generated = generate_widget_source(
            team_id=job.team_id,
            trace_id=f"notebook-widget-{job.id}",
            prompt=effective_prompt,
            schemas=frames,
            input_names=frame_names,
            model=job.model,
            is_cancelled=is_cancelled,
            base_source=base_source,
            change_prompt=change_prompt,
        )
        source = generated.source
        title = generated.title or _display_name(effective_prompt)
        if is_cancelled():
            raise WidgetError("Widget generation was canceled.", "generation_canceled")
        reviewing = (
            GeneratedWidgetGenerationJob.objects.for_team(job.team_id)
            .filter(
                id=job.id,
                status=GeneratedWidgetGenerationJob.Status.GENERATING,
                cancel_requested_at__isnull=True,
            )
            .update(phase="reviewing_source", heartbeat_at=timezone.now())
        )
        if not reviewing:
            raise WidgetError("This generation is no longer active.", "generation_abandoned")
        job.phase = "reviewing_source"
        security_review = review_widget_source(
            team_id=job.team_id,
            trace_id=f"notebook-widget-security-review-{job.id}",
            source=source,
            input_names=frame_names,
            is_cancelled=is_cancelled,
        )
        # Publication preserves the exact reviewed artifact for inspection. Browser consumers gate execution of
        # every non-clean verdict on explicit trust for this version's immutable build hash.
        security_reviewed_at = timezone.now()
        if is_cancelled():
            raise WidgetError("Widget generation was canceled.", "generation_canceled")
        publishing = (
            GeneratedWidgetGenerationJob.objects.for_team(job.team_id)
            .filter(
                id=job.id,
                status=GeneratedWidgetGenerationJob.Status.GENERATING,
                cancel_requested_at__isnull=True,
            )
            .update(
                status=GeneratedWidgetGenerationJob.Status.PUBLISHING,
                phase="publishing_source",
                heartbeat_at=timezone.now(),
            )
        )
        if not publishing:
            raise WidgetError("This generation is no longer active.", "generation_abandoned")
        job.phase = "publishing_source"
        prepared_source = canvas_facade.prepare_notebook_canvas_source(
            team_id=job.team_id,
            canvas_id=job.widget.canvas_id,
            user_id=job.requested_by.id,
            source=source,
            input_names=[str(item.get("slot")) for item in job.input_contract if isinstance(item, dict)],
            prompt=job.prompt,
            name=title,
            expected_current_version_id=(
                job.base_version.canvas_source_version_id if job.base_version is not None else None
            ),
        )
        with transaction.atomic():
            locked_job = (
                GeneratedWidgetGenerationJob.objects.for_team(job.team_id)
                .select_for_update()
                .select_related("instance", "widget")
                .get(id=job.id)
            )
            widget = GeneratedWidget.objects.for_team(job.team_id).select_for_update().get(id=job.widget_id)
            instance = NotebookWidgetInstance.objects.for_team(job.team_id).select_for_update().get(id=job.instance_id)
            if locked_job.cancel_requested_at is not None:
                raise WidgetError("Widget generation was canceled.", "generation_canceled")
            if locked_job.status != GeneratedWidgetGenerationJob.Status.PUBLISHING:
                raise WidgetError("This generation is no longer active.", "generation_abandoned")
            if widget.current_version_id != job.base_version_id:
                raise WidgetConflictError(
                    "This widget changed while the new version was being generated.",
                    "generation_conflict",
                )
            publication = canvas_facade.publish_prepared_notebook_canvas_source(
                team_id=job.team_id,
                user_id=job.requested_by.id,
                prepared=prepared_source,
            )
            prompt_history = (
                _extend_prompt_history(_prompt_history(job.base_version), job.prompt)
                if job.operation == GeneratedWidgetVersion.Operation.IMPROVE and job.base_version is not None
                else [job.prompt]
            )
            version = GeneratedWidgetVersion.objects.for_team(job.team_id).create(
                team_id=job.team_id,
                widget=widget,
                canvas_source_version_id=publication,
                parent_version=job.base_version,
                title=title,
                operation=job.operation,
                prompt_delta=job.prompt,
                prompt_history=prompt_history,
                model=job.model,
                generator_version=GENERATOR_VERSION,
                input_contract=_version_input_contract(job.input_contract),
                schema_hash=job.schema_hash,
                security_review_severity=security_review.severity,
                security_review_summary=security_review.summary,
                security_review_findings=[
                    {
                        "severity": finding.severity,
                        "title": finding.title,
                        "details": finding.details,
                    }
                    for finding in security_review.findings
                ],
                security_review_model=security_review.model,
                security_review_version=security_review.review_version,
                security_reviewed_at=security_reviewed_at,
                created_by=job.requested_by,
            )
            widget.current_version = version
            widget.name = title
            widget.save(update_fields=["current_version", "name"])
            instance.pinned_version = version
            instance.save(update_fields=["pinned_version"])
            locked_job.status = GeneratedWidgetGenerationJob.Status.COMPLETED
            locked_job.phase = "completed"
            locked_job.result_version = version
            locked_job.finished_at = timezone.now()
            locked_job.heartbeat_at = timezone.now()
            locked_job.save(update_fields=["status", "phase", "result_version", "finished_at", "heartbeat_at"])
    except WidgetSourceGenerationCancelled:
        _mark_job_failed(job.id, job.team_id, WidgetError("Widget generation was canceled.", "generation_canceled"))
    except WidgetSourceGenerationTimedOut as error:
        _record_job_step_failure(
            job,
            failure_phase="generating_source",
            error=error,
            error_code="source_generation_timed_out",
            error_detail="Source generation took too long. Try a faster model or a more focused request.",
        )
    except WidgetSourceGenerationError as error:
        _record_job_step_failure(
            job,
            failure_phase="generating_source",
            error=error,
            error_code=error.code,
            error_detail=error.detail,
        )
    except WidgetSecurityReviewError as error:
        _record_job_step_failure(
            job,
            failure_phase="reviewing_source",
            error=error,
            error_code=error.code,
            error_detail=error.detail,
        )
    except canvas_facade.NotebookCanvasVersionConflictError as error:
        _record_job_step_failure(
            job,
            failure_phase="publishing_source",
            error=error,
            error_code="generation_conflict",
            error_detail="The widget changed before its generated source could be published. Generate it again.",
        )
    except canvas_facade.NotebookCanvasBuildCapacityError as error:
        _record_job_step_failure(
            job,
            failure_phase="publishing_source",
            error=error,
            error_code="build_capacity",
            error_detail="The source was generated and reviewed, but build capacity is full. Try again shortly.",
        )
    except canvas_facade.NotebookCanvasError as error:
        _record_job_step_failure(
            job,
            failure_phase="publishing_source",
            error=error,
            error_code="build_failed",
            error_detail="The source was generated and reviewed, but the widget build failed. Try again.",
        )
    except WidgetError as error:
        failure_phase = (
            job.phase if job.phase in {"generating_source", "reviewing_source", "publishing_source"} else None
        )
        if failure_phase:
            _record_job_step_failure(
                job,
                failure_phase=failure_phase,
                error=error,
                error_code=error.code,
                error_detail=error.detail,
            )
        else:
            _mark_job_failed(job.id, job.team_id, error)
    except Exception:
        failure_phase = (
            job.phase if job.phase in {"generating_source", "reviewing_source", "publishing_source"} else "unknown"
        )
        failure_step = {
            "generating_source": "source generation",
            "reviewing_source": "security review",
            "publishing_source": "publishing",
            "unknown": "an unknown step",
        }[failure_phase]
        logger.exception(
            "notebook_widget_generation_failed",
            extra={"job_id": str(job.id), "team_id": job.team_id, "failure_phase": failure_phase},
        )
        _mark_job_failed(
            job.id,
            job.team_id,
            WidgetError(
                f"The widget failed during {failure_step}. Try again, and contact support if it keeps happening.",
                "generation_unexpected_error",
            ),
            failure_phase=failure_phase,
        )
    finally:
        cache.delete(_cancellation_key(job.team_id, job.id))


def _latest_job(instance: NotebookWidgetInstance) -> GeneratedWidgetGenerationJob | None:
    job = (
        GeneratedWidgetGenerationJob.objects.for_team(instance.team_id)
        .filter(instance=instance)
        .order_by("-created_at")
        .first()
    )
    return job


def get_widget_status(*, notebook: Notebook, node_id: str) -> WidgetStatus:
    from products.canvas.backend import (  # noqa: PLC0415 — keeps Canvas build imports off notebook startup
        notebook_integration as canvas_facade,
    )

    assert_widget_node_exists(notebook, node_id)
    instance = (
        NotebookWidgetInstance.objects.for_team(notebook.team_id)
        .select_related("widget", "widget__current_version", "pinned_version")
        .filter(notebook=notebook, node_id=node_id)
        .first()
    )
    if instance is None:
        return WidgetStatus(
            lifecycle_status="awaiting_generation",
            error_detail=None,
            artifact_url=None,
            frame_names=[],
            current_version_id=None,
            widget_id=None,
            instance_id=None,
            has_versions=False,
            active_job=None,
            security_review=None,
            error_code=None,
            failure_phase=None,
            build_hash=None,
        )
    job = _latest_job(instance)
    if job is not None:
        _reconcile_stale_generation_job(job)
    active_job = (
        WidgetJobState(
            id=job.idempotency_key,
            status=job.status,
            phase=job.phase,
            model=job.model,
            created_at=job.created_at,
            started_at=job.started_at,
        )
        if job is not None and job.status in GeneratedWidgetGenerationJob.ACTIVE_STATUSES
        else None
    )
    current_version = instance.pinned_version or instance.widget.current_version
    if current_version is None:
        lifecycle = (
            "generating"
            if active_job is not None
            else "failed"
            if job is not None and job.status == GeneratedWidgetGenerationJob.Status.FAILED
            else "awaiting_generation"
        )
        return WidgetStatus(
            lifecycle_status=lifecycle,
            error_detail=job.error_detail if job and job.status == GeneratedWidgetGenerationJob.Status.FAILED else None,
            artifact_url=None,
            frame_names=[],
            current_version_id=None,
            widget_id=instance.widget_id,
            instance_id=instance.id,
            has_versions=False,
            active_job=active_job,
            security_review=None,
            error_code=job.error_code if job and job.status == GeneratedWidgetGenerationJob.Status.FAILED else None,
            failure_phase=_job_failure_phase(job),
            build_hash=None,
        )
    state = canvas_facade.get_canvas_generation_state(team_id=notebook.team_id, canvas_id=instance.widget.canvas_id)
    selected_canvas_version = None
    if state is not None and state.current_source_version_id != current_version.canvas_source_version_id:
        selected_canvas_versions = canvas_facade.list_notebook_canvas_versions(
            team_id=notebook.team_id,
            canvas_id=instance.widget.canvas_id,
            version_ids=[current_version.canvas_source_version_id],
        )
        selected_canvas_version = selected_canvas_versions[0] if selected_canvas_versions else None
    frame_names = [
        str(item.get("slot")) for item in current_version.input_contract if isinstance(item, dict) and item.get("slot")
    ]
    artifact_url: str | None = None
    build_hash: str | None = None
    lifecycle = "building"
    error_detail = job.error_detail if job and job.status == GeneratedWidgetGenerationJob.Status.FAILED else None
    error_code = job.error_code if job and job.status == GeneratedWidgetGenerationJob.Status.FAILED else None
    failure_phase = _job_failure_phase(job)
    if state is None:
        lifecycle = "failed"
        error_detail = error_detail or "The widget preview is unavailable. Generate a new version."
    elif state.current_source_version_id == current_version.canvas_source_version_id:
        if state.build_status == "ready" and state.artifact_url:
            lifecycle = "generating" if active_job is not None else "ready"
            artifact_url = state.artifact_url
            build_hash = state.build_hash
            error_detail = None
            error_code = None
            failure_phase = None
        elif state.build_status == "ready":
            lifecycle = "failed"
            error_detail = error_detail or "The widget preview is unavailable. Reload it, or generate a new version."
        elif state.build_status == "failed":
            lifecycle = "failed"
            error_detail = (
                error_detail
                or "The widget preview couldn't be built. Regenerate it or view the source to make changes."
            )
    elif selected_canvas_version is None:
        lifecycle = "failed"
        error_detail = error_detail or "The widget preview is unavailable. Generate a new version."
    elif selected_canvas_version.build_status == "ready" and selected_canvas_version.artifact_url:
        lifecycle = "generating" if active_job is not None else "ready"
        artifact_url = selected_canvas_version.artifact_url
        build_hash = selected_canvas_version.build_hash
        error_detail = None
        error_code = None
        failure_phase = None
    elif selected_canvas_version.build_status == "ready":
        lifecycle = "failed"
        error_detail = error_detail or "The widget preview is unavailable. Reload it, or generate a new version."
    elif selected_canvas_version.build_status == "failed":
        lifecycle = "failed"
        error_detail = (
            error_detail or "The widget preview couldn't be built. Regenerate it or view the source to make changes."
        )
    if active_job is not None:
        lifecycle = "generating"
        error_detail = None
        error_code = None
        failure_phase = None
    return WidgetStatus(
        lifecycle_status=lifecycle,
        error_detail=error_detail,
        artifact_url=artifact_url,
        frame_names=frame_names,
        current_version_id=current_version.id,
        widget_id=instance.widget_id,
        instance_id=instance.id,
        has_versions=True,
        active_job=active_job,
        security_review=_security_review_state(current_version),
        error_code=error_code,
        failure_phase=failure_phase,
        build_hash=build_hash,
    )


def list_widget_versions(*, notebook: Notebook, node_id: str, offset: int = 0, limit: int = 25) -> WidgetVersionPage:
    from products.canvas.backend import (  # noqa: PLC0415 — keeps Canvas build imports off notebook startup
        notebook_integration as canvas_facade,
    )

    assert_widget_node_exists(notebook, node_id)
    instance = (
        NotebookWidgetInstance.objects.for_team(notebook.team_id)
        .select_related("widget", "widget__current_version", "pinned_version")
        .filter(notebook=notebook, node_id=node_id)
        .first()
    )
    if instance is None:
        return WidgetVersionPage(results=[], count=0, next_offset=None)
    queryset = GeneratedWidgetVersion.objects.for_team(notebook.team_id).filter(widget=instance.widget)
    count = queryset.count()
    versions = list(queryset.order_by("-created_at")[offset : offset + limit])
    canvas_versions = canvas_facade.list_notebook_canvas_versions(
        team_id=notebook.team_id,
        canvas_id=instance.widget.canvas_id,
        version_ids=[version.canvas_source_version_id for version in versions],
    )
    canvas_by_id = {version.id: version for version in canvas_versions}
    current_id = instance.pinned_version_id or instance.widget.current_version_id
    results: list[WidgetVersionSummary] = []
    for index, version in enumerate(versions):
        canvas_version = canvas_by_id.get(version.canvas_source_version_id)
        results.append(
            WidgetVersionSummary(
                id=version.id,
                parent_version_id=version.parent_version_id,
                version=count - (offset + index),
                operation=version.operation,
                prompt_delta=version.prompt_delta,
                effective_prompt=_materialize_effective_prompt(version),
                model=version.model or None,
                created_at=version.created_at,
                build_status=canvas_version.build_status if canvas_version is not None else None,
                artifact_url=canvas_version.artifact_url if canvas_version is not None else None,
                frame_names=[
                    str(item.get("slot"))
                    for item in version.input_contract
                    if isinstance(item, dict) and item.get("slot")
                ],
                is_current=version.id == current_id,
                security_review=_security_review_state(version),
                build_hash=canvas_version.build_hash if canvas_version is not None else None,
            )
        )
    next_offset = offset + limit if offset + limit < count else None
    return WidgetVersionPage(results=results, count=count, next_offset=next_offset)


def _get_instance_and_version(
    notebook: Notebook, node_id: str, version_id: UUID | None
) -> tuple[NotebookWidgetInstance, GeneratedWidgetVersion]:
    assert_widget_node_exists(notebook, node_id)
    instance = (
        NotebookWidgetInstance.objects.for_team(notebook.team_id)
        .select_related("widget", "widget__current_version", "pinned_version")
        .filter(notebook=notebook, node_id=node_id)
        .first()
    )
    if instance is None:
        raise WidgetError("Generate the widget before viewing its source.", "version_missing")
    if version_id is not None:
        version = (
            GeneratedWidgetVersion.objects.for_team(notebook.team_id)
            .filter(id=version_id, widget=instance.widget)
            .first()
        )
    else:
        version = instance.pinned_version or instance.widget.current_version
    if version is None:
        raise WidgetError("The widget version is unavailable.", "version_missing")
    return instance, version


def read_widget_source(*, notebook: Notebook, node_id: str, version_id: UUID | None = None) -> str:
    from products.canvas.backend import (  # noqa: PLC0415 - keeps Canvas storage imports off notebook startup
        notebook_integration as canvas_facade,
    )

    instance, version = _get_instance_and_version(notebook, node_id, version_id)
    try:
        return canvas_facade.get_notebook_canvas_source(
            team_id=notebook.team_id,
            canvas_id=instance.widget.canvas_id,
            version_id=version.canvas_source_version_id,
        )
    except canvas_facade.NotebookCanvasError as error:
        raise WidgetError("The widget source is unavailable. Try again.", "source_unavailable") from error


def revert_widget_version(
    *,
    notebook: Notebook,
    node_id: str,
    version_id: UUID,
    expected_current_version_id: UUID,
    user_id: int,
) -> WidgetStatus:
    from products.canvas.backend import (  # noqa: PLC0415 — keeps Canvas storage imports off notebook startup
        notebook_integration as canvas_facade,
    )

    instance, target = _get_instance_and_version(notebook, node_id, version_id)
    current = instance.pinned_version or instance.widget.current_version
    if current is None or current.id != expected_current_version_id:
        raise WidgetConflictError("This widget changed before the version could be restored.", "revert_conflict")
    try:
        target_source = canvas_facade.get_notebook_canvas_source(
            team_id=notebook.team_id,
            canvas_id=instance.widget.canvas_id,
            version_id=target.canvas_source_version_id,
        )
        title = target.title or instance.widget.name
        prepared_source = canvas_facade.prepare_notebook_canvas_source(
            team_id=notebook.team_id,
            canvas_id=instance.widget.canvas_id,
            user_id=user_id,
            source=target_source,
            input_names=[str(item.get("slot")) for item in target.input_contract if isinstance(item, dict)],
            prompt=f"Restore version {target.id}",
            name=title,
            expected_current_version_id=current.canvas_source_version_id,
        )
    except canvas_facade.NotebookCanvasVersionConflictError as error:
        raise WidgetConflictError(
            "This widget changed before the version could be restored.", "revert_conflict"
        ) from error
    except canvas_facade.NotebookCanvasBuildCapacityError as error:
        raise WidgetRateLimitError("Widget build capacity is full. Try again shortly.", "build_capacity") from error
    except canvas_facade.NotebookCanvasNotFoundError as error:
        raise WidgetError("The selected widget version is no longer available.", "version_missing") from error
    except canvas_facade.NotebookCanvasError as error:
        raise WidgetError("The widget preview could not be updated. Try again.", "build_failed") from error
    with transaction.atomic():
        widget = GeneratedWidget.objects.for_team(notebook.team_id).select_for_update().get(id=instance.widget_id)
        locked_instance = (
            NotebookWidgetInstance.objects.for_team(notebook.team_id).select_for_update().get(id=instance.id)
        )
        if widget.current_version_id != current.id:
            raise WidgetConflictError("This widget changed before the version could be restored.", "revert_conflict")
        try:
            publication = canvas_facade.publish_prepared_notebook_canvas_source(
                team_id=notebook.team_id,
                user_id=user_id,
                prepared=prepared_source,
            )
        except canvas_facade.NotebookCanvasVersionConflictError as error:
            raise WidgetConflictError(
                "This widget changed before the version could be restored.", "revert_conflict"
            ) from error
        except canvas_facade.NotebookCanvasBuildCapacityError as error:
            raise WidgetRateLimitError("Widget build capacity is full. Try again shortly.", "build_capacity") from error
        except canvas_facade.NotebookCanvasNotFoundError as error:
            raise WidgetError("The selected widget version is no longer available.", "version_missing") from error
        except canvas_facade.NotebookCanvasError as error:
            raise WidgetError("The widget preview could not be updated. Try again.", "build_failed") from error
        version = GeneratedWidgetVersion.objects.for_team(notebook.team_id).create(
            team_id=notebook.team_id,
            widget=widget,
            canvas_source_version_id=publication,
            parent_version=current,
            reverted_from_version=target,
            title=title,
            operation=GeneratedWidgetVersion.Operation.REVERT,
            prompt_delta="Restored an earlier version.",
            prompt_history=_prompt_history(target),
            generator_version=GENERATOR_VERSION,
            input_contract=target.input_contract,
            schema_hash=target.schema_hash,
            security_review_severity=target.security_review_severity,
            security_review_summary=target.security_review_summary,
            security_review_findings=target.security_review_findings,
            security_review_model=target.security_review_model,
            security_review_version=target.security_review_version,
            security_reviewed_at=target.security_reviewed_at,
            created_by_id=user_id,
        )
        widget.current_version = version
        widget.name = title
        widget.save(update_fields=["current_version", "name"])
        locked_instance.pinned_version = version
        locked_instance.save(update_fields=["pinned_version"])
    return get_widget_status(notebook=notebook, node_id=node_id)


def _safe_cell(value: object) -> object:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if -(2**53) + 1 <= value <= 2**53 - 1 else str(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:MAX_CELL_STRING_LENGTH]
    return json.dumps(_bounded_json_value(value, [200]), default=str, separators=(",", ":"))[:MAX_CELL_STRING_LENGTH]


def _bounded_json_value(value: object, budget: list[int], depth: int = 0) -> object:
    if budget[0] <= 0 or depth >= 6:
        return "…"
    budget[0] -= 1
    if value is None or isinstance(value, bool | int | float | str):
        return _safe_cell(value)
    if isinstance(value, list | tuple):
        return [_bounded_json_value(item, budget, depth + 1) for item in value if budget[0] > 0]
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            if budget[0] <= 0:
                break
            result[str(key)[:128]] = _bounded_json_value(item, budget, depth + 1)
        return result
    return str(value)[:MAX_CELL_STRING_LENGTH]


def _bounded_rows(
    *, name: str, run_id: UUID, columns: list[dict[str, str]], candidates: object, total_row_count: int, offset: int
) -> dict[str, object]:
    rows: list[list[object]] = []
    raw_rows = candidates if isinstance(candidates, list) else []
    used_bytes = len(json.dumps({"name": name, "columns": columns}, separators=(",", ":")).encode())
    for raw_row in raw_rows:
        if not isinstance(raw_row, list):
            continue
        row = [_safe_cell(value) for value in raw_row[: len(columns)]]
        row_size = len(json.dumps(row, separators=(",", ":")).encode())
        if used_bytes + row_size > MAX_FRAME_BYTES:
            if not rows:
                raise WidgetError(
                    "A dataframe row is too large to preview. Reduce the number or size of its values and run the cell again.",
                    "frame_row_too_large",
                )
            break
        rows.append(row)
        used_bytes += row_size
    end_offset = offset + len(rows)
    next_offset = end_offset if end_offset < min(total_row_count, MAX_FRAME_TOTAL_ROWS) and rows else None
    return {
        "name": name,
        "runId": run_id,
        "columns": columns,
        "rows": rows,
        "totalRowCount": total_row_count,
        "includedRowCount": len(rows),
        "offset": offset,
        "nextOffset": next_offset,
        "truncated": end_offset < total_row_count,
    }


def read_widget_frame(
    *,
    notebook: Notebook,
    node_id: str,
    frame_name: str,
    authorize_run: Callable[[NotebookNodeRun], None],
    user: User | None,
    version_id: UUID | None = None,
    run_id: UUID | None = None,
    offset: int = 0,
    limit: int = 100,
) -> WidgetFrameRead:
    _instance, version = _get_instance_and_version(notebook, node_id, version_id)
    contract_item = next(
        (item for item in version.input_contract if isinstance(item, dict) and item.get("slot") == frame_name),
        None,
    )
    if contract_item is None:
        raise WidgetError("This dataframe is not available to this widget version.", "frame_not_allowed")
    source_name = str(contract_item.get("sourceName") or frame_name)
    owners = _dataframe_owners(notebook)
    node_id_for_frame = owners.get(source_name)
    if node_id_for_frame is None:
        raise WidgetConflictError(f'Dataframe "{source_name}" is no longer in this notebook.', "frame_missing")
    run_queryset = NotebookNodeRun.objects.for_team(notebook.team_id).filter(
        notebook=notebook,
        node_id=node_id_for_frame,
        status=NotebookNodeRun.Status.DONE,
    )
    run = run_queryset.filter(id=run_id).first() if run_id is not None else run_queryset.order_by("-created_at").first()
    if run is None:
        raise WidgetConflictError(f'Run the cell that creates "{source_name}" first.', "frame_not_ready")
    authorize_run(run)
    envelope = run.envelope if isinstance(run.envelope, dict) else {}
    columns = _columns_from_metadata(envelope.get("types"), envelope.get("columns"))
    expected_schema_hash = contract_item.get("schemaHash")
    if expected_schema_hash and _json_hash({"columns": columns}) != expected_schema_hash:
        raise WidgetConflictError(
            f'The columns in "{source_name}" changed. Generate a new widget version to use the new schema.',
            "frame_schema_changed",
        )
    total_row_count = _row_count_from_metadata(envelope.get("row_count"), envelope.get("first_page"))
    if offset >= MAX_FRAME_TOTAL_ROWS:
        raise WidgetError(
            f"Widget data is limited to {MAX_FRAME_TOTAL_ROWS:,} rows per dataframe.",
            "frame_row_limit",
        )
    page_limit = min(max(limit, 1), MAX_FRAME_PAGE_ROWS, MAX_FRAME_TOTAL_ROWS - offset)
    first_page = envelope.get("first_page")
    candidates: object
    requested_end = min(offset + page_limit, total_row_count)
    if isinstance(first_page, list) and requested_end <= len(first_page):
        candidates = first_page[offset : offset + page_limit]
    else:
        try:
            page = fetch_sql_v2_page(notebook, user, run, offset=offset, limit=page_limit)
        except (SQLV2KernelNotRunning, SQLV2PageError) as error:
            raise WidgetConflictError(
                f'Re-run the cell that creates "{source_name}" to load more rows.',
                "frame_page_unavailable",
            ) from error
        candidates = page.get("rows") if isinstance(page, dict) else []
        if isinstance(page, dict) and isinstance(page.get("row_count"), int):
            total_row_count = page["row_count"]
    return WidgetFrameRead(
        frame=_bounded_rows(
            name=frame_name,
            run_id=run.id,
            columns=columns,
            candidates=candidates,
            total_row_count=total_row_count,
            offset=offset,
        )
    )
