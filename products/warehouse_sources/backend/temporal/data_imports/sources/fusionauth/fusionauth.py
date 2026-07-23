import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth.settings import (
    FUSIONAUTH_ENDPOINTS,
    FusionAuthEndpointConfig,
)

HOST_NOT_ALLOWED_ERROR = "FusionAuth base URL is not allowed"


class FusionAuthHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class FusionAuthResumeConfig:
    offset: int


def normalize_base_url(base_url: str) -> str:
    """Turn whatever the user typed into a bare origin (scheme + host[:port]).

    Accepts values like ``auth.example.com``, ``https://auth.example.com/``, or
    ``https://auth.example.com/api``, and returns ``https://auth.example.com``. Defaults to
    https since FusionAuth Cloud and any customer-facing self-hosted instance should be
    reachable over TLS.
    """
    stripped = base_url.strip().rstrip("/")
    if not stripped.lower().startswith(("http://", "https://")):
        stripped = f"https://{stripped}"
    parsed = urlparse(stripped)
    return f"{parsed.scheme}://{parsed.netloc}"


def _hostname(base_url: str) -> str:
    return (urlparse(base_url).hostname or "").lower()


def _is_same_host(url: str, base_url: str) -> bool:
    try:
        return (urlparse(url).hostname or "").lower() == _hostname(base_url)
    except Exception:
        return False


