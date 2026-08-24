"""Fetchers for HubSpot's lookup tables: pipelines, pipeline stages, property definitions and owners.

These are not CRM objects — they have no `properties` envelope, no `/search` endpoint and no
server-side timestamp filter — so they are always a full refresh and reuse `helpers.fetch_data`
for auth refresh, retries and `paging.next.link` following.

Rows are flattened to a fixed column set (`HubspotMetadataEndpointConfig.columns`): missing fields
are backfilled with None so an optional field a portal never sets can't shift the table's schema
between syncs, and nested values are JSON-encoded so a heterogeneous `metadata` blob can't produce
a different PyArrow struct per batch.
"""

import json
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.helpers import fetch_data
from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.settings import (
    HUBSPOT_ENDPOINTS,
    HUBSPOT_METADATA_ENDPOINTS,
    PIPELINE_OBJECT_TYPES,
    apply_crm_api_version,
)

# A portal that hasn't enabled an object (or a grant that can't read it) answers with one of these
# for that object type only. Skipping keeps one unavailable object type from failing the table.
_SKIPPABLE_STATUSES = (403, 404)


def _normalize_row(row: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    normalized = {k: json.dumps(v) if isinstance(v, dict | list) else v for k, v in row.items()}
    for column in columns:
        normalized.setdefault(column, None)
    return normalized


def _iter_pages(
    path: str,
    api_key: str,
    refresh_token: str,
    source_id: str | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    try:
        yield from fetch_data(path, api_key, refresh_token, source_id=source_id)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status in _SKIPPABLE_STATUSES:
            logger.warning(f"Hubspot: skipping {path} (status={status}); the portal cannot read it")
            return
        raise


def get_pipelines_rows(
    api_key: str,
    refresh_token: str,
    logger: FilteringBoundLogger,
    source_id: str | None,
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    columns = HUBSPOT_METADATA_ENDPOINTS["pipelines"].columns
    for object_type in PIPELINE_OBJECT_TYPES:
        path = apply_crm_api_version(f"/crm/v3/pipelines/{object_type}", api_version)
        for page in _iter_pages(path, api_key, refresh_token, source_id, logger):
            # `stages` is dropped here — it is the pipeline_stages table.
            yield [
                _normalize_row({**{k: v for k, v in p.items() if k != "stages"}, "object_type": object_type}, columns)
                for p in page
            ]


def get_pipeline_stages_rows(
    api_key: str,
    refresh_token: str,
    logger: FilteringBoundLogger,
    source_id: str | None,
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    columns = HUBSPOT_METADATA_ENDPOINTS["pipeline_stages"].columns
    for object_type in PIPELINE_OBJECT_TYPES:
        path = apply_crm_api_version(f"/crm/v3/pipelines/{object_type}", api_version)
        for page in _iter_pages(path, api_key, refresh_token, source_id, logger):
            rows = [
                _normalize_row({**stage, "object_type": object_type, "pipeline_id": pipeline.get("id")}, columns)
                for pipeline in page
                for stage in pipeline.get("stages") or []
            ]
            if rows:
                yield rows


def get_properties_rows(
    api_key: str,
    refresh_token: str,
    logger: FilteringBoundLogger,
    source_id: str | None,
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    columns = HUBSPOT_METADATA_ENDPOINTS["properties"].columns
    for object_type in HUBSPOT_ENDPOINTS:
        path = apply_crm_api_version(f"/crm/v3/properties/{object_type}", api_version)
        for page in _iter_pages(path, api_key, refresh_token, source_id, logger):
            yield [_normalize_row({**p, "object_type": object_type}, columns) for p in page]


def get_owners_rows(
    api_key: str,
    refresh_token: str,
    logger: FilteringBoundLogger,
    source_id: str | None,
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    columns = HUBSPOT_METADATA_ENDPOINTS["owners"].columns
    path = apply_crm_api_version("/crm/v3/owners", api_version)
    for page in _iter_pages(path, api_key, refresh_token, source_id, logger):
        yield [_normalize_row(owner, columns) for owner in page]


METADATA_FETCHERS = {
    "pipelines": get_pipelines_rows,
    "pipeline_stages": get_pipeline_stages_rows,
    "properties": get_properties_rows,
    "owners": get_owners_rows,
}
