"""Veeqo API client used by the data warehouse source.

Spec: https://developers.veeqo.com/api

Veeqo is a multichannel ecommerce inventory, order and shipping management
platform. The API is pure REST/JSON with API-key auth (`x-api-key` header),
page-number pagination (`page` / `page_size`, with `X-Total-Pages-Count` /
`X-Total-Count` response headers), and server-side filters (`updated_at_min` /
`created_at_min` / `since_id`) on orders and products for incremental syncs.

Built on the shared ``rest_source`` framework: the framework ``api_key`` auth
carries the token in the ``x-api-key`` header and redacts it from logs and
error messages, and a small paginator extends the framework page-number
paginator with Veeqo's total-pages header and a short-page stop.

Veeqo has no list endpoints for returns, stock entries, shipments or bundles.
Returns and stock entries are exploded from the order and product records that
embed them; shipment tracking events and bundle contents fan out from those
records to one request per shipment or bundle.

NOTE: these endpoint params were taken from the public API docs and could not
be curl-verified against a live account during implementation (Veeqo API keys
must be enabled by their support team). The pagination/filter handling is
intentionally conservative — see inline comments where behavior is assumed
rather than confirmed.
"""

import dataclasses
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.settings import (
    VEEQO_ENDPOINTS,
    VeeqoEndpointConfig,
)

VEEQO_BASE_URL = "https://api.veeqo.com"

# User-chosen incremental field -> the documented server-side filter param it maps to.
INCREMENTAL_PARAM_BY_FIELD = {
    "updated_at": "updated_at_min",
    "created_at": "created_at_min",
    "id": "since_id",
}


@dataclasses.dataclass  # nosemgrep: prefer-frozen-dataclasses -- pre-existing; new field shifts the backlog finding into diff
class VeeqoResumeConfig:
    """Page cursor for resumable list iteration.

    ``page`` is the next page to fetch. ``endpoint`` scopes the state to a single
    endpoint so we never replay an orders page number against products.
    Fan-out tables store the ``build_dependent_resource`` checkpoint in
    ``fanout_state`` instead.
    """

    endpoint: str
    page: Optional[int] = None
    fanout_state: Optional[dict[str, Any]] = None


class VeeqoPaginator(PageNumberPaginator):
    """Page-number pagination for Veeqo list endpoints (1-based ``page`` param).

    Extends the framework paginator with two extra stop conditions:

    - the ``X-Total-Pages-Count`` response header, so the terminal page doesn't
      cost one extra empty-page request;
    - a short (partial) page, which is always the last page for offset-backed
      page-number pagination.

    Endpoints that document no pagination params at all (``/tags``) must not use
    this paginator — they're configured ``single_page`` instead, because an API
    that ignores ``page`` and returns ``page_size``-or-more rows would loop on
    the same full list forever.
    """

    def __init__(self, page_size: int) -> None:
        super().__init__(base_page=1, page_param="page", stop_after_empty_page=True)
        self.page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page:
            return

        # After super().update_state, self.page points at the NEXT page to fetch.
        total_pages_header = response.headers.get("X-Total-Pages-Count")
        if total_pages_header is not None:
            try:
                if self.page > int(total_pages_header):
                    self._has_next_page = False
                    return
            except (TypeError, ValueError):
                pass

        if data is not None and len(data) < self.page_size:
            self._has_next_page = False

    def __str__(self) -> str:
        return f"VeeqoPaginator(page={self.page}, page_size={self.page_size})"


def _format_incremental_value(incremental_field: str, value: Any) -> Any:
    """Format an incremental cursor value for Veeqo's server-side filters.

    ``updated_at_min`` / ``created_at_min`` expect ``YYYY-MM-DD HH:MM:SS``; the
    docs don't state a timezone, so we normalize to UTC (Veeqo returns UTC
    timestamps) to keep behavior deterministic. ``since_id`` expects an integer.
    """
    if incremental_field == "id":
        return int(value)
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d 00:00:00")
    return str(value)


