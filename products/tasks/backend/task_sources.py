from uuid import UUID

from posthog.dataclasses import frozen

from products.tasks.backend.facade.profiles import SourceKind, TaskSource, TaskSourceError


@frozen
class SourceColumns:
    signal_report_id: str | None
    hog_flow_id: UUID | None


def apply_task_source(
    source: TaskSource | None, *, signal_report_id: str | None, hog_flow_id: UUID | None
) -> SourceColumns:
    if source is None:
        return SourceColumns(signal_report_id=signal_report_id, hog_flow_id=hog_flow_id)
    if signal_report_id is not None or hog_flow_id is not None:
        raise TaskSourceError("Pass the source as source or as signal_report_id and hog_flow_id, not both")
    if source.kind == SourceKind.SIGNAL_REPORT:
        return SourceColumns(signal_report_id=source.id, hog_flow_id=None)
    return SourceColumns(signal_report_id=None, hog_flow_id=UUID(source.id))


def source_from_columns(*, signal_report_id: str | None, hog_flow_id: UUID | None) -> TaskSource | None:
    if signal_report_id and hog_flow_id:
        raise TaskSourceError("A task has one source. Pass signal_report_id or hog_flow_id, not both")
    if signal_report_id:
        return TaskSource(kind=SourceKind.SIGNAL_REPORT, id=str(signal_report_id))
    if hog_flow_id:
        return TaskSource(kind=SourceKind.HOG_FLOW, id=str(hog_flow_id))
    return None
