import re
from bisect import bisect_left
from collections.abc import Iterator
from typing import Any, Optional, cast

import requests

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.settings import (
    BIGEYE_ENDPOINTS,
    REQUEST_TIMEOUT_SECONDS,
    SCORECARD_DAYS_OF_HISTORY,
    BigeyeEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    create_response_hooks,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
    HTTPMethodBasic,
    ResponseAction,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

DEFAULT_HOST = "app.bigeye.com"

# Bigeye's `.../fetch` endpoints (Sources, Tables, Issues) don't publish a page-size cap; this is
# a conservative default that keeps individual responses small on large workspaces.
PAGE_SIZE = 100

# The exact body of the 400 Bigeye returns when a multi-workspace tenant omits `workspaceId`
# (docs.bigeye.com/docs/api-user-guide). Matched in get_non_retryable_errors so the user is told
# to set the Workspace ID field instead of retrying forever.
WORKSPACE_ID_REQUIRED_MESSAGE = "A workspace ID must be supplied"

_HOST_RE = re.compile(r"^https?://", re.IGNORECASE)

# A metric deleted between the Metrics listing and its own request returns 404; skip it instead of
# failing the whole fan-out.
_PER_METRIC_RESPONSE_ACTIONS: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]


@frozen
class BigeyeResumeConfig:
    next_cursor: str
    # Set only by the per-metric endpoints: the metric to resume from. `next_cursor` is then that
    # metric's page cursor, or empty to start the metric from its first page.
    metric_id: Optional[int] = None


def normalize_host(host: Optional[str]) -> str:
    """Accept a bare host, a full URL, or an empty value (falls back to the SaaS default)."""
    if not host or not host.strip():
        return DEFAULT_HOST
    normalized = _HOST_RE.sub("", host.strip())
    return normalized.split("/")[0].rstrip("/")


def _base_url(host: Optional[str]) -> str:
    return f"https://{normalize_host(host)}"


def _auth_header_value(api_key: str) -> str:
    return f"apikey {api_key}"


def _flatten_collection(item: dict[str, Any]) -> dict[str, Any]:
    # Collection rows nest their identity under `collectionConfiguration`; copy `id`/`name` to the
    # row root so the pipeline's primary-key column ("id") and table naming are top-level fields,
    # while keeping the full nested payload for anyone querying the raw JSON columns.
    config = item.get("collectionConfiguration") or {}
    return {**item, "id": config.get("id"), "name": config.get("name")}


def _flatten_revision(item: dict[str, Any]) -> dict[str, Any]:
    info = item.get("revisionInfo") or {}
    return {**item, "revision_epoch_seconds": info.get("epochSeconds"), "revision_type": info.get("type")}


def _explode_scorecard(item: dict[str, Any]) -> list[dict[str, Any]]:
    category = item.get("metricCategory")
    return [
        {**counts, "metric_category": category, "run_at_epoch_seconds": counts.get("runAtMinute")}
        for counts in item.get("metricRunCounts") or []
    ]


