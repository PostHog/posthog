import dataclasses
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.settings import SPARKPOST_ENDPOINTS

# SparkPost runs fully independent US and EU stacks that do not share data; the user picks which one
# their account lives on. The set is a fixed allow-list, so the host can't be retargeted at an
# arbitrary server.
SPARKPOST_HOSTS = {
    "us": "https://api.sparkpost.com",
    "eu": "https://api.eu.sparkpost.com",
}
DEFAULT_REGION = "us"


@dataclasses.dataclass
class SparkPostResumeConfig:
    next_url: str


def base_url(region: Optional[str]) -> str:
    resolved = (region or DEFAULT_REGION).lower()
    return SPARKPOST_HOSTS.get(resolved, SPARKPOST_HOSTS[DEFAULT_REGION])


def _format_from(value: Any) -> str:
    """Format an incremental cursor value for SparkPost's ``from`` filter.

    SparkPost's Events Search API expects ``YYYY-MM-DDTHH:MM`` and treats it as UTC by default. We
    truncate to the minute (the finest granularity the filter accepts); ``from`` is inclusive, so
    the boundary event is re-fetched and deduped on ``event_id`` by the merge.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        # The stored watermark can come back as an ISO 8601 string; parse it so we still emit the
        # ``YYYY-MM-DDTHH:MM`` SparkPost wants rather than passing e.g. ``2026-01-01T00:00:00Z``
        # through verbatim (which the API rejects). Normalize a trailing ``Z`` for fromisoformat.
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    else:
        return str(value)
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M")


def _is_same_host(url: str, host: str) -> bool:
    """True only for ``https`` URLs whose netloc matches the resolved SparkPost API host."""
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc == urlparse(host).netloc


class SparkPostLinksPaginator(BaseNextUrlPaginator):
    """Follows SparkPost's HAL-style ``links: [{"href": ..., "rel": ...}]`` next link.

    The ``next`` href is usually a host-relative path (e.g. ``/api/v1/events/message?cursor=...``);
    it's resolved against the API host and re-pinned to that host (https + exact netloc) so a tampered
    response can't redirect the authenticated request (and its API key) off-host. A missing / off-host
    / non-https next link — or a page that returned no rows — terminates pagination.
    """

    def __init__(self, host: str) -> None:
        super().__init__()
        self._host = host

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # A page with no rows ends the walk before we even look for a next link, matching the
        # source's "stop as soon as a page returns nothing" behavior.
        if not data:
            self._has_next_page = False
            return

        try:
            body = response.json()
        except Exception:
            body = None

        next_url = self._extract_next_url(body)
        if next_url:
            self._next_url = next_url
            self._has_next_page = True
        else:
            self._has_next_page = False

    def _extract_next_url(self, body: Any) -> Optional[str]:
        links = body.get("links") if isinstance(body, dict) else None
        if not isinstance(links, list):
            return None
        for link in links:
            if isinstance(link, dict) and link.get("rel") == "next":
                href = link.get("href")
                if not isinstance(href, str) or not href:
                    return None
                # ``urljoin`` resolves a relative path against the host and leaves an absolute URL
                # as-is; either way we re-pin it to the resolved host so a tampered response can't
                # send our authenticated request at an internal address (SSRF).
                resolved = urljoin(f"{self._host}/", href)
                return resolved if _is_same_host(resolved, self._host) else None
        return None


def sparkpost_source(
    region: Optional[str],
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SparkPostResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SPARKPOST_ENDPOINTS[endpoint]
    host = base_url(region)

    params: dict[str, Any] = {}
    if config.pagination == "cursor":
        # ``cursor=initial`` opts the request into SparkPost's cursor-based pagination; we then walk
        # the ``rel: next`` links it returns.
        params["cursor"] = "initial"
        params["per_page"] = config.per_page

    if config.timestamp_filter_param:
        # Continue from the stored watermark on incremental runs; otherwise seed the first sync with
        # the lookback window (bounded by SparkPost's 10-day event retention).
        if should_use_incremental_field and db_incremental_field_last_value:
            cutoff: Any = db_incremental_field_last_value
        elif config.default_lookback_days:
            cutoff = datetime.now(UTC) - timedelta(days=config.default_lookback_days)
        else:
            cutoff = None
        if cutoff is not None:
            params[config.timestamp_filter_param] = _format_from(cutoff)

    paginator = SparkPostLinksPaginator(host) if config.pagination == "cursor" else SinglePagePaginator()

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": host,
            # Only the non-secret Accept header lives here; the API key is supplied verbatim on the
            # Authorization header via the framework auth so its value is redacted from logs/errors.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "Authorization", "location": "header"},
            "paginator": paginator,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # SparkPost wraps every list endpoint in ``{"results": [...]}``. A 200 without
                    # ``results`` (or a non-list value) yields no rows and stops — the endpoints are
                    # best-effort and shouldn't fail loud on an empty/absent list.
                    "data_selector": config.data_path,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            # Guard the persisted resume URL — only ever saved from the host-pinned paginator, but
            # re-check so a tampered Redis state can't redirect our authenticated request.
            if not _is_same_host(resume_config.next_url, host):
                raise ValueError(f"SparkPost resume state contains an unexpected URL: {resume_config.next_url!r}")
            initial_paginator_state = {"next_url": resume_config.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded and only while a next page remains — a crash re-yields the
        # last batch (merge dedupes on the primary key) instead of skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(SparkPostResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # ``from`` is injected as a static param above, so the framework's incremental machinery is
        # unused here.
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(region: Optional[str], api_key: str) -> tuple[bool, str | None]:
    """Validate SparkPost credentials with a single cheap probe against ``/api/v1/account``."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{base_url(region)}/api/v1/account",
        headers={"Authorization": api_key, "Accept": "application/json"},
        # 403 means the key authenticated but lacks the ``Account`` scope this probe uses. The key is
        # genuine, and a user who only grants the per-data-type read scopes (as our caption suggests)
        # shouldn't be blocked from connecting — real per-endpoint scope gaps surface at sync time via
        # get_non_retryable_errors. Only 401 is a definitively bad key.
        ok_statuses=(200, 403),
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid SparkPost API key. Check the API key and selected region, then try again."
    return False, f"SparkPost credential validation failed (status {status})."
