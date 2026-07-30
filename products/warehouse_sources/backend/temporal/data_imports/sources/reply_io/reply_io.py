import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
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
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.settings import REPLY_IO_ENDPOINTS

REPLY_IO_BASE_URL = "https://api.reply.io/v3"
# List endpoints accept `top` up to 1000 (default 25); the largest page minimises round trips
# against Reply's 100 requests/minute rate limit.
PAGE_SIZE = 1000


@dataclasses.dataclass
class ReplyIoResumeConfig:
    # Reply paginates with `top`/`skip` offsets. A crashed full-refresh sync resumes from the
    # offset after the last yielded page; merge dedupes any re-pulled rows on `id`.
    skip: int = 0


def _headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs
    # and raised errors; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


class ReplyIoOffsetPaginator(BasePaginator):
    """`top`/`skip` offset pagination where the response body carries the authoritative
    `hasMore` flag. Advance `skip` by the rows actually received (robust to a server-side page
    cap below the requested `top`) and stop when `hasMore` is false or a page is empty — the
    built-in ``OffsetPaginator`` can't be used because it treats any short page as the last one,
    whereas Reply signals continuation explicitly with `hasMore`.
    """

    def __init__(self, limit: int, offset: int = 0) -> None:
        super().__init__()
        self.limit = limit
        self.offset = offset

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["top"] = self.limit
        request.params["skip"] = self.offset

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        received = len(data) if data else 0
        has_more = False
        try:
            body = response.json()
        except Exception:
            body = None
        if isinstance(body, dict):
            has_more = bool(body.get("hasMore"))

        if received == 0 or not has_more:
            self._has_next_page = False
            return

        # Advance by the rows actually received, not `limit` — robust to a server-side page cap.
        self.offset += received
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["skip"] = self.offset

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.offset already points at the next page to fetch (update_state advanced it).
        return {"skip": self.offset} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        skip = state.get("skip")
        if skip is not None:
            self.offset = int(skip)
            self._has_next_page = True


def reply_io_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ReplyIoResumeConfig],
) -> SourceResponse:
    config = REPLY_IO_ENDPOINTS[endpoint]

    if config.paginated:
        paginator: BasePaginator = ReplyIoOffsetPaginator(limit=PAGE_SIZE)
        # Paginated list endpoints wrap rows in {"items": [...], "hasMore": bool}.
        data_selector: Optional[str] = "items"
    else:
        # Small catalog endpoints (custom fields, template folders) return a bare, unpaginated array.
        paginator = SinglePagePaginator()
        data_selector = None

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": REPLY_IO_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "bearer", "token": api_key},
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "paginator": paginator,
                    "data_selector": data_selector,
                    # A 200 whose body isn't the expected list shape (paginated: not a dict with an
                    # `items` list; unpaginated: not a bare array) is treated as transient and
                    # retried, matching the hand-rolled source's defensive payload check.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"skip": resume.skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it. Bare-array endpoints never resume:
        # SinglePagePaginator reports no next page, so this is a no-op for them.
        if state and state.get("skip") is not None:
            resumable_source_manager.save_state(ReplyIoResumeConfig(skip=int(state["skip"])))

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
    )


def check_access(api_key: str, path: str, paginated: bool = False) -> tuple[int, Optional[str]]:
    """Probe an endpoint with the smallest possible request.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", **_headers()}, redact_values=(api_key,)
    )
    try:
        response = session.get(
            f"{REPLY_IO_BASE_URL}{path}",
            params={"top": 1} if paginated else None,
            timeout=15,
        )
    except Exception as e:
        return 0, f"Could not connect to Reply: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Reply returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str, endpoint: Optional[str] = None) -> tuple[bool, str | None]:
    """Validate the API key against `/whoami` (needs no scope), or a specific endpoint's scope."""
    if endpoint is not None:
        config = REPLY_IO_ENDPOINTS[endpoint]
        status, message = check_access(api_key, config.path, paginated=config.paginated)
        if status == 403:
            return False, f"Your Reply API key is missing the `{config.scope}` scope"
    else:
        status, message = check_access(api_key, "/whoami")

    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Reply API key"
    return False, message or "Could not validate Reply API key"


def check_endpoint_permissions(api_key: str, endpoints: list[str]) -> dict[str, str | None]:
    """Per-table scope status for the schema picker. ``None`` = reachable, str = why not.

    Endpoints sharing a scope share one probe, so the whole check costs at most one request per
    distinct scope. Only a real 403 counts as a missing scope — throttles, 5xx, and network blips
    are reported as reachable so a transient error never blocks the picker.
    """
    verdict_by_scope: dict[str, str | None] = {}
    results: dict[str, str | None] = {}
    for name in endpoints:
        config = REPLY_IO_ENDPOINTS.get(name)
        if config is None:
            results[name] = None
            continue
        if config.scope not in verdict_by_scope:
            status, _ = check_access(api_key, config.path, paginated=config.paginated)
            verdict_by_scope[config.scope] = (
                f"Your Reply API key is missing the `{config.scope}` scope" if status == 403 else None
            )
        results[name] = verdict_by_scope[config.scope]
    return results