def _build_initial_params(
    config: VeeqoEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Query params for the first page (the paginator only advances ``page``)."""
    # Single-page endpoints document no pagination params, so none are sent.
    params: dict[str, Any] = {} if config.single_page else {"page_size": config.page_size}
    params.update(config.extra_params)

    use_incremental = (
        config.supports_incremental
        and should_use_incremental_field
        and incremental_field in INCREMENTAL_PARAM_BY_FIELD
        and db_incremental_field_last_value is not None
    )

    if use_incremental and incremental_field is not None:
        params[INCREMENTAL_PARAM_BY_FIELD[incremental_field]] = _format_incremental_value(
            incremental_field, db_incremental_field_last_value
        )

    return params


def _order_returns(order: dict[str, Any]) -> list[dict[str, Any]]:
    return [{**item, "order_id": order.get("id")} for item in order.get("returns") or [] if isinstance(item, dict)]


def _product_stock_entries(product: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {**entry, "product_id": product.get("id")}
        for sellable in product.get("sellables") or []
        if isinstance(sellable, dict)
        for entry in sellable.get("stock_entries") or []
        if isinstance(entry, dict)
    ]


def _order_shipments(order: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for allocation in order.get("allocations") or []:
        shipment = allocation.get("shipment") if isinstance(allocation, dict) else None
        shipment_id = shipment.get("id") if isinstance(shipment, dict) else None
        # Allocations of one order can share a shipment; request its events once.
        if shipment_id is not None and shipment_id not in seen:
            seen.add(shipment_id)
            rows.append({"shipment_id": shipment_id, "order_id": order.get("id")})
    return rows


def _product_kits(product: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"kit_id": sellable["id"], "product_id": product.get("id")}
        for sellable in product.get("sellables") or []
        if isinstance(sellable, dict) and sellable.get("type") == "Kit" and sellable.get("id") is not None
    ]


# Explodes each record of a `nested` table's path into the table's rows.
_NESTED_ROW_MAPS: dict[str, Callable[[dict[str, Any]], list[dict[str, Any]]]] = {
    "returns": _order_returns,
    "stock_entries": _product_stock_entries,
}

# Derives the ids a fan-out child requests from each parent record.
_FANOUT_PARENT_MAPS: dict[str, Callable[[dict[str, Any]], list[dict[str, Any]]]] = {
    "shipment_tracking_events": _order_shipments,
    "bundle_contents": _product_kits,
}

# `/kits/{id}` returns one bundle object; its rows are the `contents` array.
_FANOUT_CHILD_DATA_SELECTORS: dict[str, str] = {
    "bundle_contents": "contents",
}


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe ``/warehouses`` — a cheap list call every account can serve.

    Veeqo API keys carry full account access (no scopes), so one probe confirms
    the key. A 401 means the key is invalid or not yet enabled by Veeqo support.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{VEEQO_BASE_URL}/warehouses?page_size=1&page=1",
        headers={"x-api-key": api_key, "Accept": "application/json"},
        allow_redirects=False,
    )
    if ok:
        return True, None
    if status == 401:
        return False, (
            "Invalid Veeqo API key. Check the key in your Veeqo account settings — "
            "Veeqo support must enable API access before a key appears there."
        )
    if status is None:
        return False, "Could not reach Veeqo. Please check your connection and try again."
    return False, f"Veeqo rejected the request (HTTP {status})."


def _source_response(
    endpoint: str,
    config: VeeqoEndpointConfig,
    items: Callable[[], Iterable[Any]],
    column_hints: Optional[dict[str, Any]],
) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Veeqo documents no sort param and no ordering guarantee for list
        # endpoints, so declare "desc": the incremental watermark then commits
        # only after a successful sync instead of checkpointing per batch, which
        # is safe whatever order rows actually arrive in.
        sort_mode="desc",
        column_hints=column_hints,
    )


def veeqo_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[VeeqoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = VEEQO_ENDPOINTS[endpoint]

    client_config: ClientConfig = {
        "base_url": VEEQO_BASE_URL,
        "headers": {"Accept": "application/json"},
        # api_key auth injects the key into the `x-api-key` header and redacts
        # it from logs and raised error messages.
        "auth": {
            "type": "api_key",
            "api_key": api_key,
            "name": "x-api-key",
            "location": "header",
        },
        # requests preserves the custom x-api-key header when following a
        # redirect, so a redirect response could replay the full-account key
        # to another host — refuse redirects outright.
        "allow_redirects": False,
    }

    resume: Optional[VeeqoResumeConfig] = None
    if resumable_source_manager.can_resume():
        loaded = resumable_source_manager.load_state()
        # Only replay state saved for THIS endpoint.
        if loaded is not None and loaded.endpoint == endpoint:
            resume = loaded

    if config.fanout is not None:
        parent_config = VEEQO_ENDPOINTS[config.fanout.parent_name]

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(VeeqoResumeConfig(endpoint=endpoint, fanout_state=state))

        child_endpoint_extra: Endpoint = {"paginator": SinglePagePaginator()}
        if endpoint in _FANOUT_CHILD_DATA_SELECTORS:
            child_endpoint_extra["data_selector"] = _FANOUT_CHILD_DATA_SELECTORS[endpoint]

        child = build_dependent_resource(
            endpoint_configs=VEEQO_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra={
                "data_selector_required": True,
                "paginator": VeeqoPaginator(page_size=parent_config.page_size),
            },
            child_endpoint_extra=child_endpoint_extra,
            parent_data_map=_FANOUT_PARENT_MAPS[endpoint],
            # The parent page size travels in `fanout.parent_params`; the child
            # endpoints are single-object responses that take no page size.
            page_size_param=None,
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume.fanout_state if resume else None,
        )
        return _source_response(endpoint, config, lambda: child, column_hints=None)

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Veeqo list responses are bare JSON arrays (no wrapper key) —
                    # fail loud if the response shape ever changes.
                    "data_selector_required": True,
                    "paginator": SinglePagePaginator()
                    if config.single_page
                    else VeeqoPaginator(page_size=config.page_size),
                },
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.page:
        initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the hook fires AFTER a page is
        # yielded so a crash re-yields the last page (merge dedupes) rather than
        # skipping it.
        if state and state.get("page"):
            resumable_source_manager.save_state(VeeqoResumeConfig(endpoint=endpoint, page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    if config.nested:
        resource.add_map(_NESTED_ROW_MAPS[endpoint])

    return _source_response(endpoint, config, lambda: resource, column_hints=resource.column_hints)
