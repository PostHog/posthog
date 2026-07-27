import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urljoin, urlparse

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.settings import K6_CLOUD_ENDPOINTS

# Grafana Cloud k6 pins the current REST API under a single global host + version path.
K6_CLOUD_HOST = "api.k6.io"
K6_CLOUD_BASE_URL = f"https://{K6_CLOUD_HOST}/cloud/v6"

# $top caps at 1000 rows per page (the documented maximum).
PAGE_SIZE = 1000
REQUEST_TIMEOUT_SECONDS = 60


@dataclasses.dataclass
class K6CloudResumeConfig:
    # Absolute `@nextLink` URL to fetch next. The server encodes the original filter and
    # `$skip` offset into it, so resuming replays exactly where we stopped.
    next_url: str


def _get_headers(api_token: str, stack_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "X-Stack-Id": stack_id,
        "Accept": "application/json",
    }


def _format_rfc3339(value: Any) -> str:
    """Format an incremental value as the RFC 3339 timestamp k6's `created_after` expects."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return str(value)


def _created_after_value(value: Any) -> Optional[str]:
    """Convert the incremental cursor into k6's `created_after` filter value.

    Returns ``None`` when there is no watermark so the client drops the param entirely — a
    full-refresh sync (or the first incremental run before a watermark exists) must send no
    time filter, exactly as the hand-rolled source did.
    """
    if value is None:
        return None
    return _format_rfc3339(value)


def _require_k6_origin(url: str) -> str:
    """Reject any pagination/resume URL that doesn't point at the k6 API origin.

    `@nextLink` is attacker-influenceable response data and resume state is loaded back from
    Redis, so before we send the bearer token + stack id to a URL we confirm its scheme is
    https and its host is the k6 API host. Otherwise a tampered link could exfiltrate the
    stored credential to an attacker-controlled or internal server.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != K6_CLOUD_HOST:
        raise ValueError(f"k6 Cloud: refusing to follow non-k6 URL: {url}")
    return url


def _absolute_url(current_url: str, next_link: str) -> str:
    """Resolve `@nextLink` against the current URL, then pin it to the k6 origin.

    Relative links are joined onto the current (already-pinned) URL; absolute links are taken
    as-is. Either way the result must resolve to the k6 API host — `_require_k6_origin` rejects
    a tampered link before we send credentials to it.
    """
    resolved = next_link if next_link.startswith(("http://", "https://")) else urljoin(current_url, next_link)
    return _require_k6_origin(resolved)


class K6NextLinkPaginator(BaseNextUrlPaginator):
    """Follow k6's `@nextLink` body field, pinned to the k6 https origin.

    Mirrors the hand-rolled source's SSRF guard: any relative link is resolved against the page
    just fetched, and every next/resume URL must be https on the k6 host before the credential-
    bearing request is sent, so a tampered `@nextLink` (or poisoned Redis resume state) can't
    redirect the bearer token off-origin.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        next_link = body.get("@nextLink") if isinstance(body, dict) else None
        if next_link:
            self._next_url = _absolute_url(response.url, next_link)
            self._has_next_page = True
        else:
            self._has_next_page = False

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_url = state.get("next_url")
        if next_url:
            self._next_url = _require_k6_origin(next_url)
            self._has_next_page = True


def k6_cloud_source(
    api_token: str,
    stack_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[K6CloudResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = K6_CLOUD_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if config.paginated:
        params["$top"] = str(PAGE_SIZE)
    if config.order_by:
        params["$orderby"] = config.order_by

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        # A 200 body without `value` means the response shape changed — fail loud instead of
        # silently syncing 0 rows (the hand-rolled source raised KeyError here).
        "data_selector": "value",
        "data_selector_required": True,
        # load_zones returns every row in one page (no $skip/$top, no @nextLink).
        "paginator": K6NextLinkPaginator() if config.paginated else SinglePagePaginator(),
    }
    if config.time_filter_param is not None:
        endpoint_config["incremental"] = {
            "start_param": config.time_filter_param,
            "cursor_path": "created",
            "convert": _created_after_value,
        }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": K6_CLOUD_BASE_URL,
            # Auth (Bearer) goes through the framework auth config so its value is redacted from
            # errors/logs; only the non-secret stack id + accept headers are set here.
            "headers": {"X-Stack-Id": stack_id, "Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_token},
        },
        "resources": [{"name": endpoint, "endpoint": endpoint_config}],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            # Pinned by the paginator's set_resume_state before the token is sent.
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the `id` primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(K6CloudResumeConfig(next_url=state["next_url"]))

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
    )


def validate_credentials(api_token: str, stack_id: str, schema_name: Optional[str] = None) -> tuple[bool, bool]:
    """Probe Grafana Cloud k6 to confirm the token + stack id work.

    Returns ``(is_valid, is_forbidden)``. ``is_forbidden`` distinguishes a 403
    (token is genuine but lacks access) from a 401 (bad token) so the caller can
    accept access gaps at source-create time but reject them for a specific schema.
    """
    config = K6_CLOUD_ENDPOINTS.get(schema_name) if schema_name else None

    if config is not None:
        # For a specific schema, probe that endpoint so the check reflects real access.
        params = {"$top": "1"} if config.paginated else {}
        url = f"{K6_CLOUD_BASE_URL}{config.path}"
        if params:
            url = f"{url}?{urlencode(params)}"
    else:
        # `/auth` validates the token and stack access without touching any resource.
        url = f"{K6_CLOUD_BASE_URL}/auth"

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        url,
        headers=_get_headers(api_token, stack_id),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return ok, status == 403