class FusionAuthOffsetPaginator(BasePaginator):
    """FusionAuth search endpoints take their pagination fields (``startRow``,
    ``numberOfResults``) nested inside the POST body's ``search`` object rather than as
    query params or root-level JSON keys, so the generic ``OffsetPaginator`` doesn't fit.

    Termination relies on ``len(page) < limit`` rather than the response's ``total`` field:
    ``total`` is either absent unless explicitly requested (login records) or an extra
    computation the API doesn't need to do just to page (audit/event logs, users), so an
    undersized page is a simpler, universally available stopping signal.
    """

    def __init__(self, limit: int, offset: int = 0, maximum_offset: Optional[int] = None) -> None:
        super().__init__()
        self.limit = limit
        self.offset = offset
        self.maximum_offset = maximum_offset

    def _set_paging(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        search = request.json.setdefault("search", {})
        search["startRow"] = self.offset
        search["numberOfResults"] = self.limit

    def init_request(self, request: Request) -> None:
        self._set_paging(request)

    def update_request(self, request: Request) -> None:
        self._set_paging(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        self.offset += self.limit
        if len(data) < self.limit:
            self._has_next_page = False
            return
        if self.maximum_offset is not None and self.offset >= self.maximum_offset:
            self._has_next_page = False

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"offset": self.offset} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"FusionAuthOffsetPaginator(offset={self.offset}, limit={self.limit})"


def _build_search_body(config: FusionAuthEndpointConfig, search_extra: dict[str, Any]) -> dict[str, Any]:
    search: dict[str, Any] = {}
    if config.name == "Users":
        # `queryString: "*"` matches every user; sortFields keeps ordering stable across pages.
        search["queryString"] = "*"
        search["sortFields"] = [{"name": "insertInstant", "order": "asc"}]
    elif config.sort_mode == "asc":
        # AuditLogs/EventLogs document an explicit `orderBy` field (unlike LoginRecords),
        # so we can request ascending order and use a simple advancing watermark.
        search["orderBy"] = "insertInstant ASC"
    search.update(search_extra)
    return {"search": search}


def _get_headers() -> dict[str, str]:
    return {"Accept": "application/json", "Content-Type": "application/json"}


def validate_credentials(base_url: str, api_key: str, team_id: Optional[int] = None) -> tuple[bool, str | None]:
    """Probe a cheap, non-search endpoint to confirm the API key is genuine.

    Applications aren't Elasticsearch-backed (unlike the search endpoints this source syncs),
    so this doesn't require the instance to have search configured just to validate a key.
    """
    try:
        normalized = normalize_base_url(base_url)
    except Exception:
        return False, "Invalid FusionAuth base URL"

    hostname = _hostname(normalized)
    if not hostname:
        return False, "Invalid FusionAuth base URL"

    if team_id is not None:
        host_ok, host_err = _is_host_safe(hostname, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    try:
        # Don't follow redirects: the validated host could 3xx to an internal address,
        # defeating the host check above (SSRF).
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{normalized}/api/application",
            headers={**_get_headers(), "Authorization": api_key},
            timeout=10,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid FusionAuth API key"

    try:
        body = response.json()
        return False, body.get("generalErrors", [{}])[0].get("message", response.text) if body else response.text
    except Exception:
        return False, response.text


def fusionauth_source(
    base_url: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FusionAuthResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    db_incremental_field_earliest_value: Optional[Any] = None,
) -> SourceResponse:
    config = FUSIONAUTH_ENDPOINTS[endpoint]
    normalized_url = normalize_base_url(base_url)

    def make_rest_config(search_extra: dict[str, Any], maximum_offset: Optional[int]) -> RESTAPIConfig:
        return {
            "client": {
                "base_url": normalized_url,
                "headers": _get_headers(),
                # Auth rides on the framework auth config so it's redacted from logs/errors;
                # FusionAuth expects the raw key value, no "Bearer"/scheme prefix.
                "auth": {"type": "api_key", "api_key": api_key, "name": "Authorization", "location": "header"},
                "paginator": FusionAuthOffsetPaginator(limit=config.page_size, maximum_offset=maximum_offset),
                # A validated host could still 3xx to an internal address; refuse to follow
                # redirects so the Authorization header never replays to an unexpected host (SSRF).
                "allow_redirects": False,
            },
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "method": "POST",
                        "path": config.path,
                        "json": _build_search_body(config, search_extra),
                        "data_selector": config.data_selector,
                    },
                }
            ],
        }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash
        # re-fetches the next page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(FusionAuthResumeConfig(offset=int(state["offset"])))

    def items() -> Iterator[list[Any]]:
        # Re-check at run time (not just at source-create) in case the base URL was edited to
        # now resolve to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        host_ok, host_err = _is_host_safe(_hostname(normalized_url), team_id)
        if not host_ok:
            raise FusionAuthHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

        if config.sort_mode == "desc":
            # LoginRecords has no documented `orderBy`, so we can't assert ascending order.
            # Mirror the Stripe source's descending-endpoint pattern: scroll strictly-earlier
            # rows (below the lowest instant already synced) and strictly-newer rows (above the
            # highest instant already synced) as two separate bounded passes. Each pass fully
            # drains its own small window every attempt rather than persisting resumable state,
            # since a bounded incremental delta is cheap to redo from scratch on a crash.
            if (
                not should_use_incremental_field
                or db_incremental_field_last_value is None
                and db_incremental_field_earliest_value is None
            ):
                initial_state = None
                if resumable_source_manager.can_resume():
                    resume = resumable_source_manager.load_state()
                    if resume is not None:
                        initial_state = {"offset": resume.offset}
                resource = rest_api_resource(
                    make_rest_config({}, config.maximum_offset),
                    team_id,
                    job_id,
                    None,
                    resume_hook=save_checkpoint,
                    initial_paginator_state=initial_state,
                )
                yield from resource
                return

            if db_incremental_field_earliest_value is not None:
                resource = rest_api_resource(
                    make_rest_config({"end": db_incremental_field_earliest_value}, None), team_id, job_id, None
                )
                yield from resource

            if db_incremental_field_last_value is not None:
                resource = rest_api_resource(
                    make_rest_config({"start": db_incremental_field_last_value}, None), team_id, job_id, None
                )
                yield from resource
            return

        # Ascending (or non-incremental full-refresh) endpoints: a single pass, resumable
        # across the whole run since a first full-history sync can be large.
        search_extra: dict[str, Any] = {}
        if should_use_incremental_field and db_incremental_field_last_value is not None and config.incremental_fields:
            search_extra["start"] = db_incremental_field_last_value

        initial_state = None
        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None:
                initial_state = {"offset": resume.offset}

        resource = rest_api_resource(
            make_rest_config(search_extra, config.maximum_offset),
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        )
        yield from resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
