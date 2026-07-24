import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from requests import PreparedRequest, Request, Response

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.discourse.settings import (
    DISCOURSE_ENDPOINTS,
    POSTS_PAGE_SIZE,
)

REQUEST_TIMEOUT_SECONDS = 30

HOST_NOT_ALLOWED_ERROR = "Discourse instance URL is not allowed"


class DiscourseHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class DiscourseResumeConfig:
    # Next page to fetch for `PageNumberPaginator`-based endpoints (topics, groups, users).
    page: Optional[int] = None
    # Next `before=<post_id>` cursor for the posts endpoint's descending id walk.
    before: Optional[int] = None


def normalize_base_url(base_url: str) -> str:
    url = base_url.strip()
    if url and "://" not in url:
        url = f"https://{url}"
    return url.rstrip("/")


def _validated_hostname(base_url: str) -> Optional[str]:
    """Hostname of the normalized instance URL, or None when the URL is malformed or ambiguous.

    SSRF guard: urlparse treats a backslash as ordinary userinfo and an "@" as a userinfo
    separator, but urllib3/requests treat the backslash as an authority separator, so
    `https://127.0.0.1\\@example.com` validates as example.com yet connects to 127.0.0.1. A
    legitimate instance URL has no userinfo, so reject either construct outright.
    """
    if "\\" in base_url or "%5c" in base_url.lower():
        return None
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or "@" in parsed.netloc:
        return None
    # The API key rides in a header on every request, so plaintext http would leak it to any
    # network observer once it egresses over the public internet. Self-hosted operators control
    # their own network path, so http stays allowed there (mirrors Unleash/Gitea).
    if parsed.scheme == "http" and is_cloud():
        return None
    hostname = parsed.hostname
    if not hostname or not re.match(r"^[A-Za-z0-9.\-]+$", hostname):
        return None
    return hostname


def hostname_of(base_url: str) -> Optional[str]:
    return _validated_hostname(normalize_base_url(base_url))


def _check_host(base_url: str, team_id: int) -> None:
    hostname = hostname_of(base_url)
    if not hostname:
        raise DiscourseHostNotAllowedError("Invalid Discourse instance URL")
    host_ok, host_err = _is_host_safe(hostname, team_id)
    if not host_ok:
        raise DiscourseHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)


class DiscourseAuth(AuthConfigBase):
    """Discourse's admin API auth: `Api-Key` + `Api-Username` headers (no Bearer/Basic scheme).

    Query-param auth (`?api_key=`) was removed by Discourse in 2020, so header auth is the only
    supported method — no built-in framework auth type carries two header values, hence this
    custom auth class.
    """

    def __init__(self, api_key: str, api_username: str) -> None:
        self.api_key = api_key
        self.api_username = api_username

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Api-Key"] = self.api_key
        request.headers["Api-Username"] = self.api_username
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.api_key,) if self.api_key else ()


class DiscoursePostsPaginator(BasePaginator):
    """Cursor paginator for `/posts.json`, walking backward via `before=<post_id>`.

    Discourse's global post firehose returns posts newest-first with no `since`/`after` filter,
    so an incremental sync instead walks backward from the newest post and stops once a whole
    page is at or before the last-synced post id (the watermark) — otherwise every incremental
    sync would re-walk the full post history. A full-refresh sync (no watermark) walks all the
    way back until a page comes back shorter than the fixed page size.
    """

    def __init__(self, stop_at_or_before: Optional[int] = None) -> None:
        super().__init__()
        self._before: Optional[int] = None
        self._stop_at_or_before = stop_at_or_before

    def init_request(self, request: Request) -> None:
        if self._before is not None:
            if request.params is None:
                request.params = {}
            request.params["before"] = self._before

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return

        ids = [item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), int)]
        if not ids:
            self._has_next_page = False
            return

        oldest_in_page = min(ids)
        self._before = oldest_in_page
        self._has_next_page = len(data) >= POSTS_PAGE_SIZE

        if self._has_next_page and self._stop_at_or_before is not None and oldest_in_page <= self._stop_at_or_before:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._before is not None:
            if request.params is None:
                request.params = {}
            request.params["before"] = self._before

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"before": self._before} if self._has_next_page and self._before is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        before = state.get("before")
        if before is not None:
            self._before = int(before)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"DiscoursePostsPaginator(before={self._before}, stop_at_or_before={self._stop_at_or_before})"


def _flatten_directory_item(item: dict[str, Any]) -> dict[str, Any]:
    """Lift the nested `user` object's fields onto the row so the users table isn't a blob column.

    The outer `id` already equals `user.id`, so the nested copy is dropped rather than
    overwriting the (identical) outer value.
    """
    user = item.pop("user", None)
    if isinstance(user, dict):
        for key, value in user.items():
            if key == "id":
                continue
            item[key] = value
    return item


