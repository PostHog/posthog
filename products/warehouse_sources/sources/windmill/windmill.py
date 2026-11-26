import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from functools import partial
from typing import Any, Optional
from urllib.parse import quote, urlparse

import requests
from requests import Request, Response

from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    Endpoint,
    EndpointResource,
    PageNumberPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    _is_host_safe,
    make_parent_key_name,
    make_tracked_session,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.sources.windmill.settings import WINDMILL_ENDPOINTS, WindmillEndpointConfig

MAX_RETRY_ATTEMPTS = 5
PER_PAGE = 100

HOST_NOT_ALLOWED_ERROR = "Windmill instance URL is not allowed"


class WindmillHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass(frozen=False)
class WindmillResumeConfig:
    # 1-based page number to fetch on resume. A saved value points at the next page to fetch after
    # the last durably-committed one; on resume the scan restarts there and merge dedupes any overlap.
    page: Optional[int] = None
    # Detail endpoints fan out over a list endpoint. Their state is the shape the framework
    # checkpoints: which parents finished and where the current one stopped.
    fanout_state: Optional[dict[str, Any]] = None


def normalize_base_url(url: str) -> str:
    """Return the API root (``https://<host>/api``) for a user-supplied Windmill instance URL.

    Forces https (matching the Okta/ServiceNow/Braze connectors that also take a user-supplied
    host), strips any trailing slash, and tolerates the user pasting a URL that already ends in
    ``/api`` so we never build ``/api/api``.

    The authority is rebuilt from the parsed host (and port) alone, dropping any userinfo, query,
    or fragment. This keeps the host we SSRF-check identical to the host requests actually connects
    to — an embedded ``user@`` or trailing ``?``/``#`` can't make the checked authority diverge
    from the effective one.
    """
    stripped = re.sub(r"^https?://", "", url.strip(), flags=re.IGNORECASE)
    parsed = urlparse(f"https://{stripped}")
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = f"{host}:{port}" if port else host
    path = parsed.path.rstrip("/")
    if path.lower().endswith("/api"):
        path = path[: -len("/api")]
    return f"https://{netloc}{path}/api"


def _host_from_url(base_url: str) -> str:
    return (urlparse(normalize_base_url(base_url)).hostname or "").lower()


def _workspace_url(base_url: str, workspace: str, path: str) -> str:
    return f"{normalize_base_url(base_url)}/w/{quote(workspace, safe='')}{path}"


def _workspace_base_url(base_url: str, workspace: str) -> str:
    """Root the REST client at the workspace so endpoint paths resolve to ``{base}/w/{ws}{path}``."""
    return f"{normalize_base_url(base_url)}/w/{quote(workspace, safe='')}"


