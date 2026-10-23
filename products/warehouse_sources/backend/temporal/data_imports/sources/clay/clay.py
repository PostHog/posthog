import re
import dataclasses
from datetime import UTC, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

CLAY_BASE_URL = "https://api.clay.com/public/v0"
PAGE_SIZE = 100  # API maximum
REQUEST_TIMEOUT_SECONDS = 60

CREDIT_BALANCES_SCHEMA = "credit_balances"
# The balance endpoint returns only the current balance, so each sync stamps the row with the time it
# was read. That timestamp is the append cursor, which builds a balance history across syncs.
CREDIT_BALANCES_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "retrieved_at",
        "type": IncrementalFieldType.DateTime,
        "field": "retrieved_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]

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


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": CLAY_BASE_URL,
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
        "auth": {
            "type": "api_key",
            "name": "clay-api-key",
            "api_key": api_key,
            "location": "header",
        },
    }


def clay_source(
    api_key: str,
    table_id: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ClayResumeConfig],
) -> SourceResponse:
    config: RESTAPIConfig = {
        "client": _client_config(api_key),
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


def credit_balance_row(balance: dict[str, Any], retrieved_at: datetime) -> dict[str, Any]:
    # Clay sends whole balances as JSON integers. Cast to float so the first snapshot does not
    # create an int64 column that a later fractional balance cannot be written to.
    row: dict[str, Any] = {**balance, "retrieved_at": retrieved_at}
    for field in ("balance", "action_execution_balance"):
        if row.get(field) is not None:
            row[field] = float(row[field])
    return row


def clay_credit_balances_source(api_key: str, team_id: int, job_id: str) -> SourceResponse:
    retrieved_at = datetime.now(UTC)
    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": CREDIT_BALANCES_SCHEMA,
                "table_name": CREDIT_BALANCES_SCHEMA,
                "write_disposition": "replace",
                "endpoint": {
                    "path": "/credits/balance",
                    "data_selector": "$",
                    "paginator": "single_page",
                },
                "data_map": lambda balance: credit_balance_row(balance, retrieved_at),
                "table_format": "delta",
            }
        ],
    }
    resource = rest_api_resource(config, team_id, job_id, None)

    return SourceResponse(
        name=CREDIT_BALANCES_SCHEMA,
        items=lambda: resource,
        primary_keys=["retrieved_at"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["retrieved_at"],
    )


_CLAY_REJECTED_KEY_MESSAGE = (
    "Clay rejected PostHog's request while checking your API key. Create a new key under "
    "Settings > Account > API keys in Clay, then reconnect."
)

_CLAY_REJECTED_TABLE_MESSAGE = (
    "Clay rejected PostHog's request for one of your tables. Check that each value is a Clay table "
    "ID or table URL, and that Enable for API is on in the table's settings."
)

_CLAY_UNAVAILABLE_MESSAGE = (
    "Clay couldn't complete the request. Try again in a few minutes, and contact Clay support if it keeps failing."
)


def _unexpected_status_message(status_code: int, rejected_message: str) -> str:
    """Copy for a status the checks above don't recognise.

    A 429 or a 5xx clears on its own, so waiting is a real next step for both. Every other 4xx
    fails the same way on every attempt, so it has to point at what the customer can change.
    """
    return _CLAY_UNAVAILABLE_MESSAGE if status_code == 429 or status_code >= 500 else rejected_message


def validate_credentials(api_key: str, table_ids: list[str]) -> tuple[bool, str | None]:
    if not table_ids:
        return False, "Enter at least one Clay table ID or table URL."

    session = make_tracked_session(headers={"clay-api-key": api_key}, redact_values=(api_key,))

    me = session.get(f"{CLAY_BASE_URL}/me", timeout=REQUEST_TIMEOUT_SECONDS)
    if me.status_code == 401:
        return False, "Clay rejected the API key. Create a new key under Settings > Account > API keys in Clay."
    if me.status_code != 200:
        return False, _unexpected_status_message(me.status_code, _CLAY_REJECTED_KEY_MESSAGE)

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
        return False, _unexpected_status_message(res.status_code, _CLAY_REJECTED_TABLE_MESSAGE)

    return True, None
