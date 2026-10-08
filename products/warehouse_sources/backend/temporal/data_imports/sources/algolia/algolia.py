import re
import dataclasses
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any, Optional, cast
from urllib.parse import quote

import requests
from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.settings import (
    ALGOLIA_ENDPOINTS,
    ANALYTICS_LOOKBACK_DAYS,
    AlgoliaApi,
    AlgoliaEndpointConfig,
    PaginationStyle,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    HTTPMethodBasic,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# Algolia's Search API is served per-application. The main host handles both reads and the
# admin/list operations we use; the `-dsn` replica is only a latency optimisation for search,
# which doesn't matter for a batch import.
ALGOLIA_HOST_TEMPLATE = "https://{application_id}.algolia.net"

# The Analytics and A/B Testing APIs live on a separate, region-specific host. The application ID
# rides in a header here (never the host), so these are fixed Algolia hostnames with no injection
# surface — only the two documented regions are reachable.
ALGOLIA_ANALYTICS_HOSTS = {
    "us": "https://analytics.algolia.com",
    "de": "https://analytics.de.algolia.com",
}

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


@frozen
class AlgoliaResumeConfig:
    # Browse cursor token to continue an index scan from. None on the first page.
    cursor: str | None = None
    # 0-based page number for the page-paginated endpoints (synonyms, rules, indices).
    page: int | None = None
    # Row offset for the offset-paginated analytics / A-B testing endpoints.
    offset: int | None = None
    # Fan-out progress, in the shape the shared fan-out builder checkpoints.
    fanout: dict[str, Any] | None = None


def _base_url(application_id: str) -> str:
    if not _APPLICATION_ID_RE.match(application_id):
        raise InvalidApplicationIdError("Algolia Application ID must be alphanumeric (letters and digits only)")
    return ALGOLIA_HOST_TEMPLATE.format(application_id=application_id)


def _analytics_base_url(region: str) -> str:
    # An unknown region falls back to the US host rather than failing; the select field only ever
    # supplies a documented region.
    return ALGOLIA_ANALYTICS_HOSTS.get(region, ALGOLIA_ANALYTICS_HOSTS["us"])


def _base_url_for(config: AlgoliaEndpointConfig, application_id: str, region: str) -> str:
    if config.api == AlgoliaApi.ANALYTICS:
        return _analytics_base_url(region)
    return _base_url(application_id)


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
        # Search endpoints carry the index in the path; analytics endpoints carry it as a query
        # param (added by the caller), so only substitute when the placeholder is present.
        if "{index}" in path:
            path = path.format(index=quote(index_name, safe=""))
    return path


def _endpoint_url(
    application_id: str,
    config: AlgoliaEndpointConfig,
    index_name: str | None,
    region: str = "us",
) -> str:
    return f"{_base_url_for(config, application_id, region)}{_endpoint_path(config, index_name)}"


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
    if config.pagination == PaginationStyle.SINGLE:
        return SinglePagePaginator()
    if config.pagination == PaginationStyle.CURSOR:
        # Browse pages via an opaque cursor carried in the POST body; a missing cursor in the
        # response signals end of index.
        return JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor", param_location="json")
    if config.pagination == PaginationStyle.OFFSET:
        # Analytics / A-B endpoints page via `offset`/`limit` query params. `abtests` reports a
        # `total`; the top-searches/hits tables don't, so a short final page ends the walk.
        return OffsetPaginator(
            limit=config.page_size,
            offset_param="offset",
            limit_param="limit",
            param_location="query",
        )
    # Search endpoints (synonyms/rules) page via a 0-based `page` in the POST body; the indices
    # listing pages via `page` in the query string.
    return AlgoliaPageNumberPaginator(
        page_size=config.page_size,
        base_page=0,
        page_param="page",
        param_location="json" if config.method == "POST" else "query",
    )


def _analytics_params(config: AlgoliaEndpointConfig, index_name: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.requires_index and index_name:
        params["index"] = index_name
    if config.click_analytics:
        params["clickAnalytics"] = "true"
    return params


def _to_start_date(value: Any) -> str | None:
    """Format an incremental watermark as Algolia's `startDate`, floored by the lookback window.

    None (the first incremental sync, before a watermark exists) drops the param so Algolia
    applies its own default period, which every plan's analytics retention covers. An
    unparseable watermark degrades the same way rather than asking for a window Algolia rejects.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        day = value.date()
    elif isinstance(value, date):
        day = value
    else:
        parsed = parse_datetime_value(value)
        if parsed is None:
            return None
        day = parsed.date()
    return (day - timedelta(days=ANALYTICS_LOOKBACK_DAYS)).isoformat()


def _client_config(
    application_id: str,
    api_key: str,
    config: AlgoliaEndpointConfig,
    region: str,
) -> ClientConfig:
    return {
        "base_url": _base_url_for(config, application_id, region),
        # The API key is supplied via the framework auth config so its value is redacted from
        # logs; only the non-secret application ID / content headers are set here.
        "headers": {
            "X-Algolia-Application-Id": application_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        "auth": {"type": "api_key", "api_key": api_key, "name": "X-Algolia-API-Key", "location": "header"},
    }


def _fanout_items(
    config: AlgoliaEndpointConfig,
    fanout_config: DependentEndpointConfig,
    application_id: str,
    api_key: str,
    index_name: str | None,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[AlgoliaResumeConfig],
    region: str,
) -> Iterable[Any]:
    parent_config = ALGOLIA_ENDPOINTS[fanout_config.parent_name]
    # The index is required on both requests but only known at run time, so it is bound here
    # rather than in the static endpoint catalog.
    fanout = dataclasses.replace(fanout_config, parent_params=_analytics_params(parent_config, index_name))

    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            manager.save_state(AlgoliaResumeConfig(fanout=state))

    return build_dependent_resource(
        endpoint_configs=ALGOLIA_ENDPOINTS,
        child_endpoint=config.name,
        fanout=fanout,
        client_config=_client_config(application_id, api_key, config, region),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        # A facet attribute name is a record attribute path, so percent-encode it before the
        # builder binds it into the path with `str.format`, which escapes nothing.
        parent_data_map=lambda row: {**row, "attribute": quote(str(row.get("attribute", "")), safe="")},
        parent_endpoint_extra={
            "data_selector": parent_config.data_selector,
            "paginator": _build_paginator(parent_config),
        },
        child_endpoint_extra={
            "data_selector": config.data_selector,
            "paginator": _build_paginator(config),
        },
        child_params_extra=_analytics_params(config, index_name),
        # The paginators supply `limit` themselves; adding a page-size param would duplicate it.
        page_size_param=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=resume.fanout if resume is not None else None,
    )


def _endpoint_config(
    config: AlgoliaEndpointConfig,
    index_name: str | None,
    should_use_incremental_field: bool,
    incremental_field: str | None,
) -> Endpoint:
    endpoint_config: Endpoint = {
        "path": _endpoint_path(config, index_name),
        "method": cast(HTTPMethodBasic, config.method),
        "data_selector": config.data_selector,
        "paginator": _build_paginator(config),
    }
    if config.api == AlgoliaApi.ANALYTICS:
        # The paginator supplies `offset`/`limit`; the index (when the endpoint is index-scoped)
        # and the click-analytics toggle travel as static query params alongside it.
        endpoint_config["params"] = _analytics_params(config, index_name)
        if should_use_incremental_field and config.start_param:
            incremental: IncrementalConfig = {
                "start_param": config.start_param,
                "cursor_path": incremental_field or config.default_incremental_field or "date",
                "convert": _to_start_date,
            }
            endpoint_config["incremental"] = incremental
    elif config.method == "POST":
        # Rows requested per page (`hitsPerPage`) travel where the page token does: in the POST body
        # for browse/search, in the query string for the GET indices listing.
        endpoint_config["json"] = {"hitsPerPage": config.page_size}
    else:
        endpoint_config["params"] = {"hitsPerPage": config.page_size}
    return endpoint_config


def _resume_state(
    config: AlgoliaEndpointConfig,
    manager: ResumableSourceManager[AlgoliaResumeConfig],
) -> Optional[dict[str, Any]]:
    """Seed the paginator from saved state, in whichever token the endpoint pages by."""
    if not manager.can_resume():
        return None
    resume = manager.load_state()
    if resume is None:
        return None
    if config.pagination == PaginationStyle.CURSOR and resume.cursor is not None:
        return {"cursor": resume.cursor}
    if config.pagination == PaginationStyle.OFFSET and resume.offset is not None:
        return {"offset": resume.offset}
    if config.pagination == PaginationStyle.PAGE and resume.page is not None:
        return {"page": resume.page}
    return None


def _save_resume_state(
    config: AlgoliaEndpointConfig,
    manager: ResumableSourceManager[AlgoliaResumeConfig],
    state: Optional[dict[str, Any]],
) -> None:
    # Persist only when a next page remains; the framework calls this AFTER a page is yielded so a
    # crash re-yields the last page (merge dedupes on the primary key) rather than skipping it.
    if not state:
        return
    if config.pagination == PaginationStyle.CURSOR:
        if state.get("cursor") is not None:
            manager.save_state(AlgoliaResumeConfig(cursor=state["cursor"]))
    elif config.pagination == PaginationStyle.OFFSET:
        if state.get("offset") is not None:
            manager.save_state(AlgoliaResumeConfig(offset=int(state["offset"])))
    elif state.get("page") is not None:
        manager.save_state(AlgoliaResumeConfig(page=int(state["page"])))


def algolia_source(
    endpoint: str,
    application_id: str,
    api_key: str,
    index_name: str | None,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[AlgoliaResumeConfig],
    region: str = "us",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = ALGOLIA_ENDPOINTS[endpoint]

    if config.fanout is not None:
        items: Iterable[Any] = _fanout_items(
            config, config.fanout, application_id, api_key, index_name, team_id, job_id, manager, region
        )
    else:
        rest_config: RESTAPIConfig = {
            "client": _client_config(application_id, api_key, config, region),
            "resource_defaults": {},
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": _endpoint_config(config, index_name, should_use_incremental_field, incremental_field),
                }
            ],
        }
        items = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value if should_use_incremental_field else None,
            resume_hook=lambda state: _save_resume_state(config, manager, state),
            initial_paginator_state=_resume_state(config, manager),
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: items,
        primary_keys=config.primary_keys,
        # Full-refresh endpoints with no stable datetime field to partition on. The daily
        # analytics tables stay unpartitioned too: they hold at most one row per day.
        partition_count=1,
        partition_size=1,
        # The time-series endpoints return their whole window in one response, so the watermark
        # is the max `date` of a single batch regardless of the order Algolia lists the days in.
        sort_mode="asc",
    )


def validate_credentials(
    application_id: str,
    api_key: str,
    index_name: str | None = None,
    schema_name: str | None = None,
    region: str = "us",
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

    # A fan-out endpoint's path carries a parameter resolved from its parent's rows, so there is
    # no URL to probe directly. The parent needs the same `analytics` ACL, so probe that instead.
    if config.fanout is not None:
        config = ALGOLIA_ENDPOINTS[config.fanout.parent_name]

    # An index-scoped probe with no index name configured falls back to listing indices.
    if config.requires_index and not index_name:
        config = ALGOLIA_ENDPOINTS["indices"]

    headers = _get_headers(application_id, api_key)
    try:
        url = _endpoint_url(application_id, config, index_name, region)
    except InvalidApplicationIdError as exc:
        return False, str(exc)

    session = make_tracked_session(redact_values=(api_key,))
    try:
        if config.api == AlgoliaApi.ANALYTICS:
            # Only the paginated breakdowns take `limit`, so sending one to a time-series
            # endpoint would be an undocumented param on an ACL probe.
            params: dict[str, Any] = {"limit": 1} if config.pagination == PaginationStyle.OFFSET else {}
            if config.requires_index and index_name:
                params["index"] = index_name
            response = session.get(url, headers=headers, params=params, timeout=10)
        elif config.method == "POST":
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
