import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.settings import SPOTLERCRM_ENDPOINTS

BASE_URL = "https://apiv4.reallysimplesystems.com"
PAGE_LIMIT = 100
REQUEST_TIMEOUT_SECONDS = 30


@dataclasses.dataclass
class SpotlerCRMResumeConfig:
    next_page: int


class SpotlerCRMPaginator(BasePaginator):
    """Page-number paginator for Spotler CRM list endpoints.

    Pages are 1-indexed (``?page=``); the response's top-level ``metadata.has_more``
    signals whether another page exists. An empty ``list`` also terminates, since the
    API returns no records (not an error) for a page past the end.
    """

    def __init__(self) -> None:
        super().__init__()
        self._page = 1

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self._page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is None or len(data) == 0:
            self._has_next_page = False
            return

        self._page += 1

        try:
            has_more = response.json().get("metadata", {}).get("has_more")
        except Exception:
            has_more = None

        # `has_more` is documented but not guaranteed on every deployment; when it's
        # absent we keep paginating and rely on the empty-page stop above.
        self._has_next_page = has_more is not False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self._page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self._page already points at the next page to fetch (update_state incremented it).
        return {"page": self._page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self._page = int(page)
            self._has_next_page = True


def get_resource(name: str) -> EndpointResource:
    endpoint = SPOTLERCRM_ENDPOINTS[name]
    return {
        "name": endpoint.name,
        "table_name": endpoint.name.lower(),
        # No server-side timestamp filter, so every sync is a full refresh.
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": "list[*].record",
            "path": endpoint.path,
            "params": {"limit": PAGE_LIMIT},
            "paginator": SpotlerCRMPaginator(),
        },
        "table_format": "delta",
    }


def spotlercrm_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SpotlerCRMResumeConfig],
) -> SourceResponse:
    endpoint_config = SPOTLERCRM_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {
                "type": "bearer",
                "token": access_token,
            },
            "headers": {"Accept": "application/json"},
            # `capture=False`: raw Accounts/Contacts/Activities/Documents rows carry arbitrary
            # CRM custom fields and free-text content the name-based scrubbers can't recognise,
            # so keep them out of the shared HTTP sample store (still metered and logged).
            "session": make_tracked_session(
                capture=False,
                redact_values=(access_token,),
                allow_redirects=False,
            ),
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL
        # handles cleanup on completion.
        if state and state.get("page"):
            resumable_source_manager.save_state(SpotlerCRMResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partition_kwargs: dict[str, Any] = {}
    if endpoint_config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [endpoint_config.partition_key],
        }

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[endpoint_config.primary_key],
        **partition_kwargs,
    )


def _probe_endpoint(access_token: str, path: str) -> Response:
    # `capture=False`: probe responses return the same CRM record shapes as the sync, so
    # exclude them from HTTP sample capture too.
    return make_tracked_session(
        redact_values=(access_token,),
        capture=False,
        allow_redirects=False,
    ).get(
        f"{BASE_URL}{path}",
        params={"limit": 1},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    res = _probe_endpoint(access_token, "/accounts")
    if res.status_code == 200:
        return True, None

    # The API answers 403 "Unauthenticated" for a bad token; the docs also list 402
    # ("Forbidden, please check your access token").
    if res.status_code in (402, 403):
        return False, "Invalid Spotler CRM access token. Generate a new token under Settings / Integrations / API V4."

    return False, f"Spotler CRM API returned an unexpected status: {res.status_code}"


def get_endpoint_permissions(access_token: str, endpoints: list[str]) -> dict[str, str | None]:
    """Per-table reachability for the schema picker.

    Some record types are gated behind paid add-ons (Campaigns needs the Marketing
    tool, Cases needs the Service & Support tool). Only a definite denial counts as
    a missing permission; transient failures are treated as reachable.
    """
    permissions: dict[str, str | None] = {}
    for name in endpoints:
        endpoint = SPOTLERCRM_ENDPOINTS.get(name)
        if endpoint is None:
            permissions[name] = None
            continue

        try:
            res = _probe_endpoint(access_token, endpoint.path)
        except Exception:
            permissions[name] = None
            continue

        if res.status_code in (402, 403, 404):
            permissions[name] = (
                f"Your Spotler CRM plan or access token can't read this record type (HTTP {res.status_code}). "
                "It may require a paid add-on such as the Marketing or Service & Support tool."
            )
        else:
            permissions[name] = None

    return permissions
