from collections.abc import Callable
from typing import Any, cast

from products.warehouse_sources.backend.temporal.data_imports.sources.coda.settings import CODA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

CODA_BASE_URL = "https://coda.io/apis/v1"
PAGE_SIZE = 100
ROWS_PAGE_SIZE = 200


def _cursor_paginator() -> JSONResponseCursorPaginator:
    # Coda hands back an opaque `nextPageToken` in the body and expects it echoed as `pageToken`;
    # a page without a token ends the stream, so an empty intermediate page (token present) keeps going.
    return JSONResponseCursorPaginator(cursor_path="nextPageToken", cursor_param="pageToken")


def _map_row(
    renames: dict[str, str] | None = None,
    lift_ids: dict[str, str] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    # `renames`: include_from_parent carries fields as `_<parent>_<field>`; rename them back to the
    # flat `_doc_id` / `_table_id` keys the composite primary keys and downstream schema expect.
    # `lift_ids`: analytics items nest their subject under `doc` / `page`; lift that object's id to a
    # top-level column so it can serve as a merge primary key.
    def _mapper(row: dict[str, Any]) -> dict[str, Any]:
        for src, dst in (renames or {}).items():
            if src in row:
                row[dst] = row.pop(src)
        for nested_key, dst in (lift_ids or {}).items():
            nested = row.get(nested_key)
            if isinstance(nested, dict) and "id" in nested:
                row[dst] = nested["id"]
        return row

    return _mapper


def _docs_resource() -> EndpointResource:
    return {
        "name": "docs",
        "endpoint": {
            "path": "/docs",
            "params": {"limit": PAGE_SIZE},
            "data_selector": "items",
            "paginator": _cursor_paginator(),
        },
    }


def _tables_resource() -> EndpointResource:
    return {
        "name": "tables",
        "endpoint": {
            "path": "/docs/{doc_id}/tables",
            "params": {
                "doc_id": {"type": "resolve", "resource": "docs", "field": "id"},
                "limit": PAGE_SIZE,
            },
            "data_selector": "items",
            "paginator": _cursor_paginator(),
        },
        # Carry the parent doc id into every table row so ids that are only unique within a doc
        # get a composite primary key.
        "include_from_parent": ["id"],
        "data_map": _map_row(renames={"_docs_id": "_doc_id"}),
    }


def _rows_resource() -> EndpointResource:
    return {
        "name": "rows",
        "endpoint": {
            "path": "/docs/{doc_id}/tables/{table_id}/rows",
            "params": {
                # Both path params bind fields of the same parent table row (doc_id is carried in
                # from the tables resource via include_from_parent above).
                "doc_id": {"type": "resolve", "resource": "tables", "field": "_doc_id"},
                "table_id": {"type": "resolve", "resource": "tables", "field": "id"},
                "limit": ROWS_PAGE_SIZE,
                # Column names instead of opaque column ids in `values`.
                "useColumnNames": "true",
            },
            "data_selector": "items",
            "paginator": _cursor_paginator(),
        },
        "include_from_parent": ["_doc_id", "id"],
        "data_map": _map_row(renames={"_tables__doc_id": "_doc_id", "_tables_id": "_table_id"}),
    }


def _columns_resource() -> EndpointResource:
    return {
        "name": "columns",
        "endpoint": {
            "path": "/docs/{doc_id}/tables/{table_id}/columns",
            "params": {
                # Both path params bind fields of the same parent table row (doc_id is carried in
                # from the tables resource via include_from_parent above).
                "doc_id": {"type": "resolve", "resource": "tables", "field": "_doc_id"},
                "table_id": {"type": "resolve", "resource": "tables", "field": "id"},
                "limit": PAGE_SIZE,
            },
            "data_selector": "items",
            "paginator": _cursor_paginator(),
        },
        "include_from_parent": ["_doc_id", "id"],
        "data_map": _map_row(renames={"_tables__doc_id": "_doc_id", "_tables_id": "_table_id"}),
    }


def _doc_analytics_resource() -> EndpointResource:
    return {
        "name": "doc_analytics",
        "endpoint": {
            "path": "/analytics/docs",
            "params": {"limit": PAGE_SIZE},
            "data_selector": "items",
            "paginator": _cursor_paginator(),
        },
        # Each item nests the doc under `doc`; lift its id so it can key the merge.
        "data_map": _map_row(lift_ids={"doc": "doc_id"}),
    }


def _page_analytics_resource() -> EndpointResource:
    return {
        "name": "page_analytics",
        "endpoint": {
            "path": "/analytics/docs/{doc_id}/pages",
            "params": {
                "doc_id": {"type": "resolve", "resource": "docs", "field": "id"},
                "limit": PAGE_SIZE,
            },
            "data_selector": "items",
            "paginator": _cursor_paginator(),
        },
        # Carry the parent doc id, and lift the nested page id, so each row has a composite key.
        "include_from_parent": ["id"],
        "data_map": _map_row(renames={"_docs_id": "_doc_id"}, lift_ids={"page": "page_id"}),
    }


def _folders_resource() -> EndpointResource:
    return {
        "name": "folders",
        "endpoint": {
            "path": "/folders",
            "params": {"limit": PAGE_SIZE},
            "data_selector": "items",
            "paginator": _cursor_paginator(),
        },
    }


def _resource_chain(endpoint: str) -> list[EndpointResource]:
    # Rows and columns fan out docs → tables → …; page analytics fans out docs → pages. Each
    # endpoint's chain is the resources up to and including it, so iterating the leaf drives its
    # parents lazily. Fresh dicts per call — config setup mutates.
    if endpoint == "docs":
        return [_docs_resource()]
    if endpoint == "tables":
        return [_docs_resource(), _tables_resource()]
    if endpoint == "rows":
        return [_docs_resource(), _tables_resource(), _rows_resource()]
    if endpoint == "columns":
        return [_docs_resource(), _tables_resource(), _columns_resource()]
    if endpoint == "doc_analytics":
        return [_doc_analytics_resource()]
    if endpoint == "page_analytics":
        return [_docs_resource(), _page_analytics_resource()]
    if endpoint == "folders":
        return [_folders_resource()]
    raise ValueError(f"Unknown Coda endpoint: {endpoint!r}")


def coda_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    resource_chain = _resource_chain(endpoint)
    config = CODA_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CODA_BASE_URL,
            "auth": {"type": "bearer", "token": api_token},
        },
        "resource_defaults": {},
        "resources": cast("list[str | EndpointResource]", resource_chain),
    }

    resources = rest_api_resources(rest_config, team_id, job_id, None)
    resource = next(r for r in resources if r.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )


def validate_credentials(api_token: str) -> bool:
    """Confirm the API token is valid with the whoami endpoint."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{CODA_BASE_URL}/whoami",
        headers={"Authorization": f"Bearer {api_token}"},
    )
    return ok
