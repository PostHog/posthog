import json
import dataclasses
from typing import Any, Optional

import requests
from requests import PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.canny.settings import CANNY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CANNY_BASE_URL = "https://canny.io/api"
# Airbyte's community connector pages every Canny list endpoint at 100 records.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60


@dataclasses.dataclass
class CannyResumeConfig:
    # Offset into the current endpoint's list. Each schema syncs independently, so a single
    # skip value is enough to resume — there is no cross-endpoint cursor to track.
    skip: int = 0


class CannyBodyAuth(AuthConfigBase):
    """Injects the secret `apiKey` into the JSON POST body.

    Canny authenticates via an `apiKey` request-body parameter rather than a header, which no
    built-in auth location covers. Going through the framework auth contract (instead of a static
    body param) keeps the secret registered for value-based redaction in tracked HTTP logs/samples.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        body: dict[str, Any] = json.loads(request.body) if request.body else {}
        body["apiKey"] = self.api_key
        request.prepare_body(data=None, files=None, json=body)
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.api_key,)


class CannyPaginator(OffsetPaginator):
    """Canny's skip/limit POST-body pagination, terminated by the body's `hasMore` flag.

    Also fails loud on Canny's 200-with-`{"error": ...}` envelope (e.g. an invalid API key),
    surfacing it as an HTTPError so the friendly non-retryable mapping can match the error text.
    `paginated=False` (boards/list) sends no skip/limit and always stops after one page, but still
    gets the error-envelope check.
    """

    def __init__(self, *, paginated: bool = True, offset: int = 0) -> None:
        super().__init__(
            limit=PAGE_SIZE,
            offset=offset,
            offset_param="skip",
            limit_param="limit",
            total_path=None,
            param_location="json",
        )
        self.paginated = paginated

    def init_request(self, request: requests.Request) -> None:
        if self.paginated:
            super().init_request(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except ValueError:
            # An empty/non-JSON body already surfaced as an empty page upstream; there is
            # no `hasMore` to read, so just stop.
            body = None
        if isinstance(body, dict) and body.get("error"):
            raise requests.HTTPError(f"Canny API error: {body['error']} (url: {response.url})", response=response)

        if not self.paginated:
            self._has_next_page = False
            return

        self.offset += self.limit
        self._has_next_page = bool(isinstance(body, dict) and body.get("hasMore"))

    def update_request(self, request: requests.Request) -> None:
        if self.paginated:
            super().update_request(request)


def canny_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CannyResumeConfig],
) -> SourceResponse:
    config = CANNY_ENDPOINTS[endpoint]

    def extract_records(body: dict[str, Any]) -> list[dict[str, Any]]:
        # Canny nests the record array under a per-endpoint key; anything else (missing key,
        # non-list value) is treated as an empty page, matching how the source always behaved.
        records = body.get(config.data_key)
        return records if isinstance(records, list) else []

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CANNY_BASE_URL,
            "auth": CannyBodyAuth(api_key),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "method": "post",
                    "paginator": CannyPaginator(paginated=config.paginated),
                },
                # The whole body reaches the transform (no data_selector) so the record-array
                # extraction above can keep the exact legacy empty-page semantics.
                "data_map": extract_records,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (the merge dedupes on the primary key) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(CannyResumeConfig(skip=int(state["offset"])))

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
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    # boards/list is the cheapest probe: no pagination, returns quickly, and requires only a
    # valid API key (every workspace has at least one board). Reuse the catalog path so this can
    # never drift from the synced endpoint. validate_via_probe only issues GETs, and Canny needs
    # the key POSTed in the body, so the probe stays hand-rolled.
    url = f"{CANNY_BASE_URL}{CANNY_ENDPOINTS['boards'].path}"
    try:
        response = make_tracked_session(redact_values=(api_key,)).post(
            url, data={"apiKey": api_key}, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except Exception:
        return False

    if not response.ok:
        return False

    try:
        body = response.json()
    except ValueError:
        return False

    return not (isinstance(body, dict) and body.get("error"))
