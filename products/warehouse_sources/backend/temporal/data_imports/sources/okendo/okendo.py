import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from requests import Request, Response
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.okendo.settings import (
    OKENDO_BASE_URL,
    OKENDO_ENDPOINTS,
    PAGE_LIMIT,
)


@dataclasses.dataclass
class OkendoResumeConfig:
    # Which sub-request of the endpoint was in flight: a review moderation status, or "" for the
    # endpoints that issue a single request.
    variant: str
    # Cursor for the next unfetched page, or None when the variant was walked to its end.
    last_evaluated: Optional[str] = None


def _cursor_from_next_url(next_url: Optional[str]) -> Optional[str]:
    """Pull the `lastEvaluated` cursor out of a `nextUrl` link.

    Okendo documents `nextUrl` as a relative link but not what it is relative to, so the request is
    rebuilt from the cursor rather than following the link verbatim. A link we can't read a cursor
    out of ends pagination instead of being guessed at.
    """
    if not next_url:
        return None
    values = parse_qs(urlsplit(next_url).query).get("lastEvaluated")
    return values[0] if values else None


class OkendoCursorPaginator(BasePaginator):
    def __init__(self) -> None:
        super().__init__()
        self._last_evaluated: Optional[str] = None

    def _apply(self, request: Request) -> None:
        if self._last_evaluated is None:
            return
        if request.params is None:
            request.params = {}
        request.params["lastEvaluated"] = self._last_evaluated

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request of a resumed run.
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except ValueError:
            body = None

        cursor = _cursor_from_next_url(body.get("nextUrl") if isinstance(body, dict) else None)
        if cursor is None or cursor == self._last_evaluated:
            # No link, an unreadable link, or a link repeating the cursor we just sent — either way
            # there is no page to advance to, and following a repeated cursor would loop forever.
            self._has_next_page = False
            return

        self._last_evaluated = cursor
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._last_evaluated is not None:
            return {"last_evaluated": self._last_evaluated}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        last_evaluated = state.get("last_evaluated")
        if last_evaluated is not None:
            self._last_evaluated = str(last_evaluated)
            self._has_next_page = True

    def __str__(self) -> str:
        return "OkendoCursorPaginator()"


def _headers(api_version: str) -> dict[str, str]:
    # Basic auth goes through the framework auth config so the API key is redacted from logs; only
    # the non-secret headers are set here.
    return {"okendo-api-version": api_version, "Accept": "application/json"}


def _request_variants(endpoint: str) -> list[tuple[str, dict[str, Any]]]:
    """The (variant key, query params) pairs making up one full read of an endpoint."""
    config = OKENDO_ENDPOINTS[endpoint]

    base: dict[str, Any] = dict(config.params)
    if config.paginated:
        base["limit"] = PAGE_LIMIT

    if not config.statuses:
        return [("", base)]

    return [(status, {**base, "status": status}) for status in config.statuses]


def okendo_source(
    user_id: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[OkendoResumeConfig],
) -> SourceResponse:
    config = OKENDO_ENDPOINTS[endpoint]
    variants = _request_variants(endpoint)

    def build_rest_config(params: dict[str, Any]) -> RESTAPIConfig:
        return {
            "client": {
                "base_url": OKENDO_BASE_URL,
                "headers": _headers(api_version),
                "auth": {"type": "http_basic", "username": user_id, "password": api_key},
                "paginator": OkendoCursorPaginator() if config.paginated else SinglePagePaginator(),
            },
            # Every resource setting is spelled out below, so there are no shared defaults.
            "resource_defaults": {},
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": params,
                        "data_selector": config.data_selector,
                        # A 200 that drops the row key entirely means the response shape changed —
                        # fail loud rather than silently syncing 0 rows. An empty body is tolerated
                        # because it is unclear whether Okendo omits the key for an empty result.
                        "data_selector_required": True,
                        "data_selector_empty_ok": True,
                    },
                }
            ],
        }

    def items() -> Iterator[list[dict[str, Any]]]:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

        variant_keys = [key for key, _ in variants]
        start = variant_keys.index(resume.variant) if resume is not None and resume.variant in variant_keys else 0

        for position in range(start, len(variants)):
            variant_key, params = variants[position]

            initial_paginator_state: Optional[dict[str, Any]] = None
            if resume is not None and position == start and resume.last_evaluated is not None:
                initial_paginator_state = {"last_evaluated": resume.last_evaluated}

            def save_checkpoint(state: Optional[dict[str, Any]], variant_key: str = variant_key) -> None:
                # Called after each page is yielded, so a crash re-yields the last page (the merge
                # dedupes on primary key) rather than skipping it.
                if state and state.get("last_evaluated"):
                    resumable_source_manager.save_state(
                        OkendoResumeConfig(variant=variant_key, last_evaluated=str(state["last_evaluated"]))
                    )

            yield from rest_api_resource(
                build_rest_config(params),
                team_id,
                job_id,
                None,  # every Okendo endpoint is full refresh
                resume_hook=save_checkpoint,
                initial_paginator_state=initial_paginator_state,
            )

            if position + 1 < len(variants):
                # Point the checkpoint at the next variant so a crash between variants doesn't
                # re-walk the one just finished from its last saved cursor.
                resumable_source_manager.save_state(
                    OkendoResumeConfig(variant=variants[position + 1][0], last_evaluated=None)
                )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Rows arrive oldest-first within a review status but the stream restarts at each status, so
        # it is not globally ascending. Nothing reads this today (no endpoint is incremental), and
        # claiming an order the stream doesn't have would be wrong if one ever is.
        sort_mode=None,
    )


def validate_credentials(user_id: str, api_key: str, api_version: str) -> tuple[bool, int | None]:
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{OKENDO_BASE_URL}/reviews?limit=1",
        headers=_headers(api_version),
        auth=HTTPBasicAuth(user_id, api_key),
    )
