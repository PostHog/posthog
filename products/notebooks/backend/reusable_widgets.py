import json
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Q, TextField
from django.db.models.functions import Cast
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models import User

from products.notebooks.backend.models import GeneratedWidget, GeneratedWidgetVersion, Notebook, NotebookWidgetInstance
from products.notebooks.backend.widgets import (
    WidgetConflictError,
    WidgetError,
    WidgetFrameRead,
    WidgetInputInspection,
    WidgetRateLimitError,
    WidgetSecurityReviewState,
    WidgetStatus,
    _security_review_state,
    assert_widget_node_exists,
    get_widget_status,
    read_widget_frame,
    start_widget_generation,
)

MAX_REUSABLE_WIDGET_DEMO_ROWS = 20
MAX_REUSABLE_WIDGET_DEMO_BYTES = 512 * 1_024
MAX_REUSABLE_WIDGET_BINDING_HOG_LENGTH = 10_000
MAX_REUSABLE_WIDGET_BINDINGS_BYTES = 256 * 1_024


@frozen
class ReusableWidgetSummary:
    id: UUID
    name: str
    description: str
    tags: list[str]
    publication_status: str
    current_version_id: UUID
    version_count: int
    instance_count: int
    created_at: datetime
    published_at: datetime
    updated_at: datetime


@frozen
class ReusableWidgetPage:
    results: list[ReusableWidgetSummary]
    count: int
    next_offset: int | None


@frozen
class ReusableWidgetVersionDetail:
    id: UUID
    title: str
    version: int
    operation: str
    model: str | None
    artifact_url: str | None
    build_status: str | None
    build_hash: str | None
    frame_names: list[str]
    input_contract: list[dict[str, object]]
    security_review: WidgetSecurityReviewState | None
    has_demo_data: bool
    created_at: datetime


@frozen
class ReusableWidgetDetail:
    id: UUID
    name: str
    description: str
    tags: list[str]
    publication_status: str
    current_version: ReusableWidgetVersionDetail
    version_count: int
    instance_count: int
    created_at: datetime
    published_at: datetime
    updated_at: datetime


def _published_widgets(team_id: int):
    return GeneratedWidget.objects.for_team(team_id).filter(
        publication_status=GeneratedWidget.PublicationStatus.PUBLISHED,
        current_version__isnull=False,
        published_at__isnull=False,
    )


