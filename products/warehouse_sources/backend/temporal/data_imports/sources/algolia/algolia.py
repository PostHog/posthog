import re
import dataclasses
from typing import Any, Optional
from urllib.parse import quote

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.settings import (
    ALGOLIA_ENDPOINTS,
    AlgoliaEndpointConfig,
    PaginationStyle,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# Algolia's REST API is served per-application. The main host handles both reads and the
# admin/list operations we use; the `-dsn` replica is only a latency optimisation for search,
# which doesn't matter for a batch import.
ALGOLIA_HOST_TEMPLATE = "https://{application_id}.algolia.net"

# Both 401 and 403 carry this exact message when the application ID / API key pair is wrong.
# A genuine key that merely lacks the ACL for an endpoint returns a different 403 message
# ("Method not allowed with this API key"), which lets us tell "bad credentials" apart from
# "valid credentials, missing scope".
INVALID_CREDENTIALS_MESSAGE = "Invalid Application-ID or API key"

# Algolia application IDs are short alphanumeric tokens. We interpolate the ID into the request
# host, so anything outside this set could break out of the `*.algolia.net` domain and point the
# request (carrying the API key) at an attacker-controlled host — reject it.
_APPLICATION_ID_RE = re.compile(r"^[A-Za-z0-9]+$")


class InvalidApplicationIdError(ValueError):
    pass


@dataclasses.dataclass
class AlgoliaResumeConfig:
    # Browse cursor token to continue an index scan from. None on the first page.
    cursor: str | None = None
    # 0-based page number for the page-paginated endpoints (synonyms, rules, indices).
    page: int | None = None


def _base_url(application_id: str) -> str:
    if not _APPLICATION_ID_RE.match(application_id):
        raise InvalidApplicationIdError("Algolia Application ID must be alphanumeric (letters and digits only)")
    return ALGOLIA_HOST_TEMPLATE.format(application_id=application_id)


def _get_headers(application_id: str, api_key: str) -> dict[str, str]:
    return {
        "X-Algolia-Application-Id": application_id,
        "X-Algolia-API-Key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _endpoint_path(config: AlgoliaEndpointConfig, index_name: str | None) -> str:
    path = config.path
    if config.requires_index:
        if not index_name:
            raise ValueError(f"Algolia endpoint '{config.name}' requires an index name")
        path = path.format(index=quote(index_name, safe=""))
    return path


def _endpoint_url(application_id: str, config: AlgoliaEndpointConfig, index_name: str | None) -> str:
    return f"{_base_url(application_id)}{_endpoint_path(config, index_name)}"


class AlgoliaPageNumberPaginator(PageNumberPaginator):
    """Page-number paginator matching Algolia's mixed termination rules.

    `GET /1/indexes` reports the page count directly (`nbPages`, handled via `total_path`); the
    synonyms/rules search endpoints don't, so when `nbPages` is absent a short final page (fewer
    rows than requested) signals the end without paying an extra empty-page request.
    """

    def __init__(self, page_size: int, **kwargs: Any) -> None:
        super().__init__(total_path="nbPages", **kwargs)
        self.page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page:
            return
        try:
            body = response.json()
            nb_pages = body.get("nbPages") if isinstance(body, dict) else None
        except Exception:
            nb_pages = None
        if nb_pages is None and data is not None and len(data) < self.page_size:
            self._has_next_page = False


def _build_paginator(config: AlgoliaEndpointConfig) -> BasePaginator:
    if config.pagination == PaginationStyle.CURSOR:
        # Browse pages via an opaque cursor carried in the POST body; a missing cursor in the
        # response signals end of index.
        return JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor", param_location="json")
    # Search endpoints (synonyms/rules) page via a 0-based `page` in the POST body; the indices
    # listing pages via `page` in the query string.
    return AlgoliaPageNumberPaginator(
        page_size=config.page_size,
        base_page=0,
        page_param="page",
        param_location="json" if config.method == "POST" else "query",
    )


def algolia_source(
    endpoint: str,
    application_id: str,
    api_key: str,
    index_name: str | None,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[AlgoliaResumeConfig],
) -> SourceResponse:
    config = ALGOLIA_ENDPOINTS[endpoint]
    is_cursor = config.pagination == PaginationStyle.CURSOR

    endpoint_config: dict[str, Any] = {
        "path": _endpoint_path(config, index_name),
        "method": config.method,
        "data_selector": config.data_selector,
        "paginator": _build_paginator(config),
    }
    # Rows requested per page (`hitsPerPage`) travel where the page token does: in the POST body
    # for browse/search, in the query string for the GET indices listing.
    if config.method == "POST":
        endpoint_config["json"] = {"hitsPerPage": config.page_size}
    else:
        endpoint_config["params"] = {"hitsPerPage": config.page_size}

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(application_id),
            # The API key is supplied via the framework auth config so its value is redacted from
            # logs; only the non-secret application ID / content headers are set here.
            "headers": {
                "X-Algolia-Application-Id": application_id,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-Algolia-API-Key", "location": "header"},
        },
        "resources": [{"name": endpoint, "endpoint": endpoint_config}],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        if resume is not None:
            if is_cursor and resume.cursor is not None:
                initial_paginator_state = {"cursor": resume.cursor}
            elif not is_cursor and resume.page is not None:
                initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the hook fires AFTER a page is yielded so a crash
        # re-yields the last page (merge dedupes on the primary key) rather than skipping it.
        if not state:
            return
        if is_cursor:
            if state.get("cursor") is not None:
                manager.save_state(AlgoliaResumeConfig(cursor=state["cursor"]))
        elif state.get("page") is not None:
            manager.save_state(AlgoliaResumeConfig(page=int(state["page"])))

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
        primary_keys=config.primary_keys,
        # Full-refresh endpoints with no stable datetime field to partition on.
        partition_count=1,
        partition_size=1,
    )


def validate_credentials(
    application_id: str,
    api_key: str,
    index_name: str | None = None,
    schema_name: str | None = None,
) -> tuple[bool, str | None]:
    """Confirm the application ID / API key pair is genuine.

    Probes the endpoint matching ``schema_name`` (or the configured index browse, falling back to
    listing indices) with a minimal request. A bad credential pair returns a 403 carrying
    ``INVALID_CREDENTIALS_MESSAGE``; a genuine key that simply lacks the ACL for the probed
    endpoint returns a different 403. At source-create (``schema_name is None``) we accept the
    latter — users may only grant scopes for the endpoints they intend to sync — but reject it for
    a specific schema check.
    """
    config = ALGOLIA_ENDPOINTS.get(schema_name) if schema_name else None
    if config is None:
        config = ALGOLIA_ENDPOINTS["records"] if index_name else ALGOLIA_ENDPOINTS["indices"]

    # An index-scoped probe with no index name configured falls back to listing indices.
    if config.requires_index and not index_name:
        config = ALGOLIA_ENDPOINTS["indices"]

    headers = _get_headers(application_id, api_key)
    try:
        url = _endpoint_url(application_id, config, index_name)
    except InvalidApplicationIdError as exc:
        return False, str(exc)

    session = make_tracked_session(redact_values=(api_key,))
    try:
        if config.method == "POST":
            response = session.post(url, headers=headers, json={"hitsPerPage": 0}, timeout=10)
        else:
            response = session.get(url, headers=headers, timeout=10)
    except requests.RequestException as exc:
        return False, f"Could not reach Algolia: {exc}"

    if response.ok:
        return True, None

    if response.status_code in (401, 403):
        message = ""
        try:
            message = response.json().get("message", "")
        except ValueError:
            pass

        if INVALID_CREDENTIALS_MESSAGE in message:
            return False, "Invalid Algolia Application ID or API key"

        # Genuine credentials, but the key lacks the ACL for the probed endpoint.
        if schema_name is None:
            return True, None
        return False, f"Your Algolia API key is missing the ACL required to sync '{schema_name}'"

    # Any other status is unexpected for a credential probe. Surface Algolia's own message when it
    # sends one, and give the common 404 an actionable hint, rather than echoing a bare status code
    # the user can't act on.
    api_message = ""
    try:
        api_message = response.json().get("message", "")
    except ValueError:
        pass

    if response.status_code == 404:
        target = f"index '{index_name}'" if index_name else "requested resource"
        detail = f" Algolia said: {api_message}." if api_message else ""
        return (
            False,
            f"Algolia couldn't find the {target} (status 404). Check that your Application ID is "
            f"correct and the index exists, then try again.{detail}",
        )

    if api_message:
        return False, f"Algolia rejected the request (status {response.status_code}): {api_message}"
    return (
        False,
        f"Algolia returned an unexpected status ({response.status_code}). Check your Application ID "
        "and API key, then try again.",
    )
