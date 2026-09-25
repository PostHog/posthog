import re
import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

CLAY_BASE_URL = "https://api.clay.com/public/v0"
PAGE_SIZE = 100  # API maximum
REQUEST_TIMEOUT_SECONDS = 60

# Clay table IDs look like `t_0te9i4tZEHwc9hihBXu`, and appear after `/tables/` in table URLs.
_TABLE_ID_RE = re.compile(r"(?<![A-Za-z0-9_])t_[A-Za-z0-9]+")


@dataclasses.dataclass(frozen=True)
class ClayResumeConfig:
    next_cursor: str


def parse_table_ids(raw: str) -> list[str]:
    """Extract unique table IDs, in order, from pasted IDs or table URLs in any separator style."""
    return list(dict.fromkeys(_TABLE_ID_RE.findall(raw or "")))


def flatten_record(record: dict[str, Any]) -> dict[str, Any]:
    """Turn a record of Clay cells into a flat row.

    Only `success` cells carry a value. Enrichment columns return a structured object in the
    cell's `fields`, which goes into a sibling `<column>_fields` column so it is not lost. When the
    table already has a column with that name, the real column wins and the metadata is dropped.
    """
    row: dict[str, Any] = {}
    for name, cell in record.items():
        if not isinstance(cell, dict) or cell.get("status") != "success":
            row[name] = None
            continue
        row[name] = cell.get("value")
        fields_column = f"{name}_fields"
        if cell.get("fields") is not None and fields_column not in record:
            row[fields_column] = cell["fields"]
    return row


def _query_body(table_id: str, limit: int = PAGE_SIZE) -> dict[str, Any]:
    # No `select`: the API caps it at 20 fields, and we want every column of the table.
    return {"query": {"tables": [{"id": table_id}], "field_mode": "names"}, "limit": limit}


def clay_source(
    api_key: str,
    table_id: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ClayResumeConfig],
) -> SourceResponse:
    config: RESTAPIConfig = {
        "client": {
            "base_url": CLAY_BASE_URL,
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
            "auth": {
                "type": "api_key",
                "name": "clay-api-key",
                "api_key": api_key,
                "location": "header",
            },
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": table_id,
                "table_name": table_id,
                "write_disposition": "replace",
                "endpoint": {
                    "method": "POST",
                    "path": "/tables/query",
                    "json": _query_body(table_id),
                    "data_selector": "data",
                    "paginator": JSONResponseCursorPaginator(
                        cursor_path="cursor", cursor_param="cursor", param_location="json"
                    ),
                },
                "data_map": flatten_record,
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(ClayResumeConfig(next_cursor=str(state["cursor"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    # Rows carry no documented record id or timestamps, so every sync is a full replace. A row
    # updated while the scan runs can appear twice in that sync.
    return SourceResponse(name=table_id, items=lambda: resource, primary_keys=None)


def validate_credentials(api_key: str, table_ids: list[str]) -> tuple[bool, str | None]:
    if not table_ids:
        return False, "Enter at least one Clay table ID or table URL."

    session = make_tracked_session(headers={"clay-api-key": api_key}, redact_values=(api_key,))

    me = session.get(f"{CLAY_BASE_URL}/me", timeout=REQUEST_TIMEOUT_SECONDS)
    if me.status_code == 401:
        return False, "Clay rejected the API key. Create a new key under Settings > Account > API keys in Clay."
    if me.status_code != 200:
        return (
            False,
            f"Clay returned an unexpected status ({me.status_code}) while checking the API key. Try again in a few minutes.",
        )

    for table_id in table_ids:
        res = session.post(
            f"{CLAY_BASE_URL}/tables/query", json=_query_body(table_id, limit=1), timeout=REQUEST_TIMEOUT_SECONDS
        )
        if res.status_code == 200:
            continue
        if res.status_code == 403:
            return False, (
                f"Clay denied access to table {table_id}. Turn on Enable for API in the table's settings "
                "(Edit table settings > Integrations). This needs a Clay Enterprise plan, and the API key's "
                "user must have access to the table."
            )
        if res.status_code == 404:
            return False, f"Clay could not find table {table_id}. Check the table ID or URL."
        return (
            False,
            f"Clay returned an unexpected status ({res.status_code}) for table {table_id}. Try again in a few minutes.",
        )

    return True, None
