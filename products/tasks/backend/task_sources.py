from collections.abc import Iterable
from uuid import UUID

from django.db.models import Q

from posthog.dataclasses import frozen

from products.tasks.backend.facade.profiles import SourceKind, TaskSource, TaskSourceError


@frozen
class SourceColumns:
    signal_report_id: str | None
    hog_flow_id: UUID | None
    source: TaskSource | None


def apply_task_source(
    source: TaskSource | None, *, signal_report_id: str | None, hog_flow_id: UUID | None
) -> SourceColumns:
    if source is None:
        return SourceColumns(
            signal_report_id=signal_report_id,
            hog_flow_id=hog_flow_id,
            source=source_from_columns(signal_report_id=signal_report_id, hog_flow_id=hog_flow_id),
        )
    if signal_report_id is not None or hog_flow_id is not None:
        raise TaskSourceError("Pass the source as source or as signal_report_id and hog_flow_id, not both")
    if source.kind == SourceKind.SIGNAL_REPORT:
        return SourceColumns(signal_report_id=source.id, hog_flow_id=None, source=source)
    if source.kind == SourceKind.HOG_FLOW:
        return SourceColumns(signal_report_id=None, hog_flow_id=UUID(source.id), source=source)
    return SourceColumns(signal_report_id=None, hog_flow_id=None, source=source)


def source_from_columns(*, signal_report_id: str | None, hog_flow_id: UUID | None) -> TaskSource | None:
    if signal_report_id and hog_flow_id:
        raise TaskSourceError("A task has one source. Pass signal_report_id or hog_flow_id, not both")
    if signal_report_id:
        return TaskSource(kind=SourceKind.SIGNAL_REPORT, id=str(signal_report_id))
    if hog_flow_id:
        return TaskSource(kind=SourceKind.HOG_FLOW, id=str(hog_flow_id))
    return None


def source_q(kind: SourceKind, source_ids: Iterable[str | UUID], *, via: str = "") -> Q:
    ids = [str(source_id) for source_id in source_ids]
    on_new_columns = Q(**{f"{via}source_kind": kind.value, f"{via}source_id__in": ids})
    if kind == SourceKind.SIGNAL_REPORT:
        legacy_column = f"{via}signal_report_id__in"
    elif kind == SourceKind.HOG_FLOW:
        legacy_column = f"{via}hog_flow_id__in"
    else:
        return on_new_columns
    return on_new_columns | (Q(**{f"{via}source_kind__isnull": True}) & Q(**{legacy_column: ids}))


def idempotency_key_q(key: str, *, via: str = "") -> Q:
    return _idempotency_q("", key, via)


def idempotency_key_startswith_q(key_prefix: str, *, via: str = "") -> Q:
    return _idempotency_q("__startswith", key_prefix, via)


def _idempotency_q(lookup: str, value: str, via: str) -> Q:
    on_new_column = Q(**{f"{via}idempotency_key{lookup}": value})
    legacy = Q(**{f"{via}idempotency_key__isnull": True, f"{via}origin_key{lookup}": value})
    return on_new_column | legacy
