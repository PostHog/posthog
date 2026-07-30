import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.braze.settings import (
    BRAZE_ENDPOINTS,
    BrazeEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

# Shared so the source-layer 403 acceptance check can't drift from the message produced here.
BRAZE_FORBIDDEN_MSG = "Your Braze API key does not have permission for this endpoint"
HOST_NOT_ALLOWED_ERROR = "Braze REST endpoint URL is not allowed"


class BrazeHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class BrazeResumeConfig:
    # Page index (page pagination) or row offset (offset pagination) to resume from.
    # Old checkpoints stored the last-yielded cursor, so re-loading one re-fetches that
    # page and merge dedupes on primary key.
    cursor: int


def normalize_base_url(url: str) -> str:
    """Force https and strip any trailing slash so endpoint paths join cleanly.

    Forcing https prevents a downgrade to plaintext, matching the Okta/ServiceNow
    connectors that also take a user-supplied host.
    """
    url = re.sub(r"^https?://", "", url.strip(), flags=re.IGNORECASE)
    return f"https://{url.rstrip('/')}"


def _host_from_url(base_url: str) -> str:
    return (urlparse(normalize_base_url(base_url)).hostname or "").lower()


def _format_modified_after(value: Any) -> str:
    """Format an incremental cursor value as an ISO-8601 string for Braze filters."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _normalize_items(config: BrazeEndpointConfig, items: list[Any]) -> list[dict[str, Any]]:
    if config.wrap_scalar_as:
        return [{config.wrap_scalar_as: item} for item in items]
    return [item for item in items if isinstance(item, dict)]


class BrazeOffsetPaginator(BasePaginator):
    """Braze's limit/offset pagination (templates/content blocks).

    Diverges from the generic ``OffsetPaginator`` in two Braze-specific ways: the
    ``offset`` param must be omitted when 0 (Braze rejects ``offset=0`` as not a
    positive integer), and only an empty page terminates — a short page is not
    treated as the last one.
    """

    def __init__(self, limit: int, offset: int = 0) -> None:
        super().__init__()
        self.limit = limit
        self.offset = offset

    def _inject_params(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["limit"] = self.limit
        if self.offset:
            request.params["offset"] = self.offset

    def init_request(self, request: Request) -> None:
        self._inject_params(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        self.offset += self.limit
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._inject_params(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.offset already points at the next page to fetch (update_state incremented it).
        return {"offset": self.offset} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"BrazeOffsetPaginator(offset={self.offset}, limit={self.limit})"


def validate_credentials(
    api_key: str, base_url: str, path: str = "/campaigns/list", team_id: int | None = None
) -> tuple[bool, str | None]:
    """Probe a Braze list endpoint to confirm the REST API key is valid.

    Braze keys are scoped per endpoint, so a 403 means the key is genuine but
    lacks the probed scope — the caller decides whether to accept that.
    """
    # The REST endpoint URL is fully customer-controlled, so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(_host_from_url(base_url), team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"{normalize_base_url(base_url)}{path}?page=0"
    ok, status = validate_via_probe(
        # No redirects: keep the probe pinned to the validated host (SSRF hardening).
        lambda: make_tracked_session(allow_redirects=False, redact_values=(api_key,)),
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Braze API key"
    if status == 403:
        return False, BRAZE_FORBIDDEN_MSG
    if status is None:
        return False, "Could not reach the Braze API"
    return False, f"Braze API returned status {status}"


def braze_source(
    api_key: str,
    base_url: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BrazeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BRAZE_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if config.modified_after_param and should_use_incremental_field and db_incremental_field_last_value:
        params[config.modified_after_param] = _format_modified_after(db_incremental_field_last_value)

    paginator: BasePaginator
    if config.pagination == "page":
        paginator = PageNumberPaginator(base_page=0)
        state_key = "page"
    else:
        paginator = BrazeOffsetPaginator(limit=config.page_size)
        state_key = "offset"

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": normalize_base_url(base_url),
            "headers": {"Accept": "application/json"},
            # Framework Bearer auth so the key is redacted from logs.
            "auth": {"type": "bearer", "token": api_key},
            # No redirects: the base URL is customer-supplied, so keep traffic pinned
            # to the validated host (SSRF hardening).
            "session": make_tracked_session(allow_redirects=False, redact_values=(api_key,)),
            "paginator": paginator,
        },
        "resource_defaults": None,
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Braze omits the data key when there is nothing to return, so a missing
                    # key is a normal end-of-data page — don't set data_selector_required.
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {state_key: resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; saved AFTER a page is yielded so a crash
        # never skips an undelivered page.
        if state and state.get(state_key) is not None:
            resumable_source_manager.save_state(BrazeResumeConfig(cursor=int(state[state_key])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        # Re-check at run time (not just at source-create) in case the URL was edited or now
        # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        host_ok, host_err = _is_host_safe(_host_from_url(base_url), team_id)
        if not host_ok:
            raise BrazeHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

        for page in resource:
            # events/list returns bare event-name strings; other endpoints may carry
            # stray non-dict rows — reshape/drop them exactly as before the migration.
            yield _normalize_items(config, page)

    return SourceResponse(
        name=endpoint,
        items=get_rows,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
