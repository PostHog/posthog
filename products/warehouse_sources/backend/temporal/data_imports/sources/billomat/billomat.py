import dataclasses
from datetime import date, datetime
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# Billomat's documented maximum; requesting the largest page size keeps the per-15-minute
# request budget (300 without a registered app) from being spent on pagination alone.
_PER_PAGE = 1000


@dataclasses.dataclass(frozen=False)
class BillomatResumeConfig:
    next_page: int


def _extract_total_count(response: Response) -> Optional[int]:
    """Read the record `total` Billomat's XML-to-JSON conversion stamps onto the single
    top-level resource wrapper (e.g. `{"clients": {"client": [...], "total": "12"}}`)."""
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict) or len(body) != 1:
        return None
    (wrapper,) = body.values()
    if not isinstance(wrapper, dict):
        return None
    total = wrapper.get("total")
    try:
        return int(total) if total is not None else None
    except (TypeError, ValueError):
        return None


class BillomatPaginator(PageNumberPaginator):
    """Stops once `page * per_page` covers the response body's `total` record count, so a
    full sync doesn't pay for one extra empty-page request past the last page of data."""

    def __init__(self, per_page: int, base_page: int = 1, page: Optional[int] = None, page_param: str = "page") -> None:
        super().__init__(base_page=base_page, page=page, page_param=page_param)
        self._per_page = per_page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        fetched_page = self.page
        super().update_state(response, data)
        if not self._has_next_page:
            return
        total = _extract_total_count(response)
        if total is not None and fetched_page * self._per_page >= total:
            self._has_next_page = False


def _billomat_headers(api_key: str, app_id: Optional[str], app_secret: Optional[str]) -> dict[str, str]:
    headers = {"X-BillomatApiKey": api_key, "Accept": "application/json"}
    if app_id and app_secret:
        headers["X-AppId"] = app_id
        headers["X-AppSecret"] = app_secret
    return headers


def _format_date(value: Any) -> Optional[str]:
    """Billomat's `from`/`to` filters take a bare `YYYY-MM-DD` date, no time component."""
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _incremental_param() -> dict[str, Any]:
    return {
        "type": "incremental",
        "cursor_path": "date",
        "initial_value": None,
        "convert": _format_date,
    }


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    write_disposition = (
        {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace"
    )

    resources: dict[str, EndpointResource] = {
        "Clients": {
            "name": "Clients",
            "table_name": "clients",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": '"clients"."client"',
                "path": "/clients",
                "params": {
                    "per_page": _PER_PAGE,
                    "order_by": "id ASC",
                },
            },
            "table_format": "delta",
        },
        "Suppliers": {
            "name": "Suppliers",
            "table_name": "suppliers",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": '"suppliers"."supplier"',
                "path": "/suppliers",
                "params": {
                    "per_page": _PER_PAGE,
                    "order_by": "id ASC",
                },
            },
            "table_format": "delta",
        },
        "Invoices": {
            "name": "Invoices",
            "table_name": "invoices",
            "write_disposition": write_disposition,
            "endpoint": {
                "data_selector": '"invoices"."invoice"',
                "path": "/invoices",
                "params": {
                    "per_page": _PER_PAGE,
                    "order_by": "date ASC",
                    "from": _incremental_param() if should_use_incremental_field else None,
                },
            },
            "table_format": "delta",
        },
        "Estimates": {
            "name": "Estimates",
            "table_name": "estimates",
            "write_disposition": write_disposition,
            "endpoint": {
                # Billomat's own resource path/element for estimates is "offer" (the public docs
                # page is titled "Estimates" but the API itself never renamed it).
                "data_selector": '"offers"."offer"',
                "path": "/offers",
                "params": {
                    "per_page": _PER_PAGE,
                    "order_by": "date ASC",
                    "from": _incremental_param() if should_use_incremental_field else None,
                },
            },
            "table_format": "delta",
        },
        "CreditNotes": {
            "name": "CreditNotes",
            "table_name": "credit_notes",
            "write_disposition": write_disposition,
            "endpoint": {
                "data_selector": '"credit-notes"."credit-note"',
                "path": "/credit-notes",
                "params": {
                    "per_page": _PER_PAGE,
                    "order_by": "date ASC",
                    "from": _incremental_param() if should_use_incremental_field else None,
                },
            },
            "table_format": "delta",
        },
        "Incomings": {
            "name": "Incomings",
            "table_name": "incomings",
            "write_disposition": write_disposition,
            "endpoint": {
                "data_selector": '"incomings"."incoming"',
                "path": "/incomings",
                "params": {
                    "per_page": _PER_PAGE,
                    "order_by": "date ASC",
                    "from": _incremental_param() if should_use_incremental_field else None,
                },
            },
            "table_format": "delta",
        },
    }
    return resources[name]


def billomat_source(
    api_key: str,
    billomat_id: str,
    app_id: Optional[str],
    app_secret: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BillomatResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> Resource:
    headers = _billomat_headers(api_key, app_id, app_secret)
    # `X-AppSecret` isn't carried by any framework auth object (there is none here — the API
    # key rides as a plain header), so it needs its own redact entry alongside the API key.
    # allow_redirects=False: a redirect would forward the API key/app secret headers off the validated host.
    session = make_tracked_session(
        headers=headers, redact_values=tuple(v for v in (api_key, app_secret) if v), allow_redirects=False
    )

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(BillomatResumeConfig(next_page=int(state["page"])))

    config: RESTAPIConfig = {
        "client": {
            "base_url": f"https://{billomat_id}.billomat.net/api",
            "session": session,
            "paginator": BillomatPaginator(per_page=_PER_PAGE, base_page=1, page=1, page_param="page"),
        },
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(api_key: str, billomat_id: str, app_id: Optional[str], app_secret: Optional[str]) -> bool:
    # allow_redirects=False: a redirect would forward the API key/app secret headers off the validated host.
    session = make_tracked_session(
        headers=_billomat_headers(api_key, app_id, app_secret),
        redact_values=tuple(v for v in (api_key, app_secret) if v),
        allow_redirects=False,
    )
    res = session.get(f"https://{billomat_id}.billomat.net/api/clients?per_page=1")
    return res.status_code == 200
