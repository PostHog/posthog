from typing import Any, Optional

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.glassfrog.settings import GLASSFROG_ENDPOINTS

GLASSFROG_BASE_URL = "https://api.glassfrog.com/api/v3"
# Documented `per_page` maximum; the API default is 30.
GLASSFROG_PAGE_SIZE = 100


class GlassfrogPageNumberPaginator(PageNumberPaginator):
    """Page-number paginator that stops on a short page.

    List responses carry no total count, so a page with fewer than `per_page` rows is the last one.
    """

    def __init__(self) -> None:
        super().__init__(base_page=1)
        self._previous_first_row: Any = None

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        first_row = data[0] if data else None
        # Fail loudly instead of looping forever if the API ignores `page` and returns the same rows.
        if first_row is not None and first_row == self._previous_first_row:
            raise ValueError(f"GlassFrog returned the same rows for page {self.page} as the page before it")
        self._previous_first_row = first_row

        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < GLASSFROG_PAGE_SIZE:
            self._has_next_page = False


def _make_session(api_key: str) -> requests.Session:
    # `redact_values` masks the key in tracked logs/samples. `capture=False` keeps response bodies out
    # of HTTP sample storage — people rows carry names/emails and org-structure data the name-based
    # sample scrubbers can't fully recognise. Requests are still metered and logged (status + url).
    # `allow_redirects=False` because the key rides a custom header that `requests` would replay
    # across a cross-origin redirect.
    return make_tracked_session(redact_values=(api_key,), capture=False, allow_redirects=False)


def validate_credentials(api_key: str) -> bool:
    # `/circles` is the cheapest authenticated probe: every v3 API key can list the circles it can
    # see, so a 200 confirms the key is genuine. allow_redirects=False because the key rides a
    # custom header that `requests` would replay across a cross-origin redirect.
    ok, _status = validate_via_probe(
        lambda: _make_session(api_key),
        f"{GLASSFROG_BASE_URL}/circles",
        headers={"X-Auth-Token": api_key, "Accept": "application/json"},
        allow_redirects=False,
    )
    return ok


def glassfrog_source(api_key: str, endpoint: str, team_id: int, job_id: str) -> SourceResponse:
    endpoint_config = GLASSFROG_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": GLASSFROG_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Framework auth (not a hand-built header) so the key is redacted wherever it surfaces.
            "auth": {"type": "api_key", "name": "X-Auth-Token", "api_key": api_key, "location": "header"},
            "paginator": GlassfrogPageNumberPaginator(),
            "session": _make_session(api_key),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": endpoint_config.path,
                    "params": {"per_page": GLASSFROG_PAGE_SIZE, **endpoint_config.params},
                    # Rows are wrapped under a resource key ({"circles": [...]}); a body without it
                    # is an unexpected/error shape. Fail loud instead of syncing zero rows.
                    "data_selector": endpoint_config.data_selector,
                    "data_selector_required": True,
                },
            }
        ],
    }

    resource = rest_api_resource(rest_config, team_id, job_id, None)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
