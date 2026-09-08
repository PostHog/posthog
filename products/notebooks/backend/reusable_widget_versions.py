from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen

from products.notebooks.backend.models import GeneratedWidget, GeneratedWidgetGenerationJob, GeneratedWidgetVersion
from products.notebooks.backend.reusable_widgets import (
    ReusableWidgetDetail,
    ReusableWidgetVersionDetail,
    _published_widgets,
    _version_detail,
    get_reusable_widget,
)
from products.notebooks.backend.widgets import WidgetConflictError, WidgetError, WidgetRateLimitError, _prompt_history


@frozen
class ReusableWidgetVersionPage:
    results: list[ReusableWidgetVersionDetail]
    count: int
    next_offset: int | None


def list_reusable_widget_versions(
    *, team_id: int, widget_id: UUID, offset: int = 0, limit: int = 25
) -> ReusableWidgetVersionPage:
    # Keep Canvas build dependencies off notebook startup.
    from products.canvas.backend import notebook_integration as canvas_facade  # noqa: PLC0415

    widget = _published_widgets(team_id).filter(id=widget_id).first()
    if widget is None:
        raise WidgetError("This reusable widget does not exist.", "widget_not_found")
    queryset = (
        GeneratedWidgetVersion.objects.for_team(team_id).filter(widget=widget).exclude(id=widget.pending_version_id)
    )
    count = queryset.count()
    versions = list(queryset.order_by("-created_at", "-id")[offset : offset + limit])
    try:
        canvas_versions = canvas_facade.list_notebook_canvas_versions(
            team_id=team_id,
            canvas_id=widget.canvas_id,
            version_ids=[version.canvas_source_version_id for version in versions],
        )
    except canvas_facade.NotebookCanvasError as error:
        raise WidgetError("This reusable widget preview is unavailable.", "widget_unavailable") from error
    canvas_by_id = {version.id: version for version in canvas_versions}
    return ReusableWidgetVersionPage(
        results=[
            _version_detail(
                version=version,
                version_number=count - offset - index,
                canvas_version=canvas_by_id.get(version.canvas_source_version_id),
            )
            for index, version in enumerate(versions)
        ],
        count=count,
        next_offset=offset + limit if offset + limit < count else None,
    )


def _check_restore_available(widget: GeneratedWidget, expected_current_version_id: UUID) -> None:
    if widget.current_version_id != expected_current_version_id:
        raise WidgetConflictError("This widget changed. Reload it before making a version latest.", "revert_conflict")
    if (
        widget.pending_version_id is not None
        or GeneratedWidgetGenerationJob.objects.for_team(widget.team_id)
        .filter(widget=widget, status__in=GeneratedWidgetGenerationJob.ACTIVE_STATUSES)
        .exists()
    ):
        raise WidgetConflictError(
            "Finish or discard the current update before making a version latest.", "revert_conflict"
        )


def restore_reusable_widget_version(
    *, team_id: int, widget_id: UUID, version_id: UUID, expected_current_version_id: UUID, user_id: int
) -> ReusableWidgetDetail:
    # Keep Canvas build dependencies off notebook startup.
    from products.canvas.backend import notebook_integration as canvas_facade  # noqa: PLC0415

    widget = _published_widgets(team_id).select_related("current_version").filter(id=widget_id).first()
    if widget is None or widget.current_version is None:
        raise WidgetError("This reusable widget does not exist.", "widget_not_found")
    _check_restore_available(widget, expected_current_version_id)
    current = widget.current_version
    target = GeneratedWidgetVersion.objects.for_team(team_id).filter(widget=widget, id=version_id).first()
    if target is None:
        raise WidgetError("This widget version does not exist.", "version_missing")
    if target.id == current.id:
        return get_reusable_widget(team_id=team_id, widget_id=widget_id)
    try:
        source = canvas_facade.get_notebook_canvas_source(
            team_id=team_id, canvas_id=widget.canvas_id, version_id=target.canvas_source_version_id
        )
        prepared = canvas_facade.prepare_notebook_canvas_source(
            team_id=team_id,
            canvas_id=widget.canvas_id,
            user_id=user_id,
            source=source,
            input_names=[
                str(item["slot"]) for item in target.input_contract if isinstance(item, dict) and item.get("slot")
            ],
            prompt="Restore an earlier version.",
            name=widget.name,
            expected_current_version_id=current.canvas_source_version_id,
        )
        with transaction.atomic():
            widget = _published_widgets(team_id).select_for_update().filter(id=widget_id).first()
            if widget is None:
                raise WidgetError("This reusable widget does not exist.", "widget_not_found")
            _check_restore_available(widget, expected_current_version_id)
            source_version_id = canvas_facade.publish_prepared_notebook_canvas_source(
                team_id=team_id, user_id=user_id, prepared=prepared
            )
            version = GeneratedWidgetVersion.objects.for_team(team_id).create(
                team_id=team_id,
                widget=widget,
                canvas_source_version_id=source_version_id,
                parent_version=current,
                reverted_from_version=target,
                title=target.title,
                operation=GeneratedWidgetVersion.Operation.REVERT,
                prompt_delta="Restored an earlier version.",
                prompt_history=_prompt_history(target),
                model=target.model,
                generator_version=target.generator_version,
                input_contract=target.input_contract,
                demo_data=target.demo_data,
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
            widget.updated_at = timezone.now()
            widget.save(update_fields=["current_version", "updated_at"])
    except canvas_facade.NotebookCanvasVersionConflictError as error:
        raise WidgetConflictError(
            "This widget changed. Reload it before making a version latest.", "revert_conflict"
        ) from error
    except canvas_facade.NotebookCanvasBuildCapacityError as error:
        raise WidgetRateLimitError("Widget build capacity is full. Try again shortly.", "build_capacity") from error
    except canvas_facade.NotebookCanvasNotFoundError as error:
        raise WidgetError("The selected widget version is no longer available.", "version_missing") from error
    except canvas_facade.NotebookCanvasError as error:
        raise WidgetError("The widget preview could not be updated. Try again.", "build_failed") from error
    return get_reusable_widget(team_id=team_id, widget_id=widget_id)