def _endpoint_base_url(base_url: str, workspace: str, config: WindmillEndpointConfig) -> str:
    return _workspace_base_url(base_url, workspace) if config.workspace_scoped else normalize_base_url(base_url)


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _format_after(value: Any) -> str:
    """Format an incremental cursor value as an RFC 3339 timestamp for Windmill's *_after filters."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


class WindmillPageNumberPaginator(PageNumberPaginator):
    """1-based page/per_page paginator that stops on a short page.

    Windmill list endpoints return bare JSON arrays with no total, so a page shorter than
    ``per_page`` is the last one — stop there instead of paying an extra empty-page request the
    built-in (empty-page-only) stop check would incur. ``stop_on_short_page=False`` keeps only the
    empty-page check, for endpoints that can return a short page before the end.
    """

    def __init__(self, per_page: int, stop_on_short_page: bool = True) -> None:
        super().__init__(base_page=1, page_param="page")
        self._per_page = per_page
        self._stop_on_short_page = stop_on_short_page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._stop_on_short_page and self._has_next_page and data is not None and len(data) < self._per_page:
            self._has_next_page = False


class WindmillCursorPaginator(BasePaginator):
    """Keyset paginator for ``listAssets``, which returns the next keyset as a ``next_cursor`` object.

    The server sends ``next_cursor: null`` on the last page, so no empty-page request is needed.
    """

    def __init__(self) -> None:
        super().__init__()
        self._cursor: Optional[dict[str, Any]] = None

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            cursor = response.json().get("next_cursor")
        except (ValueError, AttributeError):
            cursor = None
        if not isinstance(cursor, dict) or cursor.get("created_at") is None or cursor.get("id") is None:
            self._has_next_page = False
            return
        if cursor == self._cursor:
            raise ValueError("Windmill cursor pagination is not advancing (repeated cursor)")
        self._cursor = cursor
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if self._cursor is not None:
            request.params = {
                **(request.params or {}),
                "cursor_created_at": self._cursor["created_at"],
                "cursor_id": self._cursor["id"],
            }


def _explode_rows(field: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    base = {key: value for key, value in row.items() if key != field}
    return [{**base, **entry} for entry in row.get(field) or [] if isinstance(entry, dict)]


def validate_credentials(
    api_token: str, base_url: str, workspace: str, team_id: int | None = None
) -> tuple[bool, str | None]:
    """Probe ``/w/{workspace}/users/whoami`` to confirm the token can reach the workspace."""
    # The instance URL is fully customer-controlled, so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(_host_from_url(base_url), team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = _workspace_url(base_url, workspace, "/users/whoami")
    # Redact the bearer token wherever the tracked adapter records request samples — the
    # Authorization header uses a scheme the name-based scrubbers don't cover.
    session = make_tracked_session(allow_redirects=False, redact_values=(api_token,))
    try:
        response = session.get(url, headers=_get_headers(api_token), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Windmill API token"
    if response.status_code in (403, 404):
        return False, f"Could not access Windmill workspace '{workspace}' with this token"

    try:
        message = response.json().get("message", response.text)
    except Exception:
        message = response.text
    return False, message


def windmill_source(
    api_token: str,
    base_url: str,
    workspace: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WindmillResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = WINDMILL_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if config.paginated or config.body_cursor:
        params["per_page"] = PER_PAGE
    if config.supports_order_desc:
        # Ascending so rows inserted mid-sync append at the end instead of shifting earlier pages,
        # and so the incremental watermark advances monotonically.
        params["order_desc"] = "false"

    after_value: str | None = None
    if (
        incremental_field in config.incremental_after_params
        and should_use_incremental_field
        and db_incremental_field_last_value
    ):
        after_value = _format_after(db_incremental_field_last_value)
        params[config.incremental_after_params[incremental_field]] = after_value

    # listUsers ignores pagination params and returns every row at once, so a single request avoids
    # re-fetching the same full list forever.
    paginator: BasePaginator
    if config.body_cursor:
        paginator = WindmillCursorPaginator()
    elif config.paginated:
        paginator = WindmillPageNumberPaginator(PER_PAGE, stop_on_short_page=config.stop_on_short_page)
    else:
        paginator = SinglePagePaginator()

    list_endpoint: Endpoint = {"path": config.path, "params": params}
    if config.data_selector:
        list_endpoint["data_selector"] = config.data_selector
    client_config: ClientConfig = {
        "base_url": _endpoint_base_url(base_url, workspace, config),
        # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
        # logs and error messages; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_token},
        "paginator": paginator,
        "max_retries": MAX_RETRY_ATTEMPTS,
        # The instance host is customer-controlled, so never follow a redirect that could carry
        # the bearer token to another origin.
        "allow_redirects": False,
    }

    list_resource: EndpointResource = {"name": endpoint, "endpoint": list_endpoint}
    if config.explode_field:
        list_resource["data_map"] = partial(_explode_rows, config.explode_field)
    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [list_resource],
    }

    # A saved page only indexes into a fixed result set. When an incremental watermark is active it
    # may have advanced since the page was saved (a partial run commits rows and moves the cursor),
    # reshuffling the filtered pages so page N would skip earlier unsynced rows. Restart from page 1
    # in that case; the watermark still bounds the scan and merge dedupes.
    resume: Optional[WindmillResumeConfig] = None
    if config.paginated and not config.body_cursor and after_value is None and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
    initial_paginator_state = {"page": resume.page} if resume is not None and resume.page is not None else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the hook fires after a page is yielded, so the saved
        # page is durably reached only once the consumer has committed everything before it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(WindmillResumeConfig(page=int(state["page"])))

    def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(WindmillResumeConfig(fanout_state=state))

    if config.detail_path is not None:
        resources = rest_api_resources(
            _detail_rest_config(endpoint, config, client_config, list_endpoint),
            team_id,
            job_id,
            None,
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume.fanout_state if resume is not None else None,
        )
        resource = next(r for r in resources if r.name == endpoint)
    else:
        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

    def items() -> Iterator[list[dict[str, Any]]]:
        # Re-check at run time (not just at source-create) in case the URL was edited or now
        # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        host_ok, host_err = _is_host_safe(_host_from_url(base_url), team_id)
        if not host_ok:
            raise WindmillHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)
        yield from resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        # We always request ascending order where the API allows it, so incremental watermarks
        # advance safely batch by batch.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format=config.partition_format if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


_PATH_SEGMENT_FIELD = "_path_segment"


def _add_path_segment(key: str, row: dict[str, Any]) -> dict[str, Any]:
    # Runnable paths (``u/<user>/<name>``) are matched by a wildcard route, so their slashes stay.
    return {**row, _PATH_SEGMENT_FIELD: quote(str(row[key]), safe="/" if key == "path" else "")}


def _rename_parent_key(parent_field: str, column: str, row: dict[str, Any]) -> dict[str, Any]:
    renamed = {key: value for key, value in row.items() if key != parent_field}
    renamed[column] = row.get(parent_field)
    return renamed


def _detail_rest_config(
    endpoint: str, config: WindmillEndpointConfig, client_config: ClientConfig, list_endpoint: Endpoint
) -> RESTAPIConfig:
    """Walk the list endpoint, then fetch each row's detail, which carries fields the list omits."""
    assert config.detail_path is not None
    parent_name = f"{endpoint}_list"
    detail_resource: EndpointResource = {
        "name": endpoint,
        "endpoint": {
            "path": config.detail_path,
            "params": {config.detail_key: {"type": "resolve", "resource": parent_name, "field": _PATH_SEGMENT_FIELD}},
            "paginator": SinglePagePaginator(),
            # A row deleted between the list call and its detail call is gone, not an error.
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
    }
    if config.parent_key_column:
        detail_resource["include_from_parent"] = [config.detail_key]
        detail_resource["data_map"] = partial(
            _rename_parent_key, make_parent_key_name(parent_name, config.detail_key), config.parent_key_column
        )
    return {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            # The path is bound with `str.format`, so percent-encode the value here (`#`, `?` in a name).
            {"name": parent_name, "endpoint": list_endpoint, "data_map": partial(_add_path_segment, config.detail_key)},
            detail_resource,
        ],
    }