def _tag_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _input_contract(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _summary(widget: GeneratedWidget) -> ReusableWidgetSummary:
    if widget.current_version_id is None or widget.published_at is None:
        raise WidgetError("This reusable widget is unavailable.", "widget_unavailable")
    updated_at = widget.updated_at or widget.published_at
    return ReusableWidgetSummary(
        id=widget.id,
        name=widget.name,
        description=widget.description,
        tags=_tag_list(widget.tags),
        publication_status=widget.publication_status,
        current_version_id=widget.current_version_id,
        version_count=widget.version_count,
        instance_count=widget.instance_count,
        created_at=widget.created_at,
        published_at=widget.published_at,
        updated_at=updated_at,
    )


def list_reusable_widgets(*, team_id: int, search: str = "", offset: int = 0, limit: int = 50) -> ReusableWidgetPage:
    queryset = _published_widgets(team_id)
    if search:
        queryset = queryset.annotate(tags_text=Cast("tags", TextField())).filter(
            Q(name__icontains=search) | Q(description__icontains=search) | Q(tags_text__icontains=search)
        )
    queryset = queryset.annotate(
        version_count=Count("versions", distinct=True),
        instance_count=Count("notebook_instances", distinct=True),
    )
    count = queryset.count()
    widgets = queryset.order_by("-updated_at", "-published_at", "name")[offset : offset + limit]
    return ReusableWidgetPage(
        results=[_summary(widget) for widget in widgets],
        count=count,
        next_offset=offset + limit if offset + limit < count else None,
    )


def _canvas_version(widget: GeneratedWidget, version: GeneratedWidgetVersion):
    from products.canvas.backend import (  # noqa: PLC0415 — keeps Canvas build imports off notebook startup
        notebook_integration as canvas_facade,
    )

    try:
        versions = canvas_facade.list_notebook_canvas_versions(
            team_id=widget.team_id,
            canvas_id=widget.canvas_id,
            version_ids=[version.canvas_source_version_id],
        )
    except canvas_facade.NotebookCanvasError as error:
        raise WidgetError("This reusable widget preview is unavailable.", "widget_unavailable") from error
    return versions[0] if versions else None


def get_reusable_widget(*, team_id: int, widget_id: UUID) -> ReusableWidgetDetail:
    widget = (
        _published_widgets(team_id)
        .select_related("current_version")
        .annotate(
            version_count=Count("versions", distinct=True),
            instance_count=Count("notebook_instances", distinct=True),
        )
        .filter(id=widget_id)
        .first()
    )
    if widget is None or widget.current_version is None or widget.published_at is None:
        raise WidgetError("This reusable widget does not exist.", "widget_not_found")
    canvas_version = _canvas_version(widget, widget.current_version)
    contract = _input_contract(widget.current_version.input_contract)
    return ReusableWidgetDetail(
        id=widget.id,
        name=widget.name,
        description=widget.description,
        tags=_tag_list(widget.tags),
        publication_status=widget.publication_status,
        current_version=ReusableWidgetVersionDetail(
            id=widget.current_version.id,
            title=widget.current_version.title,
            version=widget.version_count,
            operation=widget.current_version.operation,
            model=widget.current_version.model or None,
            artifact_url=canvas_version.artifact_url if canvas_version is not None else None,
            build_status=canvas_version.build_status if canvas_version is not None else None,
            build_hash=canvas_version.build_hash if canvas_version is not None else None,
            frame_names=[str(item["slot"]) for item in contract if item.get("slot")],
            input_contract=contract,
            security_review=_security_review_state(widget.current_version),
            has_demo_data=bool(widget.current_version.demo_data),
            created_at=widget.current_version.created_at,
        ),
        version_count=widget.version_count,
        instance_count=widget.instance_count,
        created_at=widget.created_at,
        published_at=widget.published_at,
        updated_at=widget.updated_at or widget.published_at,
    )


def _fit_demo_data(frames: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    while len(json.dumps(frames, separators=(",", ":"), default=str).encode()) > MAX_REUSABLE_WIDGET_DEMO_BYTES:
        largest = max(frames.values(), key=lambda frame: len(frame.get("rows", [])), default=None)
        if largest is None:
            break
        rows = largest.get("rows")
        if not isinstance(rows, list) or not rows:
            raise WidgetError("The widget demo data is too large to save.", "demo_data_too_large")
        rows.pop()
        largest["includedRowCount"] = len(rows)
        largest["truncated"] = True
    return frames


def _capture_demo_data(
    *, notebook: Notebook, node_id: str, version: GeneratedWidgetVersion, authorize_run, user: User | None
) -> dict[str, dict[str, object]]:
    frames: dict[str, dict[str, object]] = {}
    for contract_item in _input_contract(version.input_contract):
        slot = contract_item.get("slot")
        if not isinstance(slot, str):
            continue
        frame = read_widget_frame(
            notebook=notebook,
            node_id=node_id,
            frame_name=slot,
            authorize_run=authorize_run,
            user=user,
            version_id=version.id,
            limit=MAX_REUSABLE_WIDGET_DEMO_ROWS,
        ).frame
        frame["runId"] = str(frame["runId"])
        frame["nextOffset"] = None
        frames[slot] = frame
    return _fit_demo_data(frames)


def publish_reusable_widget(
    *,
    notebook: Notebook,
    node_id: str,
    name: str,
    description: str,
    tags: list[str],
    user: User,
    authorize_run,
) -> ReusableWidgetDetail:
    assert_widget_node_exists(notebook, node_id)
    instance = (
        NotebookWidgetInstance.objects.for_team(notebook.team_id)
        .select_related("widget", "widget__current_version")
        .filter(notebook=notebook, node_id=node_id)
        .first()
    )
    if instance is None or instance.widget.current_version is None:
        raise WidgetConflictError("Generate the widget before making it reusable.", "version_missing")
    if instance.widget.publication_status != GeneratedWidget.PublicationStatus.PRIVATE:
        raise WidgetConflictError("This widget is already reusable.", "widget_already_reusable")
    version = instance.widget.current_version
    demo_data = _capture_demo_data(
        notebook=notebook,
        node_id=node_id,
        version=version,
        authorize_run=authorize_run,
        user=user,
    )
    original_bindings = {
        str(item["slot"]): {"source": str(item.get("sourceName") or item["slot"])}
        for item in _input_contract(version.input_contract)
        if item.get("slot")
    }
    published_at = timezone.now()
    with transaction.atomic():
        widget = GeneratedWidget.objects.for_team(notebook.team_id).select_for_update().get(id=instance.widget_id)
        locked_instance = (
            NotebookWidgetInstance.objects.for_team(notebook.team_id).select_for_update().get(id=instance.id)
        )
        locked_version = (
            GeneratedWidgetVersion.objects.for_team(notebook.team_id).select_for_update().get(id=version.id)
        )
        if widget.publication_status != GeneratedWidget.PublicationStatus.PRIVATE:
            raise WidgetConflictError("This widget is already reusable.", "widget_already_reusable")
        if widget.current_version_id != version.id:
            raise WidgetConflictError(
                "This widget changed while it was being made reusable. Try again.", "publication_conflict"
            )
        widget.name = name
        widget.description = description
        widget.tags = tags
        widget.publication_status = GeneratedWidget.PublicationStatus.PUBLISHED
        widget.published_by = user
        widget.published_at = published_at
        widget.updated_at = published_at
        widget.save(
            update_fields=[
                "name",
                "description",
                "tags",
                "publication_status",
                "published_by",
                "published_at",
                "updated_at",
            ]
        )
        locked_version.demo_data = demo_data
        locked_version.save(update_fields=["demo_data"])
        locked_instance.pinned_version = None
        locked_instance.input_bindings = original_bindings
        locked_instance.save(update_fields=["pinned_version", "input_bindings"])
    return get_reusable_widget(team_id=notebook.team_id, widget_id=widget.id)


def _normalized_bindings(
    *, version: GeneratedWidgetVersion, input_bindings: dict[str, object]
) -> dict[str, dict[str, object]]:
    contract = _input_contract(version.input_contract)
    slots = {str(item["slot"]) for item in contract if item.get("slot")}
    unknown_slots = set(input_bindings) - slots
    if unknown_slots:
        raise WidgetError(f'"{sorted(unknown_slots)[0]}" is not an input for this widget.', "binding_not_allowed")
    result: dict[str, dict[str, object]] = {}
    for item in contract:
        slot = item.get("slot")
        if not isinstance(slot, str):
            continue
        raw_binding = input_bindings.get(slot, {})
        if not isinstance(raw_binding, dict):
            raise WidgetError(f'The binding for "{slot}" is invalid.', "binding_invalid")
        source = raw_binding.get("source", item.get("sourceName", slot))
        if not isinstance(source, str) or not source:
            raise WidgetError(f'Choose a dataframe for "{slot}".', "binding_source_missing")
        binding: dict[str, object] = {"source": source}
        hog = raw_binding.get("hog")
        bytecode = raw_binding.get("bytecode")
        if hog is not None:
            if not isinstance(hog, str) or len(hog) > MAX_REUSABLE_WIDGET_BINDING_HOG_LENGTH:
                raise WidgetError(f'The Hog mapping for "{slot}" is invalid.', "binding_hog_invalid")
            binding["hog"] = hog
        if bytecode is not None:
            if not isinstance(bytecode, list) or not bytecode or bytecode[0] != "_H":
                raise WidgetError(f'The compiled Hog mapping for "{slot}" is invalid.', "binding_bytecode_invalid")
            binding["bytecode"] = bytecode
        result[slot] = binding
    if len(json.dumps(result, separators=(",", ":"), default=str).encode()) > MAX_REUSABLE_WIDGET_BINDINGS_BYTES:
        raise WidgetError("The reusable widget input mappings are too large.", "bindings_too_large")
    return result


def attach_reusable_widget(
    *,
    notebook: Notebook,
    node_id: str,
    widget_id: UUID,
    version_id: UUID | None,
    input_bindings: dict[str, object],
    user: User,
) -> WidgetStatus:
    assert_widget_node_exists(notebook, node_id)
    widget = _published_widgets(notebook.team_id).select_related("current_version").filter(id=widget_id).first()
    if widget is None or widget.current_version is None:
        raise WidgetError("This reusable widget does not exist.", "widget_not_found")
    version = (
        GeneratedWidgetVersion.objects.for_team(notebook.team_id).filter(id=version_id, widget=widget).first()
        if version_id is not None
        else widget.current_version
    )
    if version is None:
        raise WidgetError("This reusable widget version does not exist.", "version_missing")
    bindings = _normalized_bindings(version=version, input_bindings=input_bindings)
    with transaction.atomic():
        existing = (
            NotebookWidgetInstance.objects.for_team(notebook.team_id)
            .select_for_update()
            .filter(notebook=notebook, node_id=node_id)
            .first()
        )
        if existing is not None and existing.widget_id != widget.id:
            raise WidgetConflictError("This notebook node already belongs to another widget.", "instance_conflict")
        if existing is None:
            NotebookWidgetInstance.objects.for_team(notebook.team_id).create(
                team_id=notebook.team_id,
                notebook=notebook,
                node_id=node_id,
                widget=widget,
                pinned_version=version if version_id is not None else None,
                input_bindings=bindings,
                created_by=user,
            )
        else:
            existing.pinned_version = version if version_id is not None else None
            existing.input_bindings = bindings
            existing.save(update_fields=["pinned_version", "input_bindings"])
    return get_widget_status(notebook=notebook, node_id=node_id)


def fork_reusable_widget(*, notebook: Notebook, node_id: str, user: User) -> WidgetStatus:
    from products.canvas.backend import (  # noqa: PLC0415 — keeps Canvas storage imports off notebook startup
        notebook_integration as canvas_facade,
    )
    from products.tasks.backend.facade import (  # noqa: PLC0415 — keeps Tasks imports off notebook startup
        api as tasks_facade,
    )

    assert_widget_node_exists(notebook, node_id)
    instance = (
        NotebookWidgetInstance.objects.for_team(notebook.team_id)
        .select_related("widget", "widget__current_version", "pinned_version")
        .filter(notebook=notebook, node_id=node_id)
        .first()
    )
    if instance is None or instance.widget.publication_status != GeneratedWidget.PublicationStatus.PUBLISHED:
        raise WidgetConflictError("Only a reusable widget can be forked.", "widget_not_reusable")
    source_version = instance.pinned_version or instance.widget.current_version
    if source_version is None:
        raise WidgetError("The reusable widget version is unavailable.", "version_missing")

    fork_name = f"{instance.widget.name[:393]} (fork)"
    try:
        source = canvas_facade.get_notebook_canvas_source(
            team_id=notebook.team_id,
            canvas_id=instance.widget.canvas_id,
            version_id=source_version.canvas_source_version_id,
        )
        channel_id = tasks_facade.ensure_personal_channel_id(team_id=notebook.team_id, user_id=user.id)
        canvas_id = canvas_facade.create_notebook_canvas(
            team_id=notebook.team_id,
            user_id=user.id,
            channel_id=channel_id,
            name=fork_name,
            context=f"Forked from reusable widget {instance.widget.id}",
        )
        prepared_source = canvas_facade.prepare_notebook_canvas_source(
            team_id=notebook.team_id,
            canvas_id=canvas_id,
            user_id=user.id,
            source=source,
            input_names=[
                str(item["slot"])
                for item in _input_contract(source_version.input_contract)
                if isinstance(item.get("slot"), str)
            ],
            prompt="Fork reusable widget",
            name=source_version.title or fork_name,
            expected_current_version_id=None,
        )
        publication = canvas_facade.publish_prepared_notebook_canvas_source(
            team_id=notebook.team_id,
            user_id=user.id,
            prepared=prepared_source,
        )
    except canvas_facade.NotebookCanvasBuildCapacityError as error:
        raise WidgetRateLimitError("Widget build capacity is full. Try again shortly.", "build_capacity") from error
    except canvas_facade.NotebookCanvasError as error:
        raise WidgetError("The reusable widget could not be forked. Try again.", "fork_failed") from error

    with transaction.atomic():
        locked_instance = (
            NotebookWidgetInstance.objects.for_team(notebook.team_id).select_for_update().get(id=instance.id)
        )
        locked_source_version = locked_instance.pinned_version or locked_instance.widget.current_version
        if (
            locked_instance.widget_id != instance.widget_id
            or locked_source_version is None
            or locked_source_version.id != source_version.id
        ):
            raise WidgetConflictError("This widget changed before it could be forked.", "fork_conflict")
        widget = GeneratedWidget.objects.for_team(notebook.team_id).create(
            team_id=notebook.team_id,
            name=fork_name,
            canvas_id=canvas_id,
            created_by=user,
        )
        version = GeneratedWidgetVersion.objects.for_team(notebook.team_id).create(
            team_id=notebook.team_id,
            widget=widget,
            canvas_source_version_id=publication,
            title=source_version.title,
            operation=GeneratedWidgetVersion.Operation.INITIAL,
            prompt_delta="Forked from a reusable widget.",
            prompt_history=source_version.prompt_history,
            model=source_version.model,
            generator_version=source_version.generator_version,
            input_contract=source_version.input_contract,
            schema_hash=source_version.schema_hash,
            security_review_severity=source_version.security_review_severity,
            security_review_summary=source_version.security_review_summary,
            security_review_findings=source_version.security_review_findings,
            security_review_model=source_version.security_review_model,
            security_review_version=source_version.security_review_version,
            security_reviewed_at=source_version.security_reviewed_at,
            created_by=user,
        )
        widget.current_version = version
        widget.save(update_fields=["current_version"])
        locked_instance.widget = widget
        locked_instance.pinned_version = version
        locked_instance.save(update_fields=["widget", "pinned_version"])
    return get_widget_status(notebook=notebook, node_id=node_id)


def read_reusable_widget_demo_frame(*, team_id: int, widget_id: UUID, frame_name: str) -> WidgetFrameRead:
    widget = _published_widgets(team_id).select_related("current_version").filter(id=widget_id).first()
    if widget is None or widget.current_version is None:
        raise WidgetError("This reusable widget does not exist.", "widget_not_found")
    demo_data = widget.current_version.demo_data
    frame = demo_data.get(frame_name) if isinstance(demo_data, dict) else None
    if not isinstance(frame, dict):
        raise WidgetError("This demo dataframe is unavailable.", "frame_not_found")
    return WidgetFrameRead(frame=frame)


def read_reusable_widget_source(*, team_id: int, widget_id: UUID, version_id: UUID | None = None) -> str:
    from products.canvas.backend import (  # noqa: PLC0415 — keeps Canvas storage imports off notebook startup
        notebook_integration as canvas_facade,
    )

    widget = _published_widgets(team_id).filter(id=widget_id).first()
    if widget is None:
        raise WidgetError("This reusable widget does not exist.", "widget_not_found")
    version = (
        GeneratedWidgetVersion.objects.for_team(team_id).filter(id=version_id, widget=widget).first()
        if version_id is not None
        else widget.current_version
    )
    if version is None:
        raise WidgetError("This reusable widget version does not exist.", "version_missing")
    try:
        return canvas_facade.get_notebook_canvas_source(
            team_id=team_id,
            canvas_id=widget.canvas_id,
            version_id=version.canvas_source_version_id,
        )
    except canvas_facade.NotebookCanvasError as error:
        raise WidgetError("This reusable widget source is unavailable.", "source_unavailable") from error


def start_reusable_widget_generation(
    *,
    team_id: int,
    widget_id: UUID,
    prompt: str,
    model: str,
    generation_id: UUID,
    operation: str,
    expected_current_version_id: UUID,
    user_id: int,
) -> WidgetStatus:
    widget = _published_widgets(team_id).select_related("current_version").filter(id=widget_id).first()
    if widget is None or widget.current_version is None:
        raise WidgetError("This reusable widget does not exist.", "widget_not_found")
    instance = (
        NotebookWidgetInstance.objects.for_team(team_id)
        .select_related("notebook")
        .filter(widget=widget, notebook__deleted=False)
        .order_by("created_at")
        .first()
    )
    if instance is None:
        raise WidgetConflictError(
            "This reusable widget has no notebook placement to build from. Add it to a notebook first.",
            "instance_missing",
        )
    return start_widget_generation(
        notebook=instance.notebook,
        node_id=instance.node_id,
        prompt=prompt,
        user_id=user_id,
        inspection=WidgetInputInspection(resolved_inputs=[]),
        model=model,
        generation_id=generation_id,
        operation=operation,
        expected_current_version_id=expected_current_version_id,
        allow_reusable=True,
        input_contract_override=_input_contract(widget.current_version.input_contract),
    )


def get_reusable_widget_status(*, team_id: int, widget_id: UUID) -> WidgetStatus:
    widget = _published_widgets(team_id).filter(id=widget_id).first()
    if widget is None:
        raise WidgetError("This reusable widget does not exist.", "widget_not_found")
    instance = (
        NotebookWidgetInstance.objects.for_team(team_id)
        .select_related("notebook")
        .filter(widget=widget, notebook__deleted=False)
        .order_by("created_at")
        .first()
    )
    if instance is None:
        raise WidgetConflictError("This reusable widget has no active notebook placement.", "instance_missing")
    return get_widget_status(notebook=instance.notebook, node_id=instance.node_id)
