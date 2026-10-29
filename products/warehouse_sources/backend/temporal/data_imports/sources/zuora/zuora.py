import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2Auth,
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.jsonpath_utils import (
    find_values,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    PaginatorConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.settings import (
    PAGE_SIZE,
    ZUORA_COMMERCE_ENDPOINTS,
    ZUORA_ENDPOINTS,
    ZUORA_ENVIRONMENT_HOSTS,
)

ZUORA_INCOMPLETE_LIST_ERROR = "Zuora returned a full page for a list that has no next-page token"


@dataclasses.dataclass
class ZuoraResumeConfig:
    # The nextPage cursor of the next unfetched Object Query page.
    cursor: str


def _base_url(environment: str) -> str:
    host = ZUORA_ENVIRONMENT_HOSTS.get(environment)
    if host is None:
        raise ValueError(f"Invalid Zuora environment: {environment}")
    return host


def _token_url(environment: str) -> str:
    return f"{_base_url(environment)}/oauth/token"


def _make_auth(environment: str, client_id: str, client_secret: str) -> OAuth2Auth:
    """Zuora uses OAuth2 client-credentials with the client id/secret in the token request body.

    Tokens last ~1h; the framework mints one lazily, caches it for the run, and re-mints on
    expiry — replacing the pre-framework mint-once-then-reactive-401-remint handling."""
    return OAuth2Auth(
        token_url=_token_url(environment),
        client_id=client_id,
        client_secret=client_secret,
        grant_type="client_credentials",
        client_auth_method="body",
    )


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor for the updateddate.GT filter (ISO 8601 UTC)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


class ZuoraCursorPaginator(BasePaginator):
    """Follow Zuora Object Query's body-level ``nextPage`` cursor.

    The cursor encodes the full query context (pageSize/sort/filter), so each follow-up page is
    requested with ONLY ``cursor`` — repeating the original params risks a 400. Pagination stops
    when a page carries no ``nextPage``. Resume seeds the pending cursor so a restarted run
    continues from the saved page, again sending the cursor alone."""

    def __init__(self) -> None:
        super().__init__()
        self._cursor_value: Optional[str] = None

    def _apply_cursor(self, request: Request) -> None:
        # Send the cursor alone; drop the base pageSize/sort/filter params.
        request.params = {"cursor": self._cursor_value}

    def init_request(self, request: Request) -> None:
        # On resume the first request targets the saved page with just the cursor.
        if self._cursor_value is not None:
            self._apply_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            values = find_values("nextPage", response.json())
        except Exception:
            values = []
        if values and values[0]:
            self._cursor_value = values[0]
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._cursor_value is not None:
            self._apply_cursor(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor_value} if self._has_next_page and self._cursor_value is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor_value = cursor
            self._has_next_page = True

    def __str__(self) -> str:
        return "ZuoraCursorPaginator()"


class ZuoraFullPageGuardPaginator(SinglePagePaginator):
    """Fetch a one-response list, and fail when the response fills the requested page.

    A full page can hide more rows that the API gives no way to fetch. The check runs before the
    page is yielded, so a truncated full refresh never replaces the table."""

    def __init__(self, page_size: int) -> None:
        super().__init__()
        self.page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is not None and len(data) >= self.page_size:
            raise ValueError(f"{ZUORA_INCOMPLETE_LIST_ERROR} ({len(data)} rows), so the table could be incomplete.")
        super().update_state(response, data)

    def __str__(self) -> str:
        return f"ZuoraFullPageGuardPaginator(page_size={self.page_size})"


def _object_query_endpoint(
    endpoint: str, should_use_incremental_field: bool, db_incremental_field_last_value: Optional[Any]
) -> Endpoint:
    # Filters use lowercase field names (updateddate); rows come back camelCase (updatedDate).
    # Ascending sort lets the pipeline commit the watermark progressively as pages complete.
    params: dict[str, Any] = {"pageSize": PAGE_SIZE, "sort[]": "updateddate.ASC"}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        params["filter[]"] = f"updateddate.GT:{_format_timestamp(db_incremental_field_last_value)}"

    return {
        "path": f"object-query/{ZUORA_ENDPOINTS[endpoint]}",
        "params": params,
        "data_selector": "data",
        "paginator": ZuoraCursorPaginator(),
    }


def _commerce_endpoint(endpoint: str) -> Endpoint:
    commerce = ZUORA_COMMERCE_ENDPOINTS[endpoint]
    params: dict[str, Any] = {}
    paginator: PaginatorConfig = "single_page"
    if commerce.paginated:
        paginator = JSONResponseCursorPaginator(
            cursor_path="nextPageToken", cursor_param="pageToken", raise_on_repeated_cursor=True
        )
    elif commerce.page_size_param is not None:
        params[commerce.page_size_param] = PAGE_SIZE
        paginator = ZuoraFullPageGuardPaginator(PAGE_SIZE)
    return {
        "path": commerce.path,
        "params": params,
        "data_selector": commerce.data_selector,
        "paginator": paginator,
    }


def validate_credentials(environment: str, client_id: str, client_secret: str) -> bool:
    """Confirm the OAuth client credentials are valid by minting a token."""
    auth = _make_auth(environment, client_id, client_secret)
    # Force the lazy token mint through the public auth callable; a bad credential raises here.
    probe = Request(method="GET", url=_base_url(environment)).prepare()
    try:
        auth(probe)
    except OAuth2AuthRequestError:
        # A rejected token exchange (permanent 4xx or transient 5xx/429) means we could not
        # mint. Let other failures (network/DNS/timeout) propagate so they aren't misreported
        # to the user as invalid credentials.
        return False
    return True


def zuora_source(
    environment: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZuoraResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    auth = _make_auth(environment, client_id, client_secret)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.cursor:
        initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework calls the hook AFTER a page is yielded and only while a next page remains,
        # so a crash re-yields the in-flight page (merge dedupes on primary key) rather than skipping it.
        if state is not None and state.get("cursor") is not None:
            resumable_source_manager.save_state(ZuoraResumeConfig(cursor=state["cursor"]))

    endpoint_config = (
        _commerce_endpoint(endpoint)
        if endpoint in ZUORA_COMMERCE_ENDPOINTS
        else _object_query_endpoint(endpoint, should_use_incremental_field, db_incremental_field_last_value)
    )
    client_config: ClientConfig = {
        "base_url": _base_url(environment),
        "auth": auth,
        # Pin every request — including seeded resume requests — to the configured Zuora host so a
        # tampered resume state can't exfiltrate the bearer token off-host.
        "allowed_hosts": [],
    }
    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [{"name": endpoint, "endpoint": endpoint_config}],
    }
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        # Object Query pages are requested sorted ascending by updateddate; Commerce lists are full refresh only.
        sort_mode="asc",
    )