def _coerce_incremental_cursor(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def discourse_source(
    base_url: str,
    api_key: str,
    api_username: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DiscourseResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    endpoint_config = DISCOURSE_ENDPOINTS[endpoint]
    normalized_base_url = normalize_base_url(base_url)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state: Optional[dict[str, Any]] = None

    if endpoint == "posts":
        watermark = (
            _coerce_incremental_cursor(db_incremental_field_last_value) if should_use_incremental_field else None
        )
        paginator: BasePaginator = DiscoursePostsPaginator(stop_at_or_before=watermark)
        if resume_config is not None and resume_config.before is not None:
            initial_paginator_state = {"before": resume_config.before}
    elif endpoint_config.paginated:
        paginator = PageNumberPaginator(base_page=0, page_param="page")
        if resume_config is not None and resume_config.page is not None:
            initial_paginator_state = {"page": resume_config.page}
    else:
        paginator = SinglePagePaginator()

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion. Save AFTER a page is yielded (see caller) so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        if not state:
            return
        resumable_source_manager.save_state(DiscourseResumeConfig(page=state.get("page"), before=state.get("before")))

    endpoint_dict: Endpoint = {
        "path": endpoint_config.path,
        "data_selector": endpoint_config.data_selector,
        # A 200 whose body isn't the expected list shape is treated as a transient glitch and
        # retried, rather than silently syncing 0 rows.
        "data_selector_malformed_retryable": True,
        "paginator": paginator,
    }
    if endpoint_config.extra_params:
        endpoint_dict["params"] = dict(endpoint_config.extra_params)

    write_disposition: Any = "replace"
    if endpoint_config.incremental_fields:
        write_disposition = (
            {"disposition": "merge", "strategy": "upsert"} if should_use_incremental_field else "replace"
        )

    resource: EndpointResource = {
        "name": endpoint,
        "endpoint": endpoint_dict,
        "write_disposition": write_disposition,
        "table_format": "delta",
    }
    if endpoint == "users":
        # `data_map` is a resource-level key (applied after data_selector, before type
        # coercion) — not an `endpoint` key.
        resource["data_map"] = _flatten_directory_item

    config: RESTAPIConfig = {
        "client": {
            "base_url": normalized_base_url,
            "auth": DiscourseAuth(api_key=api_key, api_username=api_username),
            # The instance URL is user-supplied: pin every request (including pagination) to the
            # base host and refuse redirects so the credentialed request can't be bounced off-host.
            "allowed_hosts": [],
            "allow_redirects": False,
            # Bound every sync request so a host that accepts the connection then stalls can't hold
            # an import worker indefinitely (the credential probe is already bounded separately).
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
        },
        "resource_defaults": {},
        "resources": [resource],
    }

    def items() -> Iterator[list[dict[str, Any]]]:
        # Re-checked at run time (not just at source-create) in case the instance URL was edited
        # or now resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        _check_host(base_url, team_id)
        resource = rest_api_resource(
            config,
            team_id,
            job_id,
            # Incremental filtering is handled by the paginator's own watermark (there is no
            # declarative `incremental` param on the endpoint — Discourse has no server-side
            # since-filter to plug into it), so nothing needs to flow through this framework arg.
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        for batch in resource:
            if batch:
                yield batch

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=endpoint_config.primary_keys,
        sort_mode=endpoint_config.sort_mode,
        partition_count=1 if endpoint_config.partition_key else None,
        partition_size=1 if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def _get_session(api_key: str, api_username: str) -> requests.Session:
    # The instance URL is user-supplied, so pin redirects off so host validation and the
    # outbound request stay on the same target (SSRF defense-in-depth). Redact the key from logs.
    return make_tracked_session(
        headers={"Api-Key": api_key, "Api-Username": api_username, "Accept": "application/json"},
        redact_values=(api_key,),
        allow_redirects=False,
    )


def _error_message(response: requests.Response) -> Optional[str]:
    try:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("errors"), list) and body["errors"]:
            first = body["errors"][0]
            if isinstance(first, str):
                return first
    except Exception:
        pass
    return None


def validate_credentials(
    base_url: str,
    api_key: str,
    api_username: str,
    schema_name: Optional[str] = None,
    team_id: Optional[int] = None,
) -> tuple[bool, Optional[str]]:
    """Probe `/session/current.json` to confirm the key/username pair is genuine.

    At source-create (`schema_name is None`) a 403 is accepted: a scoped API key may not cover
    this particular probe endpoint even though it's valid for the tables the user wants to sync.
    A scoped probe (`schema_name` set) treats 403 as a hard failure.
    """
    normalized_base_url = normalize_base_url(base_url)
    hostname = _validated_hostname(normalized_base_url)
    if not hostname:
        return False, "Invalid Discourse instance URL"

    # The instance URL is fully customer-controlled, so block hosts that resolve to private/
    # internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(hostname, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    session = _get_session(api_key, api_username)
    try:
        # The session never follows redirects: the validated host could 3xx to an internal
        # address, defeating the host check above (SSRF).
        response = session.get(f"{normalized_base_url}/session/current.json", timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as e:
        return False, f"Could not connect to Discourse: {e}"

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, _error_message(response) or "Your Discourse API key does not have the required permissions"

    return False, _error_message(response) or f"Discourse returned HTTP {response.status_code}"
