import dataclasses
from datetime import date, datetime
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.sources.justcall.settings import JUSTCALL_ENDPOINTS
from products.warehouse_sources.sources.sdk import (
    Endpoint,
    EndpointResource,
    IncrementalConfig,
    PageNumberPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    rest_api_resource,
    rest_api_resources,
    validate_via_probe,
)

JUSTCALL_BASE_URL = "https://api.justcall.io/v2.1"
# JustCall caps most v2.1 list pages at 100 items; endpoints with a lower cap override it in settings.
PAGE_SIZE = 100
# v2.1 list endpoints are 0-indexed ("page 0 indicates first page").
FIRST_PAGE = 0
CAMPAIGN_PARENT = "sales_dialer_campaigns"
CAMPAIGN_PARENT_KEY = f"_{CAMPAIGN_PARENT}_id"


@dataclasses.dataclass(frozen=False)
class JustCallResumeConfig:
    # Next 0-indexed page to fetch. The cursor filter (`from_datetime`) is recomputed from the
    # unchanged job inputs on resume, so only the page position needs persisting.
    page: int = FIRST_PAGE
    # Framework fan-out snapshot (completed campaigns plus the in-progress child page) for the
    # campaign fan-out endpoints. None for every other endpoint.
    fanout_state: Optional[dict[str, Any]] = None


class JustCallPageNumberPaginator(PageNumberPaginator):
    """0-indexed page pagination over JustCall's ``{"data": [...]}`` list envelopes.

    JustCall's list endpoints report no total count, so — like the hand-rolled loop this replaces —
    a page shorter than the requested size (or an empty page) is the last page. Stopping on a short
    page avoids the extra empty-page request the plain ``PageNumberPaginator`` would pay, and keeps
    the request count identical to the original loop.
    """

    def __init__(self, page_size: int, stop_on_short_page: bool = True) -> None:
        super().__init__(base_page=FIRST_PAGE, page_param="page")
        self._page_size = page_size
        self._stop_on_short_page = stop_on_short_page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._stop_on_short_page and self._has_next_page and data is not None and len(data) < self._page_size:
            self._has_next_page = False


def _get_headers(api_key: str, api_secret: str) -> dict[str, str]:
    # JustCall v2.1 authenticates with the raw `api_key:api_secret` pair in the Authorization
    # header — no `Basic` prefix and no base64 encoding.
    return {
        "Authorization": f"{api_key}:{api_secret}",
        "Accept": "application/json",
    }


