from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# Wufoo caps `pageSize` at 100 rows per request.
PAGE_SIZE = 100
# `forms.json` documents `page`/`limit` paging with a maximum `limit` of 1000.
FORMS_PAGE_LIMIT = 1000

FORM_FANOUT = DependentEndpointConfig(
    parent_name="forms",
    resolve_param="hash",
    resolve_field="Hash",
    include_from_parent=["Hash"],
    parent_field_renames={"Hash": "form_hash"},
    parent_params={"limit": FORMS_PAGE_LIMIT},
)

REPORT_FANOUT = DependentEndpointConfig(
    parent_name="reports",
    resolve_param="hash",
    resolve_field="Hash",
    include_from_parent=["Hash"],
    parent_field_renames={"Hash": "report_hash"},
)


@dataclass(frozen=True)
class WufooEndpointConfig:
    name: str
    # Path relative to https://<subdomain>.wufoo.com/api/v3 (includes the .json suffix).
    path: str
    # Top-level key in the JSON response that holds the list of records.
    data_key: str
    # Wufoo identifies every top-level object with a stable `Hash`, so it is a safe table-wide
    # primary key (forms, reports, and users all expose one).
    primary_keys: list[str] = field(default_factory=lambda: ["Hash"])
    fanout: DependentEndpointConfig | None = None
    # Whether the endpoint takes `pageStart`/`pageSize`. Fields endpoints return the whole list.
    paginated: bool = True
    params: dict[str, Any] = field(default_factory=dict)
    page_size: int = PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


WUFOO_ENDPOINTS: dict[str, WufooEndpointConfig] = {
    "forms": WufooEndpointConfig(name="forms", path="forms.json", data_key="Forms"),
    "reports": WufooEndpointConfig(name="reports", path="reports.json", data_key="Reports"),
    "users": WufooEndpointConfig(name="users", path="users.json", data_key="Users"),
    # EntryId and field IDs are unique only within one form or report, so the parent hash is part
    # of every child key.
    "form_entries": WufooEndpointConfig(
        name="form_entries",
        path="forms/{hash}/entries.json",
        data_key="Entries",
        primary_keys=["form_hash", "EntryId"],
        fanout=FORM_FANOUT,
        # An explicit sort keeps offset pages stable while new entries arrive during the sync.
        params={"system": "true", "sort": "EntryId", "sortDirection": "ASC"},
    ),
    "form_fields": WufooEndpointConfig(
        name="form_fields",
        path="forms/{hash}/fields.json",
        data_key="Fields",
        primary_keys=["form_hash", "ID"],
        fanout=FORM_FANOUT,
        paginated=False,
        params={"system": "true"},
    ),
    "report_entries": WufooEndpointConfig(
        name="report_entries",
        path="reports/{hash}/entries.json",
        data_key="Entries",
        primary_keys=["report_hash", "EntryId"],
        fanout=REPORT_FANOUT,
        params={"system": "true"},
    ),
    "report_fields": WufooEndpointConfig(
        name="report_fields",
        path="reports/{hash}/fields.json",
        data_key="Fields",
        primary_keys=["report_hash", "ID"],
        fanout=REPORT_FANOUT,
        paginated=False,
        params={"system": "true"},
    ),
}

ENDPOINTS = tuple(WUFOO_ENDPOINTS.keys())

# Every endpoint is full refresh. The account-level list endpoints expose no server-side
# `updated_after`-style cursor. Entries can be edited after submission, and the Entries API filter
# reads dates in a fixed PST/PDT zone while it returns them in the account's zone, so a
# `DateCreated` watermark could skip rows.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
