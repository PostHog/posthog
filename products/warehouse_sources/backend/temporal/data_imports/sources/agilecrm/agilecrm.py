import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

from requests import Request, Response, Session
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.settings import (
    AGILECRM_ENDPOINTS,
    AGILECRM_FANOUT_ENDPOINTS,
    BASE_URL_TEMPLATE,
    DEFAULT_PAGE_SIZE,
    TICKETS_ALL_FILTER_NAME,
    TICKETS_FILTERS_PATH,
    TICKETS_LIST_PATH,
    TICKETS_PRIMARY_KEYS,
    TICKETS_SORT_KEY,
    AgileCRMFanoutConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# A valid Agile CRM subdomain is a single DNS label: letters, digits and hyphens only. Constraining
# the domain to this pattern stops a malicious value (e.g. `evil.com#`) from retargeting the basic-auth
# credentials at an attacker-controlled host once it's interpolated into the base URL.
_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")


@dataclasses.dataclass
class AgileCRMResumeConfig:
    # The cursor returned on the last item of the most recently yielded page. `None` starts at the
    # first page.
    cursor: str | None = None


def _validate_domain(domain: str) -> str:
    cleaned = (domain or "").strip()
    if not _DOMAIN_RE.match(cleaned):
        raise ValueError(f"Invalid Agile CRM domain: {domain!r}. Use just the subdomain, e.g. 'acme'.")
    return cleaned


def base_url(domain: str) -> str:
    return BASE_URL_TEMPLATE.format(domain=_validate_domain(domain))


class AgileCRMCursorPaginator(BasePaginator):
    """Agile CRM signals the next page via a `cursor` field on the *last* item of the current page.

    A missing cursor or a short page (fewer items than the requested page size) means the final page.
    The cursor is stripped from the yielded rows by the endpoint's `data_map`, not here.
    """

    def __init__(self, page_size: int) -> None:
        super().__init__()
        self.page_size = page_size
        self._cursor: Optional[str] = None

    def _inject_cursor(self, request: Request) -> None:
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params["cursor"] = self._cursor

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        self._inject_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        items = data or []
        last_item = items[-1] if items else None
        next_cursor = last_item.get("cursor") if isinstance(last_item, dict) else None
        self._cursor = next_cursor
        # No items, no cursor on the last item, or a short page all mean we've reached the end.
        self._has_next_page = bool(next_cursor) and len(items) >= self.page_size

    def update_request(self, request: Request) -> None:
        self._inject_cursor(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._cursor is not None:
            return {"cursor": self._cursor}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = cursor
            self._has_next_page = True


def _strip_cursor(item: dict[str, Any]) -> dict[str, Any]:
    # The cursor is navigation metadata carried on the last item of each page, not data. Strip it so
    # it isn't written to the warehouse as a sparse `cursor` column that only the final row of each
    # page carries.
    return {k: v for k, v in item.items() if k != "cursor"}


def _basic_auth_session(email: str, api_key: str) -> Session:
    session = make_tracked_session(headers={"Accept": "application/json"}, redact_values=(api_key,))
    # Agile CRM authenticates with HTTP Basic: account email as username, API key as password.
    session.auth = HTTPBasicAuth(email, api_key)
    return session


def _paginate(
    session: Session, url: str, page_size: int, extra_params: Optional[dict[str, Any]] = None
) -> Iterator[list[dict[str, Any]]]:
    """Yield each page of a cursor-paginated list endpoint, following the `cursor` on its last item.

    A missing cursor or a short page (fewer items than `page_size`) is terminal — the same rule the
    `RESTAPIConfig`-driven endpoints use, reimplemented here because ticket and fan-out endpoints
    need extra path/param handling the declarative resource config can't express.
    """
    cursor: Optional[str] = None
    while True:
        params: dict[str, Any] = {"page_size": page_size}
        if extra_params:
            params.update(extra_params)
        if cursor is not None:
            params["cursor"] = cursor

        response = session.get(url, params=params)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, list):
            # Known list endpoints return a bare JSON array; an object body means the shape changed.
            raise ValueError(f"Required a list response body from {url}, got {type(body).__name__}")
        if not body:
            return

        yield [_strip_cursor(item) for item in body if isinstance(item, dict)]

        last_item = body[-1]
        cursor = last_item.get("cursor") if isinstance(last_item, dict) else None
        if not cursor or len(body) < page_size:
            return


def _resolve_all_tickets_filter_id(session: Session, base: str) -> Optional[str]:
    # `tickets/filter` needs a saved-filter id. Prefer the "All Tickets" system filter (returns every
    # ticket); fall back to any default filter, then the first filter. None means no filters exist.
    response = session.get(f"{base}/{TICKETS_FILTERS_PATH}")
    response.raise_for_status()
    filters = response.json()
    if not isinstance(filters, list) or not filters:
        return None

    named = [f for f in filters if isinstance(f, dict) and f.get("name") == TICKETS_ALL_FILTER_NAME]
    default = [f for f in filters if isinstance(f, dict) and f.get("is_default_filter")]
    for candidate in (*named, *default, *filters):
        if isinstance(candidate, dict) and candidate.get("id") is not None:
            return str(candidate["id"])
    return None


def _ticket_pages(session: Session, base: str, page_size: int) -> Iterator[list[dict[str, Any]]]:
    filter_id = _resolve_all_tickets_filter_id(session, base)
    if filter_id is None:
        return
    yield from _paginate(
        session,
        f"{base}/{TICKETS_LIST_PATH}",
        page_size,
        {"filter_id": filter_id, "global_sort_key": TICKETS_SORT_KEY},
    )


def _iter_parent_ids(session: Session, base: str, config: AgileCRMFanoutConfig) -> Iterator[Any]:
    if config.parent == "tickets":
        pages = _ticket_pages(session, base, config.page_size)
    else:
        pages = _paginate(session, f"{base}/{config.parent_path}", config.page_size)
    for page in pages:
        for row in page:
            parent_id = row.get("id")
            if parent_id is not None:
                yield parent_id


def _fanout_pages(session: Session, base: str, config: AgileCRMFanoutConfig) -> Iterator[list[dict[str, Any]]]:
    for parent_id in _iter_parent_ids(session, base, config):
        child_url = f"{base}/{config.child_path_template.format(parent_id=parent_id)}"
        response = session.get(child_url)
        response.raise_for_status()
        body = response.json()
        # Child lists are bare arrays; a parent with no children can return an empty body.
        if not isinstance(body, list):
            continue
        rows = [{**_strip_cursor(item), config.parent_id_field: parent_id} for item in body if isinstance(item, dict)]
        if rows:
            yield rows


def agilecrm_source(
    domain: str,
    email: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AgileCRMResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    base = base_url(domain)

    # Tickets and fan-out tables need per-parent requests or filter resolution that the declarative
    # resource config can't express, so they stream through a custom generator. All are full refresh.
    if endpoint == "tickets":
        return SourceResponse(
            name=endpoint,
            items=lambda: _ticket_pages(_basic_auth_session(email, api_key), base, DEFAULT_PAGE_SIZE),
            primary_keys=list(TICKETS_PRIMARY_KEYS),
        )

    if endpoint in AGILECRM_FANOUT_ENDPOINTS:
        fanout_config = AGILECRM_FANOUT_ENDPOINTS[endpoint]
        return SourceResponse(
            name=endpoint,
            items=lambda: _fanout_pages(_basic_auth_session(email, api_key), base, fanout_config),
            primary_keys=list(fanout_config.primary_keys),
        )

    config = AGILECRM_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base,
            "headers": {"Accept": "application/json"},
            # Agile CRM authenticates with HTTP Basic: account email as username, API key as password.
            "auth": {"type": "http_basic", "username": email, "password": api_key},
            "paginator": AgileCRMCursorPaginator(page_size=config.page_size),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"page_size": config.page_size},
                    "data_selector": config.data_selector,
                    # Known list endpoints return a bare JSON array; a 200 object body means the
                    # response shape changed — fail loud instead of silently mis-syncing.
                    "data_selector_required": True,
                },
                "data_map": _strip_cursor,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; saved AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(AgileCRMResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
    )


def validate_credentials(domain: str, email: str, api_key: str) -> bool:
    try:
        url = f"{base_url(domain)}/contacts"
    except ValueError:
        return False

    ok, _status = validate_via_probe(
        lambda: make_tracked_session(headers={"Accept": "application/json"}, redact_values=(api_key,)),
        f"{url}?page_size=1",
        auth=HTTPBasicAuth(email, api_key),
    )
    return ok
