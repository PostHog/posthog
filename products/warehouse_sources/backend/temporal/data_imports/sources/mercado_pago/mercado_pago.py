import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from dateutil import parser as dateutil_parser
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    BearerTokenAuth,
    auth_secret_values,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.jsonpath_utils import (
    find_values,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.settings import (
    MERCADO_PAGO_BASE_URL,
    MERCADO_PAGO_ENDPOINTS,
    PAGE_SIZE,
    MercadoPagoEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60

MISSING_ACCESS_TOKEN_ERROR = "Missing Mercado Pago access token"

# Mercado Pago's relative anchor for "right now". `range` needs both bounds, so an incremental
# window always sends an end as well as a begin.
NOW_ANCHOR = "NOW"


@dataclasses.dataclass
class MercadoPagoResumeConfig:
    # Offset of the next page to fetch on the search endpoint being synced.
    offset: int


def build_auth(access_token: Optional[str]) -> BearerTokenAuth:
    if not access_token:
        raise ValueError(MISSING_ACCESS_TOKEN_ERROR)
    return BearerTokenAuth(token=access_token)


def format_search_datetime(value: Any) -> str:
    """Format an incremental watermark as the ISO-8601 instant the search endpoints expect."""
    if isinstance(value, datetime):
        instant = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    elif isinstance(value, date):
        instant = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        try:
            parsed = dateutil_parser.parse(str(value))
        except (ValueError, OverflowError):
            return str(value)
        instant = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    return instant.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def resolve_cursor_field(endpoint_config: MercadoPagoEndpointConfig, incremental_field: Optional[str]) -> Optional[str]:
    """The date field the server-side window filters on, or None for a full-refresh endpoint.

    Honors the cursor the user picked in the schema settings, falling back to the first advertised
    field when their choice isn't one this endpoint can filter on.
    """
    if not endpoint_config.supports_date_range or not endpoint_config.incremental_fields:
        return None

    advertised = [f["field"] for f in endpoint_config.incremental_fields]
    if incremental_field in advertised:
        return incremental_field
    return advertised[0]


def build_request_params(
    endpoint_config: MercadoPagoEndpointConfig,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Optional[Any],
) -> dict[str, Any]:
    params: dict[str, Any] = dict(endpoint_config.extra_params)

    cursor_field = resolve_cursor_field(endpoint_config, incremental_field) if should_use_incremental_field else None
    sort_field = cursor_field or endpoint_config.default_sort_field
    if sort_field:
        # Ascending so the pipeline's watermark advances in step with the pages we yield, and so
        # page boundaries don't shift as new rows are created mid-sync.
        params["sort"] = sort_field
        params["criteria"] = "asc"

    if cursor_field and db_incremental_field_last_value is not None:
        params["range"] = cursor_field
        params["begin_date"] = format_search_datetime(db_incremental_field_last_value)
        params["end_date"] = NOW_ANCHOR

    return params


def _find_int(body: Any, path: Optional[str]) -> Optional[int]:
    if not path or not isinstance(body, dict):
        return None
    try:
        values = find_values(path, body)
    except Exception:
        return None
    if not values:
        return None
    value = values[0]
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class MercadoPagoSearchPaginator(BasePaginator):
    """Offset paginator driven by the search response's own paging block.

    Mercado Pago caps `limit` server-side, so a page can be shorter than the one we asked for
    without meaning "last page". Advancing by the rows actually returned (from the offset the
    server reports, when it reports one) keeps the walk correct under that cap, and the declared
    total is what terminates it.
    """

    def __init__(
        self,
        limit: int,
        total_path: Optional[str] = None,
        offset_path: Optional[str] = None,
        offset: int = 0,
    ) -> None:
        super().__init__()
        self.limit = limit
        self.total_path = total_path
        self.offset_path = offset_path
        self.offset = offset

    def _apply(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["offset"] = self.offset
        request.params["limit"] = self.limit

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return

        try:
            body = response.json()
        except ValueError:
            body = None

        served_offset = _find_int(body, self.offset_path)
        self.offset = (served_offset if served_offset is not None else self.offset) + len(data)

        total = _find_int(body, self.total_path)
        if total is not None and self.offset >= total:
            self._has_next_page = False
            return

        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"offset": self.offset} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"MercadoPagoSearchPaginator(offset={self.offset}, limit={self.limit})"


def mercado_pago_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MercadoPagoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    endpoint_config = MERCADO_PAGO_ENDPOINTS[endpoint]
    auth = build_auth(access_token)

    params = build_request_params(
        endpoint_config,
        should_use_incremental_field,
        incremental_field,
        db_incremental_field_last_value,
    )

    paginator = MercadoPagoSearchPaginator(
        limit=PAGE_SIZE,
        total_path=endpoint_config.total_path,
        offset_path=endpoint_config.offset_path,
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state = {"offset": resume_config.offset} if resume_config is not None else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Called after each page is yielded, so a crash re-yields the last page (merge dedupes on
        # the primary key) rather than skipping it. No state means the walk is finished.
        if not state:
            return
        resumable_source_manager.save_state(MercadoPagoResumeConfig(offset=int(state["offset"])))

    endpoint_dict: Endpoint = {
        "path": endpoint_config.path,
        "data_selector": endpoint_config.data_selector,
        # A 200 whose body isn't the expected list shape is a transient glitch worth retrying,
        # rather than a reason to silently sync 0 rows.
        "data_selector_malformed_retryable": True,
        "paginator": paginator,
        "params": params,
    }

    resource: EndpointResource = {
        "name": endpoint,
        "endpoint": endpoint_dict,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field and endpoint_config.incremental_fields
        else "replace",
        "table_format": "delta",
    }

    config: RESTAPIConfig = {
        "client": {
            "base_url": MERCADO_PAGO_BASE_URL,
            "auth": auth,
            "headers": {"Accept": "application/json"},
            # Pin every request — including pagination — to the API host and refuse redirects, so a
            # bearer token can't be bounced off-host.
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
        },
        "resource_defaults": {},
        "resources": [resource],
    }

    def items() -> Iterator[list[dict[str, Any]]]:
        api_resource = rest_api_resource(
            config,
            team_id,
            job_id,
            # The date window is built into the endpoint params above rather than the framework's
            # declarative incremental binding, because Mercado Pago needs a matching `range` and
            # `end_date` alongside the begin bound.
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        for batch in api_resource:
            if batch:
                yield batch

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=endpoint_config.primary_keys,
        sort_mode="asc",
        partition_count=1 if endpoint_config.partition_key else None,
        partition_size=1 if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def _error_message(response: requests.Response) -> Optional[str]:
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    for key in ("message", "error"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def validate_credentials(
    access_token: Optional[str],
    schema_name: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Probe the payments search endpoint to confirm the access token is genuine.

    A 403 means the token works but isn't authorized for this resource, which is accepted at
    source-create (`schema_name is None`) — a marketplace or restricted token may legitimately
    only cover the tables the user wants — and rejected when validating a specific schema.
    """
    try:
        auth = build_auth(access_token)
    except ValueError as e:
        return False, str(e)

    session = make_tracked_session(
        headers={"Accept": "application/json"},
        redact_values=auth_secret_values(auth),
    )

    try:
        response = session.get(
            f"{MERCADO_PAGO_BASE_URL}/v1/payments/search",
            params={"limit": 1},
            auth=auth,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as e:
        return False, f"Could not connect to Mercado Pago: {e}"

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, _error_message(response) or "Your Mercado Pago credentials are invalid or expired"

    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, _error_message(response) or (
            f"Your Mercado Pago credentials are not authorized to read '{schema_name}'"
        )

    return False, _error_message(response) or f"Mercado Pago returned HTTP {response.status_code}"
