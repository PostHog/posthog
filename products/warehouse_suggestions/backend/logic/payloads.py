import json
from collections.abc import Collection, Iterable, Mapping
from dataclasses import asdict
from typing import Any
from uuid import UUID

from ..facade.contracts import (
    PAYLOAD_VERSION,
    CertifyPayload,
    DeprecatePayload,
    MaterializePayload,
    MaterializeSuggestionPayload,
    SourceRef,
    SuggestionPayload,
    SuggestionPayloadView,
    UnsupportedPayloadVersionError,
    VisibleSources,
)
from ..facade.enums import WarehouseSuggestionKind

SOURCE_FIELDS = ("live_sources", "unknown_sources")


def payload_to_json(payload: SuggestionPayload) -> dict[str, Any]:
    return json.loads(json.dumps(asdict(payload), default=str))


def payload_from_json(
    kind: WarehouseSuggestionKind, payload_version: int, data: Mapping[str, Any]
) -> SuggestionPayload:
    if payload_version != PAYLOAD_VERSION:
        raise UnsupportedPayloadVersionError(payload_version)
    if kind == WarehouseSuggestionKind.CERTIFY:
        return CertifyPayload(**data)
    if kind == WarehouseSuggestionKind.DEPRECATE:
        return DeprecatePayload(**data)
    sources = {field: tuple(_source_ref(source) for source in data[field]) for field in SOURCE_FIELDS}
    return MaterializePayload(**{**data, **sources})


def source_table_ids(payloads: Iterable[SuggestionPayload]) -> set[UUID]:
    return {
        source.warehouse_table_id
        for payload in payloads
        if isinstance(payload, MaterializePayload)
        for source in (*payload.live_sources, *payload.unknown_sources)
        if source.warehouse_table_id is not None
    }


def payload_view(payload: SuggestionPayload, readable_table_ids: Collection[UUID]) -> SuggestionPayloadView:
    if not isinstance(payload, MaterializePayload):
        return payload
    return MaterializeSuggestionPayload(
        subject_name=payload.subject_name,
        refresh_interval_seconds=payload.refresh_interval_seconds,
        saves_seconds_per_month=payload.saves_seconds_per_month,
        saves_bytes_per_month=payload.saves_bytes_per_month,
        freshness_today_seconds=payload.freshness_today_seconds,
        freshness_after_seconds=payload.freshness_after_seconds,
        live_sources=_visible_sources(payload.live_sources, readable_table_ids),
        unknown_sources=_visible_sources(payload.unknown_sources, readable_table_ids),
    )


def _visible_sources(sources: tuple[SourceRef, ...], readable_table_ids: Collection[UUID]) -> VisibleSources:
    names = tuple(
        source.name
        for source in sources
        if source.warehouse_table_id is None or source.warehouse_table_id in readable_table_ids
    )
    return VisibleSources(names=names, hidden_count=len(sources) - len(names))


def _source_ref(source: Mapping[str, Any]) -> SourceRef:
    table_id = source["warehouse_table_id"]
    return SourceRef(name=source["name"], warehouse_table_id=UUID(table_id) if table_id else None)
