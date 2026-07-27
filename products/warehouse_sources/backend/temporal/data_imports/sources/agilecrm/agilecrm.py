import re
import dataclasses
from typing import Any, Optional

from requests import Request, Response
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.settings import (
    AGILECRM_ENDPOINTS,
    BASE_URL_TEMPLATE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

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
    config = AGILECRM_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(domain),
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
