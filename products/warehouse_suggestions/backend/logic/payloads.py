import json
from collections.abc import Collection, Iterable, Mapping
from dataclasses import asdict, fields
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
    UnmaterializePayload,
    UnsupportedPayloadVersionError,
    VisibleSources,
)
from ..facade.enums import (
    WarehouseSuggestionKind,
    WarehouseSuggestionRefreshIntervalBasis,
    WarehouseSuggestionRefreshMode,
)

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
    if kind == WarehouseSuggestionKind.UNMATERIALIZE:
        return UnmaterializePayload(**data)
    sources = {field: tuple(_source_ref(source) for source in data[field]) for field in SOURCE_FIELDS}
    return MaterializePayload(**{**data, **sources, **_refresh_fields(data)})


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
    shared = {field.name: getattr(payload, field.name) for field in fields(payload) if field.name not in SOURCE_FIELDS}
    return MaterializeSuggestionPayload(
        **shared,
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


def _refresh_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    basis = data.get("refresh_interval_basis")
    return {
        "refresh_mode": WarehouseSuggestionRefreshMode(data.get("refresh_mode", WarehouseSuggestionRefreshMode.FULL)),
        "unique_key": tuple(data.get("unique_key", ())),
        "refresh_interval_basis": WarehouseSuggestionRefreshIntervalBasis(basis) if basis else None,
    }