def _format_cursor(value: Any) -> Optional[str]:
    """Coerce an incremental cursor value to the `yyyy-mm-dd` form JustCall's `from_datetime` takes.

    The cursor is a `_user_date` field (account-timezone date), persisted as a Date. Datetimes and
    ISO strings are handled defensively; only the date component is kept because `from_datetime`
    accepts a bare date and the watermark is day-granular.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text:
        return None
    # Handles "2021-08-25", "2021-08-25 10:30:00", and "2021-08-25T10:30:00" alike.
    return text[:10]


def _move_campaign_id(row: dict[str, Any]) -> dict[str, Any]:
    # Campaign contact rows do not carry their campaign; the fan-out injects it under the
    # framework's `_<parent>_<field>` key.
    if CAMPAIGN_PARENT_KEY in row:
        row["campaign_id"] = row.pop(CAMPAIGN_PARENT_KEY)
    return row


def _campaign_fanout_resources(
    endpoint: str, child_endpoint: Endpoint, child_paginator: JustCallPageNumberPaginator
) -> list[EndpointResource]:
    campaigns = JUSTCALL_ENDPOINTS[CAMPAIGN_PARENT]
    campaigns_page_size = campaigns.page_size or PAGE_SIZE
    # `campaign_id` is a query param, but the resolve mechanism only substitutes into the path.
    child_endpoint["path"] = f"{child_endpoint['path']}?campaign_id={{campaign_id}}"
    child_endpoint["params"] = {
        **(child_endpoint.get("params") or {}),
        "campaign_id": {"type": "resolve", "resource": CAMPAIGN_PARENT, "field": "id"},
    }
    # The child needs a paginator of its own; it does not use the client-level one.
    child_endpoint["paginator"] = child_paginator
    return [
        {
            "name": CAMPAIGN_PARENT,
            "endpoint": {
                "path": campaigns.path,
                "params": {"per_page": campaigns_page_size, "order": campaigns.order},
                "data_selector": "data",
                "paginator": JustCallPageNumberPaginator(page_size=campaigns_page_size),
            },
        },
        {
            "name": endpoint,
            "endpoint": child_endpoint,
            "include_from_parent": ["id"],
            "data_map": _move_campaign_id,
        },
    ]


def justcall_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[JustCallResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = JUSTCALL_ENDPOINTS[endpoint]

    # `order` is set per endpoint; page/per_page/from_datetime are added by the paginator and the
    # incremental config below. Ascending order keeps already-paged results stable under concurrent
    # inserts and lets the incremental watermark advance monotonically.
    page_size = config.page_size or PAGE_SIZE
    params: dict[str, Any] = {**config.extra_params, "per_page": page_size, "order": config.order}

    incremental: Optional[IncrementalConfig] = None
    if config.incremental_cursor:
        # `sort=datetime` orders by call/SMS time; combined with `order=asc` the watermark advances
        # monotonically. `from_datetime` is only meaningful on the endpoints that support it, and
        # only when a watermark is present (a None value is dropped from the query string).
        params["sort"] = "datetime"
        incremental = {"start_param": "from_datetime", "convert": _format_cursor}

    # Only endpoints with a server-side `from_datetime` filter honor the incremental cursor; the
    # rest are full refresh regardless of what the pipeline passes.
    last_value = (
        db_incremental_field_last_value if (should_use_incremental_field and config.incremental_cursor) else None
    )

    endpoint_def: Endpoint = {
        "path": config.path,
        "params": params,
        "data_selector": "data",
    }
    if incremental is not None:
        endpoint_def["incremental"] = incremental

    resources: list[EndpointResource] = (
        _campaign_fanout_resources(
            endpoint,
            endpoint_def,
            JustCallPageNumberPaginator(page_size=page_size, stop_on_short_page=config.stop_on_short_page),
        )
        if config.campaign_fanout
        else [{"name": endpoint, "endpoint": endpoint_def}]
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": JUSTCALL_BASE_URL,
            # Only the non-secret Accept header goes here; the credential rides on the framework
            # auth config so it's redacted from any raised error message and captured HTTP sample.
            "headers": {"Accept": "application/json"},
            "auth": {
                "type": "api_key",
                "api_key": f"{api_key}:{api_secret}",
                "name": "Authorization",
                "location": "header",
            },
            "paginator": JustCallPageNumberPaginator(page_size=page_size, stop_on_short_page=config.stop_on_short_page),
        },
        "resources": list(resources),
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = resume.fanout_state if config.campaign_fanout else {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from the saved page rather than skipping it — the primary-key merge dedupes the overlap.
        if config.campaign_fanout:
            if state:
                resumable_source_manager.save_state(JustCallResumeConfig(fanout_state=state))
        elif state and state.get("page") is not None:
            resumable_source_manager.save_state(JustCallResumeConfig(page=int(state["page"])))

    if config.campaign_fanout:
        resource = next(
            r
            for r in rest_api_resources(
                rest_config,
                team_id,
                job_id,
                last_value,
                resume_hook=save_checkpoint,
                initial_paginator_state=initial_paginator_state,
            )
            if r.name == endpoint
        )
    else:
        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["campaign_id", config.primary_key] if config.campaign_fanout else [config.primary_key],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.incremental_cursor else None,
        partition_format="week" if config.incremental_cursor else None,
        partition_keys=[config.incremental_cursor] if config.incremental_cursor else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, api_secret: str) -> bool:
    """Confirm the API key/secret pair is valid with one cheap authenticated probe.

    `/phone-numbers` is a tiny account-level list available to any valid JustCall key, so it makes a
    good token check without pulling call/message history.
    """
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key, api_secret, f"{api_key}:{api_secret}")),
        f"{JUSTCALL_BASE_URL}/phone-numbers?page={FIRST_PAGE}&per_page=1",
        headers=_get_headers(api_key, api_secret),
    )
    return ok
