import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlparse

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.settings import WINDMILL_ENDPOINTS

MAX_RETRY_ATTEMPTS = 5
PER_PAGE = 100

HOST_NOT_ALLOWED_ERROR = "Windmill instance URL is not allowed"


class WindmillHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class WindmillResumeConfig:
    # 1-based page number to fetch on resume. A saved value points at the next page to fetch after
    # the last durably-committed one; on resume the scan restarts there and merge dedupes any overlap.
    page: int


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
    built-in (empty-page-only) stop check would incur.
    """

    def __init__(self, per_page: int) -> None:
        super().__init__(base_page=1, page_param="page")
        self._per_page = per_page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < self._per_page:
            self._has_next_page = False


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
    if config.paginated:
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
    paginator: BasePaginator = WindmillPageNumberPaginator(PER_PAGE) if config.paginated else SinglePagePaginator()

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _workspace_base_url(base_url, workspace),
            # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
            # logs and error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_token},
            "paginator": paginator,
            "max_retries": MAX_RETRY_ATTEMPTS,
            # The instance host is customer-controlled, so never follow a redirect that could carry
            # the bearer token to another origin.
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                },
            }
        ],
    }

    # A saved page only indexes into a fixed result set. When an incremental watermark is active it
    # may have advanced since the page was saved (a partial run commits rows and moves the cursor),
    # reshuffling the filtered pages so page N would skip earlier unsynced rows. Restart from page 1
    # in that case; the watermark still bounds the scan and merge dedupes.
    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and after_value is None and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the hook fires after a page is yielded, so the saved
        # page is durably reached only once the consumer has committed everything before it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(WindmillResumeConfig(page=int(state["page"])))

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