def get_resource(name: str, workspace_id: Optional[int]) -> EndpointResource:
    endpoint_config = BIGEYE_ENDPOINTS[name]

    endpoint: Endpoint = {
        "path": endpoint_config.path,
        "method": cast(HTTPMethodBasic, endpoint_config.method),
        "data_selector": endpoint_config.data_selector,
    }

    if endpoint_config.paginated:
        body: dict[str, Any] = {"pageSize": PAGE_SIZE}
        if workspace_id is not None:
            body["workspaceId"] = workspace_id
        endpoint["json"] = body
        endpoint["paginator"] = JSONResponseCursorPaginator(
            cursor_path="paginationInfo.nextCursor",
            cursor_param="pageCursor",
            param_location="json",
        )
    else:
        endpoint["paginator"] = SinglePagePaginator()
        if name == "Collections" and workspace_id is not None:
            endpoint["params"] = {"workspaceId": workspace_id}
        if name == "MetricScorecard":
            scorecard_body: dict[str, Any] = {"daysOfHistory": SCORECARD_DAYS_OF_HISTORY}
            if workspace_id is not None:
                scorecard_body["where"] = {"workspaceId": workspace_id}
            endpoint["json"] = scorecard_body

    resource: EndpointResource = {
        "name": name,
        "table_name": endpoint_config.table_name,
        "write_disposition": "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }
    if name == "Collections":
        resource["data_map"] = _flatten_collection
    elif name == "MetricScorecard":
        resource["data_map"] = _explode_scorecard
    return resource


def _list_metric_ids(client: RESTClient) -> list[int]:
    metrics_config = BIGEYE_ENDPOINTS["Metrics"]
    metric_ids: set[int] = set()
    for page in client.paginate(
        path=metrics_config.path, paginator=SinglePagePaginator(), data_selector=metrics_config.data_selector
    ):
        metric_ids.update(int(metric["id"]) for metric in page if metric.get("id") is not None)
    # Sorted so a resumed run walks the metrics in the same order as the run that saved the state.
    return sorted(metric_ids)


def _per_metric_request(endpoint_config: BigeyeEndpointConfig, metric_id: int) -> dict[str, Any]:
    paginator: BasePaginator
    if endpoint_config.paginated:
        paginator = JSONResponseCursorPaginator(
            cursor_path="paginationInfo.nextCursor",
            cursor_param="pageCursor",
            param_location="json",
        )
        return {
            "path": endpoint_config.path,
            "method": endpoint_config.method,
            "json": {"metricIdentifier": {"metricId": metric_id}, "pageSize": PAGE_SIZE},
            "paginator": paginator,
        }
    paginator = SinglePagePaginator()
    return {
        "path": endpoint_config.path.format(metricId=metric_id),
        "method": endpoint_config.method,
        "paginator": paginator,
    }


def _iter_per_metric(
    client: RESTClient,
    endpoint_config: BigeyeEndpointConfig,
    resumable_source_manager: ResumableSourceManager[BigeyeResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    metric_ids = _list_metric_ids(client)

    start_index = 0
    resume_cursor: Optional[str] = None
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.metric_id is not None:
        # A saved metric deleted since the checkpoint resumes at the next metric id, not at the start.
        start_index = bisect_left(metric_ids, resume.metric_id)
        if start_index < len(metric_ids) and metric_ids[start_index] == resume.metric_id:
            resume_cursor = resume.next_cursor or None

    hooks = create_response_hooks(_PER_METRIC_RESPONSE_ACTIONS, resource_name=endpoint_config.name)
    row_map = _flatten_revision if endpoint_config.name == "MetricRevisions" else None
    next_page: dict[str, Optional[str]] = {}

    def remember_next_page(state: Optional[dict[str, Any]], has_next_page: bool) -> None:
        cursor = (state or {}).get("cursor") if has_next_page else None
        next_page["cursor"] = str(cursor) if cursor else None

    for index in range(start_index, len(metric_ids)):
        metric_id = metric_ids[index]
        next_metric_id = metric_ids[index + 1] if index + 1 < len(metric_ids) else None
        cursor = resume_cursor if index == start_index else None
        next_page.clear()

        for page in client.paginate(
            **_per_metric_request(endpoint_config, metric_id),
            data_selector=endpoint_config.data_selector,
            hooks=hooks,
            page_state_hook=remember_next_page,
            initial_paginator_state={"cursor": cursor} if cursor else None,
        ):
            next_cursor = next_page.get("cursor")
            if next_cursor:
                resumable_source_manager.save_state(BigeyeResumeConfig(next_cursor=next_cursor, metric_id=metric_id))
            elif next_metric_id is not None:
                resumable_source_manager.save_state(BigeyeResumeConfig(next_cursor="", metric_id=next_metric_id))

            rows = [{**(row_map(row) if row_map else row), "metric_id": metric_id} for row in page]
            if rows:
                yield rows

        # Most metrics return few or no rows, so a long run of requests can pass without a yield.
        resumable_source_manager.safe_point()


def bigeye_source(
    api_key: str,
    host: Optional[str],
    workspace_id: Optional[int],
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BigeyeResumeConfig],
) -> SourceResponse:
    endpoint_config = BIGEYE_ENDPOINTS[endpoint]

    if endpoint_config.per_metric:
        client = RESTClient(
            base_url=_base_url(host),
            auth=APIKeyAuth(api_key=_auth_header_value(api_key), name="Authorization", location="header"),
            # The per-metric requests take no `workspaceId` parameter, so scope them with Bigeye's header.
            headers={"X-Bigeye-Workspace-Id": str(workspace_id)} if workspace_id is not None else None,
            request_timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
        return SourceResponse(
            name=endpoint_config.name,
            items=lambda: _iter_per_metric(client, endpoint_config, resumable_source_manager),
            primary_keys=list(endpoint_config.primary_keys),
            partition_count=1,
            partition_size=1,
        )

    config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(host),
            "auth": {
                "type": "api_key",
                "api_key": _auth_header_value(api_key),
                "name": "Authorization",
                "location": "header",
            },
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
            # A validated host could 3xx to an internal address; refuse to follow redirects (SSRF).
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [get_resource(endpoint, workspace_id)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if endpoint_config.paginated and resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the manager's Redis TTL handles
        # cleanup once the sync completes.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(BigeyeResumeConfig(next_cursor=str(state["cursor"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint if endpoint_config.paginated else None,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=resource.name,
        items=lambda: resource,
        primary_keys=list(endpoint_config.primary_keys),
        column_hints=resource.column_hints,
        # None of these tables expose a stable datetime field worth partitioning on (see
        # settings.py) — small metadata catalogs, full refresh only.
        partition_count=1,
        partition_size=1,
    )


def validate_credentials(
    api_key: str,
    host: Optional[str],
    workspace_id: Optional[int],
    team_id: Optional[int] = None,
) -> tuple[bool, str | None]:
    """Probe the workspaces list, the cheapest endpoint that needs no workspace scoping."""
    normalized_host = normalize_host(host)

    if team_id is not None:
        host_ok, host_err = _is_host_safe(normalized_host, team_id)
        if not host_ok:
            return False, host_err or "That Bigeye host is not allowed."

    url = f"https://{normalized_host}/api/v1/workspaces"
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            url,
            headers={"Authorization": _auth_header_value(api_key)},
            timeout=10,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as e:
        return False, f"Could not reach Bigeye: {e}"

    if response.is_redirect or response.is_permanent_redirect:
        return False, "That Bigeye host is not allowed."

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid Bigeye API key. Please check your key and try again."

    if response.status_code == 403:
        return False, "Your Bigeye API key does not have permission to list workspaces."

    return False, f"Bigeye returned an unexpected error (HTTP {response.status_code})."
