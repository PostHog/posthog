import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    APIKeyAuth,
    HttpBasicAuth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.settings import (
    SHIPSTATION_V1,
    SHIPSTATION_V2,
    ShipStationEndpointConfig,
    endpoints_for_version,
)

# ShipStation list pages cap at 500 items on both versions.
PAGE_SIZE = 500

# All ShipStation v1 DateTime values are US Pacific time, not UTC.
SHIPSTATION_TZ = ZoneInfo("America/Los_Angeles")


@dataclasses.dataclass(frozen=True)
class ShipStationDialect:
    """Per-version transport differences between the two live ShipStation APIs.

    The endpoint catalog is version-specific (see `settings`), but the request layer only differs
    in these axes: the host, auth scheme, query-param spellings (page size + sort), the date-filter
    format, and the credential probe path."""

    base_url: str
    # Page-size param name (v1 camelCase `pageSize`, v2 snake_case `page_size`).
    page_size_param: str
    # Sort param names + ascending value (v1 `sortBy`/`sortDir`/`ASC`, v2 `sort_by`/`sort_dir`/`asc`).
    sort_by_param: str
    sort_dir_param: str
    sort_dir_asc: str
    # v1 stores/filters DateTime in US Pacific; v2 (ShipEngine) uses ISO 8601 UTC.
    uses_pacific_time: bool
    # v1 authenticates with HTTP Basic (key + secret); v2 with a single API-Key header.
    uses_api_key_header: bool
    # Cheap, always-present list endpoint used as a credential/permission probe.
    credentials_probe_path: str


SHIPSTATION_DIALECTS: dict[str, ShipStationDialect] = {
    SHIPSTATION_V1: ShipStationDialect(
        base_url="https://ssapi.shipstation.com",
        page_size_param="pageSize",
        sort_by_param="sortBy",
        sort_dir_param="sortDir",
        sort_dir_asc="ASC",
        uses_pacific_time=True,
        uses_api_key_header=False,
        credentials_probe_path="/stores",
    ),
    SHIPSTATION_V2: ShipStationDialect(
        base_url="https://api.shipstation.com/v2",
        page_size_param="page_size",
        sort_by_param="sort_by",
        sort_dir_param="sort_dir",
        sort_dir_asc="asc",
        uses_pacific_time=False,
        uses_api_key_header=True,
        credentials_probe_path="/carriers",
    ),
}


def _dialect(api_version: str) -> ShipStationDialect:
    # Both supported labels are keyed explicitly. An undeclared pin is honored verbatim upstream
    # (`resolve_api_version`); fall back to the original v1 transport rather than guessing a newer
    # host/auth scheme for it.
    return SHIPSTATION_DIALECTS.get(api_version, SHIPSTATION_DIALECTS[SHIPSTATION_V1])


def _build_auth(api_key: str, api_secret: str | None, dialect: ShipStationDialect) -> APIKeyAuth | HttpBasicAuth:
    if dialect.uses_api_key_header:
        return APIKeyAuth(api_key=api_key, name="API-Key", location="header")
    return HttpBasicAuth(api_key, api_secret)


@dataclasses.dataclass
class ShipStationResumeConfig:
    # ShipStation paginates with a 1-based page number; the framework's PageNumberPaginator resume
    # state is a single ``{"page": <next page>}`` dict, so it maps straight onto this existing field.
    page: int


class ShipStationPageNumberPaginator(PageNumberPaginator):
    """1-based page pagination over ShipStation's ``{<data_key>, page, pages}`` envelopes.

    Stops after the last page when the body carries a ``pages`` total, and falls back to short-page
    termination when it doesn't — matching the hand-rolled loop this replaces. Empty intermediate
    pages don't stop pagination (``stop_after_empty_page=False``); the ``pages`` total governs
    termination whenever it's present.
    """

    def __init__(self, page_size: int) -> None:
        super().__init__(base_page=1, page_param="page", total_path="pages", stop_after_empty_page=False)
        self._page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page:
            return
        # Fall back to short-page termination only when the body lacks a ``pages`` total.
        try:
            body = response.json()
        except Exception:
            body = None
        has_pages_total = isinstance(body, dict) and body.get("pages") is not None
        if not has_pages_total and data is not None and len(data) < self._page_size:
            self._has_next_page = False


