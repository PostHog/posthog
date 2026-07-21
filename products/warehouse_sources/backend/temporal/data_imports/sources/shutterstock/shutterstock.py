import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    AuthConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.settings import (
    SHUTTERSTOCK_ENDPOINTS,
)

SHUTTERSTOCK_BASE_URL = "https://api.shutterstock.com"

# Hard cap so a runaway pagination loop (e.g. the API never returning an empty page) can't
# scan forever. Page sizes are 100-500, so this bounds a single endpoint sync.
MAX_PAGES = 100_000


@dataclasses.dataclass
class ShutterstockResumeConfig:
    # Next 1-indexed page to fetch.
    page: int


@dataclasses.dataclass(frozen=True)
class ShutterstockAuth:
    """Either an app consumer key/secret pair (HTTP Basic) or an OAuth access token
    (Bearer). Account-scoped endpoints (collections, licenses, subscriptions) require the
    OAuth token; the catalog feeds work with either."""

    consumer_key: str | None = None
    consumer_secret: str | None = None
    access_token: str | None = None


def _auth_config(auth: ShutterstockAuth) -> AuthConfig:
    # Framework auth so the credential values are redacted from logs/samples.
    if auth.access_token:
        return {"type": "bearer", "token": auth.access_token}
    return {
        "type": "http_basic",
        "username": auth.consumer_key or "",
        "password": auth.consumer_secret or "",
    }


def _format_start_date(value: Any) -> str | None:
    """Format an incremental cursor value as the ISO 8601 `start_date` the API filters on.

    Second precision, UTC offset form (the docs' examples use offset datetimes). Flooring
    to the second re-fetches boundary rows at worst; the merge dedupes them on the
    primary key.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).replace(microsecond=0).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def validate_credentials(auth: ShutterstockAuth) -> bool:
    """Confirm the credentials are genuine by hitting a cheap endpoint every valid
    credential type can reach (image categories accepts both Basic and Bearer auth with
    no scopes)."""
    ok, _status = _probe_endpoint(auth, "/v2/images/categories")
    return ok


def check_endpoint_access(auth: ShutterstockAuth, endpoint: str) -> str | None:
    """Per-endpoint scope probe for the schema picker. Only a real denial (401/403) counts
    as a missing scope — throttles, 5xx, or network blips must not mark a table
    unreachable, so anything else reads as reachable."""
    config = SHUTTERSTOCK_ENDPOINTS[endpoint]
    ok, status = _probe_endpoint(auth, config.path)
    if ok or status not in (401, 403):
        return None
    if config.required_scope:
        return (
            f"This table needs an OAuth access token with the `{config.required_scope}` scope. "
            "Consumer key/secret authentication cannot access account-level data."
        )
    return "Your Shutterstock credentials were rejected for this table."


def _probe_endpoint(auth: ShutterstockAuth, path: str) -> tuple[bool, int | None]:
    redact = tuple(v for v in (auth.consumer_key, auth.consumer_secret, auth.access_token) if v)
    headers = {"Accept": "application/json"}
    request_auth = None
    if auth.access_token:
        headers["Authorization"] = f"Bearer {auth.access_token}"
    else:
        request_auth = HTTPBasicAuth(auth.consumer_key or "", auth.consumer_secret or "")
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=redact),
        f"{SHUTTERSTOCK_BASE_URL}{path}?per_page=1&page=1",
        headers=headers,
        auth=request_auth,
    )


def get_rows(
    auth: ShutterstockAuth,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ShutterstockResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SHUTTERSTOCK_ENDPOINTS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state: Optional[dict[str, Any]] = {"page": resume.page} if resume is not None else None

    params: dict[str, Any] = {}
    if config.page_size is not None:
        params["per_page"] = config.page_size
    if config.cursor_field:
        # Ascending on the cursor field so the pipeline watermark advances safely and
        # full-refresh pages don't skip/duplicate rows inserted mid-sync. The API's sort
        # enum is newest/oldest, not a field name.
        params["sort"] = "oldest"

    use_watermark = (
        config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None
    )
    endpoint_config: Endpoint = {
        "path": config.path,
        # All list responses wrap rows in a `data` array; a missing/empty key reads as an
        # empty page and ends pagination.
        "data_selector": "data",
        "params": params,
        "paginator": PageNumberPaginator(base_page=1, page_param="page", maximum_page=MAX_PAGES)
        if config.page_size is not None
        else SinglePagePaginator(),
    }
    if use_watermark:
        endpoint_config["incremental"] = {
            "start_param": "start_date",
            "cursor_path": str(config.cursor_field),
            "convert": _format_start_date,
        }
    elif config.default_lookback_days is not None:
        # The `updated` feeds default to a 1-hour interval when no `start_date` is passed,
        # so an unwatermarked sync (first incremental run or full refresh) would silently
        # return almost nothing. Bound the window explicitly instead. Whether the API
        # honors arbitrarily old start dates is undocumented, so the window stays modest.
        window_start = datetime.now(UTC) - timedelta(days=config.default_lookback_days)
        params["start_date"] = _format_start_date(window_start)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SHUTTERSTOCK_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": _auth_config(auth),
        },
        "resources": [{"name": endpoint, "endpoint": endpoint_config}],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Called by the framework AFTER a page is yielded, so a crash re-pulls from the
        # next page rather than losing the page we just handed off; the merge dedupes any
        # overlap on the primary key.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(ShutterstockResumeConfig(page=int(state["page"])))

    yield from rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if use_watermark else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def shutterstock_source(
    auth: ShutterstockAuth,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ShutterstockResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SHUTTERSTOCK_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            auth=auth,
            endpoint=endpoint,
            team_id=team_id,
            job_id=job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
