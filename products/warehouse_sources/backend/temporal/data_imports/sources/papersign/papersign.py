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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.papersign.settings import (
    PAPERSIGN_ENDPOINTS,
    PapersignEndpointConfig,
)

# Papersign shares Paperform's single-host REST API. There is no per-account subdomain.
BASE_URL = "https://api.paperform.co/v1"

# `limit` is capped server-side at 100; the default is 20. We request the max to minimise round trips.
PAGE_SIZE = 100


@dataclasses.dataclass
class PapersignResumeConfig:
    # The `skip` (offset) of the page we're currently streaming. We persist *this* page's offset
    # (not the next one) so a crash mid-page resumes by re-fetching the same page rather than
    # skipping past rows still buffered but not yet merged — merge dedupes the re-pulled rows on
    # the primary key. `0` means "start from the first page".
    skip: int = 0


class PapersignPaginator(BasePaginator):
    """limit/skip offset pagination for Papersign list endpoints.

    Termination mirrors the hand-rolled loop exactly: stop on an empty page, on a page shorter than
    the limit (a defensive backstop for the folders/spaces endpoints whose pagination is
    undocumented), or when the authoritative `has_more` flag is false. `skip` advances by the number
    of rows actually returned, and resume persists the *current* page's offset so a crash re-fetches
    it (merge dedupes) rather than skipping still-buffered rows.
    """

    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit
        # Offset of the next request to issue (0, or a seeded resume offset).
        self.skip = 0
        # Offset of the page just fetched — persisted on resume so a crash re-pulls it.
        self._current_skip = 0

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["skip"] = self.skip
        request.params["limit"] = self.limit

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        rows = data or []
        # `skip` still holds the offset of the request that just completed.
        self._current_skip = self.skip

        body = response.json()
        has_more = isinstance(body, dict) and bool(body.get("has_more"))

        if len(rows) == 0 or len(rows) < self.limit or not has_more:
            self._has_next_page = False
            return

        self._has_next_page = True
        self.skip += len(rows)

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["skip"] = self.skip

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # Persist the offset of the page we've already fetched, not the next one.
        return {"skip": self._current_skip}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        skip = state.get("skip")
        if skip is not None:
            self.skip = int(skip)
            self._has_next_page = True


def papersign_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PapersignResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config: PapersignEndpointConfig = PAPERSIGN_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if config.supports_sort:
        # Ascending by created_at keeps offset pagination stable: rows created during the sync
        # append at the end rather than shifting the offsets of pages we've already read.
        params["sort"] = "ASC"

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            # Auth (Bearer) goes through the framework auth config so the token is redacted from
            # every raised error message; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_token},
            "paginator": PapersignPaginator(limit=PAGE_SIZE),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Rows live under `results.<resource>`. `data_selector_required` makes a 200 body
                    # missing that path raise loudly instead of silently syncing 0 rows — on a
                    # full-refresh table that would otherwise wipe previously synced data.
                    "data_selector": f"results.{config.results_key}",
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"skip": resume.skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-fetches
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("skip") is not None:
            resumable_source_manager.save_state(PapersignResumeConfig(skip=int(state["skip"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partition_kwargs: dict[str, Any] = {}
    if config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [config.partition_key],
        }

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Documents arrive ascending (we request `sort=ASC`); folders/spaces are small full scans.
        sort_mode="asc",
        column_hints=resource.column_hints,
        **partition_kwargs,
    )


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Confirm the API token is genuine with one cheap, low-limit list request.

    Paperform issues a single account-wide token (no per-resource scopes), so probing any Papersign
    list endpoint is sufficient. A 401 means the token is wrong; a 403 means the token is valid but
    the plan doesn't include Papersign API access. Anything else reachable counts as valid.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{BASE_URL}/papersign/spaces?limit=1",
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
    )

    if ok:
        return True, None
    if status is None:
        return False, "Could not reach Paperform. Check your network and try again."
    if status == 401:
        return False, "Invalid Paperform API key. Create a new key on your Paperform account page and reconnect."
    if status == 403:
        return (
            False,
            "This Paperform API key does not have Papersign API access. The Papersign API requires a paid "
            "Paperform plan — upgrade the plan, then reconnect.",
        )
    return False, f"Paperform API returned an unexpected status ({status}) while validating credentials."