def _format_date_filter(value: Any, dialect: ShipStationDialect = SHIPSTATION_DIALECTS[SHIPSTATION_V1]) -> str:
    """Format an incremental cursor for ShipStation's date filters.

    v1 both stores and filters in US Pacific time ('yyyy-mm-dd hh:mm:ss'); naive values are
    assumed to already be Pacific (they come from API rows) and aware values are converted. v2
    (ShipEngine) filters in ISO 8601 UTC ('2024-01-02T03:04:05Z')."""
    if not dialect.uses_pacific_time:
        return _format_utc_date_filter(value)
    if isinstance(value, datetime):
        dt = value if value.tzinfo is None else value.astimezone(SHIPSTATION_TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d 00:00:00")
    # Row values look like '2024-01-02T03:04:05.0000000'; the filter accepts the
    # space-separated form, so normalize the separator and drop fractions.
    text = str(value).replace("T", " ")
    return text.split(".")[0]


def _format_utc_date_filter(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    # v2 row values are already ISO 8601 UTC; pass them through unchanged.
    return str(value)


def _build_params(
    config: ShipStationEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
    dialect: ShipStationDialect = SHIPSTATION_DIALECTS[SHIPSTATION_V1],
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    if config.paginated:
        params[dialect.page_size_param] = PAGE_SIZE

    if not config.incremental_params:
        return params

    cursor_field = incremental_field or config.incremental_fields[0]["field"]

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        filter_param = config.incremental_params.get(cursor_field)
        if filter_param is not None:
            params[filter_param] = _format_date_filter(db_incremental_field_last_value, dialect)

    # Ascending sort on the cursor field (when the endpoint documents one) keeps
    # page boundaries stable and advances the incremental watermark monotonically.
    sort_by = config.sort_by.get(cursor_field)
    if sort_by is not None:
        params[dialect.sort_by_param] = sort_by
        params[dialect.sort_dir_param] = dialect.sort_dir_asc

    return params


def validate_credentials(
    api_key: str, api_secret: str | None, api_version: str = SHIPSTATION_V1
) -> tuple[bool, str | None]:
    """Confirm the credentials are valid with a cheap list probe on the version's host.

    v1 needs an API key + secret (HTTP Basic); v2 needs only the single API-Key value, so the
    required pair depends on the resolved version rather than the form."""
    dialect = _dialect(api_version)
    if not api_key:
        return False, "A ShipStation API key is required."
    if not dialect.uses_api_key_header and not api_secret:
        return False, "ShipStation API v1 requires both an API key and an API secret."

    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=tuple(v for v in (api_key, api_secret) if v)),
        f"{dialect.base_url}{dialect.credentials_probe_path}",
        auth=_build_auth(api_key, api_secret, dialect),
        # v2 sends its key in a custom API-Key header, which requests would replay across a
        # cross-host redirect; refuse redirects so the probe can't leak it.
        allow_redirects=not dialect.uses_api_key_header,
    )
    if ok:
        return True, None
    return False, "Invalid ShipStation API credentials"


def shipstation_source(
    api_key: str,
    api_secret: str | None,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ShipStationResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
    api_version: str = SHIPSTATION_V1,
) -> SourceResponse:
    dialect = _dialect(api_version)
    config = endpoints_for_version(api_version)[endpoint]

    paginator = ShipStationPageNumberPaginator(PAGE_SIZE) if config.paginated else SinglePagePaginator()
    params = _build_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field, dialect
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": dialect.base_url,
            "headers": {"Accept": "application/json"},
            # Auth via the framework so the secret is redacted from logs.
            "auth": _build_auth(api_key, api_secret, dialect),
            # The v2 API-Key header would survive a cross-host redirect (requests only strips
            # Authorization), so pin v2 requests to the base host and refuse redirects. v1's Basic
            # auth is stripped by requests across hosts, so its behavior is left unchanged.
            "allowed_hosts": [] if dialect.uses_api_key_header else None,
            "allow_redirects": not dialect.uses_api_key_header,
            "paginator": paginator,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A missing/malformed data key is tolerated (treated as an empty page), matching
                    # the old _extract_items behaviour — so no data_selector_required. None selector
                    # means the whole body is the row list (bare-array endpoints).
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(ShipStationResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
