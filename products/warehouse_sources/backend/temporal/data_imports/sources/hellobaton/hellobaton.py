import re
import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.settings import (
    HELLOBATON_ENDPOINTS,
    PER_PAGE,
    HellobatonEndpointConfig,
)

HELLOBATON_API_PATH = "/api"

# A single DNS label: letters, digits, hyphens. Rejects anything that could retarget the host
# (slashes, `@`, dots) so the stored API key is only ever sent to `<company>.hellobaton.com`.
_COMPANY_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


@dataclasses.dataclass
class HellobatonResumeConfig:
    # Next 1-indexed page to fetch. None means "start from page 1".
    next_page: int | None = None


class HellobatonPagePaginator(BasePaginator):
    """Baton uses DRF PageNumberPagination: a 1-indexed ``page`` query param, with a full ``next``
    URL in the body signalling more pages. Requesting a page past the last one 404s, so termination
    keys off the body's ``next`` (its absence, or an empty ``results`` page) rather than probing one
    extra empty page. The ``page`` param is re-emitted on every request (api_key/page_size come from
    the framework auth + static params), so the ``next`` URL itself is never followed."""

    def __init__(self, page: int = 1, page_param: str = "page") -> None:
        super().__init__()
        self.page = page
        self.page_param = page_param

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # An empty page ends pagination; requesting beyond the last page 404s, so we must not
        # advance past a body whose `next` cursor is absent.
        if not data:
            self._has_next_page = False
            return
        try:
            has_more = bool(response.json().get("next"))
        except Exception:
            has_more = False
        if has_more:
            self.page += 1
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch (update_state incremented it).
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"HellobatonPagePaginator(page={self.page})"


def normalize_company(company: str) -> str:
    """Reduce user input to a bare, validated Baton company (instance) label.

    Accepts either the full host (``yourcompany.hellobaton.com``) or the bare company
    (``yourcompany``). Raises ``ValueError`` on anything that isn't a single DNS label so the
    API key can never be retargeted away from ``<company>.hellobaton.com``.
    """
    cleaned = company.strip().removeprefix("https://").removeprefix("http://")
    cleaned = cleaned.strip("/")
    cleaned = cleaned.removesuffix(".hellobaton.com")
    if not _COMPANY_RE.match(cleaned):
        raise ValueError(
            f"Invalid Baton company: {company!r}. Enter just your company instance, e.g. 'yourcompany' "
            "for yourcompany.hellobaton.com."
        )
    return cleaned


def _base_url(company: str) -> str:
    return f"https://{normalize_company(company)}.hellobaton.com{HELLOBATON_API_PATH}"


def hellobaton_source(
    company: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HellobatonResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config: HellobatonEndpointConfig = HELLOBATON_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(company),
            # Baton authenticates via an `api_key` query param (not a header), re-required on every
            # page. Framework auth injects it and redacts it from every raised error message.
            "auth": {"type": "api_key", "api_key": api_key, "name": "api_key", "location": "query"},
            "paginator": HellobatonPagePaginator(),
            # Pin every request to `<company>.hellobaton.com`; the api_key must never leave that host.
            "allowed_hosts": [],
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"page_size": PER_PAGE},
                    "data_selector": "results",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(HellobatonResumeConfig(next_page=int(state["page"])))

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
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(company: str, api_key: str) -> tuple[bool, int | None]:
    """Probe Baton's `/projects/` list with a 1-row page to confirm the API key is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. Raises
    ``ValueError`` if the company is malformed so the caller can surface a precise message.
    """
    url = f"{_base_url(company)}/projects/?{urlencode({'api_key': api_key, 'page_size': 1})}"
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,) if api_key else ()),
        url,
    )
