from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from requests import PreparedRequest, Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.back_market.settings import (
    BACK_MARKET_ENDPOINTS,
    DATA_SELECTOR,
    BackMarketEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

BASE_URL = "https://www.backmarket.com/ws"


@frozen
class BackMarketResumeConfig:
    next_page: int


class BackMarketTokenAuth(AuthConfigBase):
    """Back Market's seller token rides as a literal `Authorization: Basic <token>` header.

    This is not RFC 7617 Basic auth (base64 of `user:pass`) — the token issued in the Back
    Office is sent as-is, so the shared `http_basic` auth type (which always base64-encodes a
    username/password pair) doesn't apply.
    """

    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = f"Basic {self.token}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.token,) if self.token else ()


class BackMarketPaginator(BasePaginator):
    """Page-number pagination gated on the response body's `next` field.

    Back Market's list endpoints accept `?page=N` (1-indexed) and return a `next` value that's
    falsy on the last page. The official api.backmarket.dev portal renders as a JS SPA we
    couldn't fetch to confirm whether `next` is a follow-on URL or a bare boolean, so this only
    trusts its truthiness and always drives the page number itself — that keeps working either
    way, unlike following `next` as a URL would if it turned out to be a boolean.
    """

    def __init__(self, base_page: int = 1) -> None:
        super().__init__()
        self.page = base_page

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            has_next = bool(response.json().get("next"))
        except Exception:
            has_next = False
        if not has_next:
            self._has_next_page = False
            return
        self.page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"BackMarketPaginator(page={self.page})"


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor as the `YYYY-MM-DD HH:MM:SS` timestamp Back Market's
    `date_modification`/`date_creation` filters expect.

    The official docs portal renders as a JS SPA we couldn't fetch, so this format is taken from
    a working third-party integration rather than the vendor's own reference.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": BackMarketTokenAuth(token=api_token),
        "paginator": BackMarketPaginator(),
        # capture=False: `orders` responses carry buyer PII (names, shipping addresses) that the
        # name-based scrubbers can't recognise, so keep raw bodies out of HTTP sample capture even
        # where an operator enables it for this source. Requests stay metered and logged either way.
        "session": make_tracked_session(redact_values=(api_token,), capture=False),
    }


def _build_params(
    config: BackMarketEndpointConfig,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if (
        config.incremental_fields
        and should_use_incremental_field
        and incremental_field
        and db_incremental_field_last_value is not None
    ):
        params[incremental_field] = _format_timestamp(db_incremental_field_last_value)
    return params


def back_market_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BackMarketResumeConfig],
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BACK_MARKET_ENDPOINTS[endpoint]
    params = _build_params(config, should_use_incremental_field, incremental_field, db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if config.incremental_fields and should_use_incremental_field
            else "replace",
        },
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": cast(dict[str, Any], params),
                    "data_selector": DATA_SELECTOR,
                },
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash
        # re-yields the last page (merge dedupes) rather than skipping it.
        if state and state.get("page"):
            resumable_source_manager.save_state(BackMarketResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_token: str) -> tuple[bool, int | None]:
    """Probe Back Market's `/orders` endpoint to confirm the token is genuine.

    `capture=False`: the probe's response body is real order data (buyer/shipping details),
    so keep it out of HTTP sample capture even where an operator enables it — the probe stays
    metered and logged either way.
    """
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,), capture=False),
        f"{BASE_URL}/orders",
        headers={"Authorization": f"Basic {api_token}", "Accept": "application/json"},
    )
