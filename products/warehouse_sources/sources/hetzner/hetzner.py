import math
import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.settings import (
    HETZNER_CHILD_ENDPOINTS,
    HETZNER_ENDPOINTS,
    HETZNER_METRICS_ENDPOINTS,
)

# Single global base URL — Hetzner Cloud has no regional hosts.
HETZNER_BASE_URL = "https://api.hetzner.cloud/v1"

# Max page size the API accepts; anything larger is clamped by the server. Bigger pages mean fewer
# round trips against the 3600 req/hour budget.
PAGE_SIZE = 50

# Hetzner list endpoints are 1-indexed.
FIRST_PAGE = 1

# Metrics: a fixed step keeps sample timestamps on the same grid every run, so a re-read sample
# merges onto its existing row instead of landing beside it. The API caps a series at 500 samples
# per request, so each request covers at most 499 steps.
METRICS_STEP_SECONDS = 300
METRICS_MAX_SAMPLES = 500
# The API keeps 30 days of metrics; the margin keeps the oldest window inside it despite clock skew.
METRICS_RETENTION = timedelta(days=30) - timedelta(hours=1)
REQUEST_TIMEOUT = (10, 60)


@dataclasses.dataclass(frozen=True)
class HetznerResumeConfig:
    # Page number to fetch first on resume. The framework checkpoints the NEXT page after a page has
    # been yielded, so a crash mid-page resumes onto that in-flight page and re-reads it rather than
    # skipping its un-yielded tail (dropping rows is worse than re-reading a page). These tables are
    # full refresh with an `id` primary key, so any rows a re-fetched page duplicates are wiped by the
    # next non-resumed run (which overwrites the table from scratch) or deduped on merge.
    page: int = FIRST_PAGE


@dataclasses.dataclass(frozen=True)
class MetricsWindow:
    start: int
    end: int


def _non_secret_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs and
    # raised error messages; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _list_paginator() -> PageNumberPaginator:
    # Page-number pagination; `meta.pagination.last_page` is the TOTAL number of pages, so the
    # paginator stops after the last page instead of paying one extra empty-page request.
    # stop_after_empty_page (default) is the fallback when a response omits the total.
    return PageNumberPaginator(base_page=FIRST_PAGE, page_param="page", total_path="meta.pagination.last_page")


def hetzner_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HetznerResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HETZNER_ENDPOINTS[endpoint]

    params: dict[str, Any] = {"per_page": PAGE_SIZE} if config.paginated else {}
    if config.sort is not None:
        params["sort"] = config.sort

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": HETZNER_BASE_URL,
            "headers": _non_secret_headers(),
            "auth": {"type": "bearer", "token": api_token},
            "paginator": _list_paginator() if config.paginated else SinglePagePaginator(),
            "request_timeout": REQUEST_TIMEOUT,
            # Disable redirect following so a 3xx can never replay the Authorization header to another
            # host — the SSRF guard the hand-rolled transport used.
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # The list lives under the endpoint's envelope key, e.g. {"servers": [...]}. A
                    # missing key means an empty page (Hetzner never returns 200 without it), so a
                    # non-required selector lets the paginator stop rather than failing loud.
                    "data_selector": config.response_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the framework calls this AFTER a page is yielded with
        # the NEXT page to fetch, so a crash re-reads the in-flight page (bounded, deduped) rather than
        # skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(HetznerResumeConfig(page=int(state["page"])))

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
        # id:asc (or default order for the catalog endpoints) — rows arrive oldest-id first.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def _align_up(epoch: int) -> int:
    return -(-epoch // METRICS_STEP_SECONDS) * METRICS_STEP_SECONDS


def _to_epoch(value: Any) -> Optional[int]:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp())


def _to_rfc3339(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _metric_windows(start: int, end: int) -> Iterator[MetricsWindow]:
    span = METRICS_STEP_SECONDS * (METRICS_MAX_SAMPLES - 1)
    while start <= end:
        window_end = min(start + span, end)
        yield MetricsWindow(start=start, end=window_end)
        # Windows include both ends, so the next one starts a step later to not repeat a sample.
        start = window_end + METRICS_STEP_SECONDS


def _metrics_start(now: int, created: Any, last_value: Any) -> int:
    # Never ask for samples older than retention or than the resource itself. On incremental runs
    # the watermark sample is read again, because the newest sample can still change.
    candidates = [now - int(METRICS_RETENTION.total_seconds())]
    for value in (created, last_value):
        epoch = _to_epoch(value)
        if epoch is not None:
            candidates.append(epoch)
    return _align_up(max(candidates))


def _to_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _metric_rows(parent_id_column: str, parent_id: Any, metrics: dict[str, Any]) -> list[dict[str, Any]]:
    # The API returns one `{series: {"values": [[epoch, "value"], ...]}}` map per request; flatten it
    # to one row per series sample.
    return [
        {
            parent_id_column: parent_id,
            "metric": series,
            "timestamp": datetime.fromtimestamp(sample[0], tz=UTC),
            "value": _to_float(sample[1]),
        }
        for series, data in (metrics.get("time_series") or {}).items()
        for sample in (data or {}).get("values") or []
    ]


def hetzner_metrics_source(
    api_token: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[HetznerResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HETZNER_METRICS_ENDPOINTS[endpoint]
    parent = HETZNER_ENDPOINTS[config.parent]

    def items() -> Iterator[list[dict[str, Any]]]:
        client = RESTClient(
            base_url=HETZNER_BASE_URL,
            headers=_non_secret_headers(),
            auth=BearerTokenAuth(api_token),
            allow_redirects=False,
            request_timeout=REQUEST_TIMEOUT,
        )
        now = int(datetime.now(UTC).timestamp())
        end = now - now % METRICS_STEP_SECONDS
        parent_params = {"per_page": PAGE_SIZE, "sort": parent.sort}

        for resources in client.paginate(
            parent.path, params=parent_params, paginator=_list_paginator(), data_selector=parent.response_key
        ):
            for resource in resources:
                start = _metrics_start(now, resource.get("created"), db_incremental_field_last_value)
                for window in _metric_windows(start, end):
                    params = {
                        "type": config.metric_types,
                        "start": _to_rfc3339(window.start),
                        "end": _to_rfc3339(window.end),
                        "step": METRICS_STEP_SECONDS,
                    }
                    try:
                        pages = list(
                            client.paginate(
                                f"{parent.path}/{resource['id']}/metrics",
                                params=params,
                                paginator=SinglePagePaginator(),
                                data_selector="metrics",
                            )
                        )
                    except HTTPError as e:
                        # The resource was deleted after the parent list was read.
                        if e.response is not None and e.response.status_code == 404:
                            break
                        raise

                    rows = [
                        row
                        for page in pages
                        for metrics in page
                        for row in _metric_rows(config.parent_id_column, resource["id"], metrics)
                    ]
                    if rows:
                        yield rows
                    else:
                        resumable_source_manager.safe_point()

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=[config.parent_id_column, "metric", "timestamp"],
        # Rows arrive oldest-first per resource, not across resources, so desc mode keeps the
        # pipeline from checkpointing one resource's newest sample as the watermark for all of them.
        # The watermark then commits once, at the end of a successful run.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=["timestamp"],
    )


def hetzner_child_source(
    api_token: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[HetznerResumeConfig],
) -> SourceResponse:
    config = HETZNER_CHILD_ENDPOINTS[endpoint]
    parent = HETZNER_ENDPOINTS[config.parent]

    def items() -> Iterator[list[dict[str, Any]]]:
        client = RESTClient(
            base_url=HETZNER_BASE_URL,
            headers=_non_secret_headers(),
            auth=BearerTokenAuth(api_token),
            allow_redirects=False,
            request_timeout=REQUEST_TIMEOUT,
        )
        parent_params = {"per_page": PAGE_SIZE, "sort": parent.sort}

        for resources in client.paginate(
            parent.path, params=parent_params, paginator=_list_paginator(), data_selector=parent.response_key
        ):
            for resource in resources:
                yielded = False
                try:
                    for page in client.paginate(
                        f"{parent.path}/{resource['id']}{config.path_suffix}",
                        params={"per_page": PAGE_SIZE, "sort": config.sort},
                        paginator=_list_paginator(),
                        data_selector=config.response_key,
                    ):
                        if page:
                            yielded = True
                            yield [{config.parent_id_column: resource["id"], **row} for row in page]
                except HTTPError as e:
                    # The resource was deleted after the parent list was read.
                    if e.response is None or e.response.status_code != 404:
                        raise
                if not yielded:
                    resumable_source_manager.safe_point()

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
    )


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """One cheap authenticated probe to confirm the token is genuine. Hetzner project tokens grant
    read access to every resource in the project (a read-only token still reads all of them), so
    there is no per-endpoint scope to check — a valid token can sync any table."""
    # redact_values masks the token in logged URLs / captured samples; allow_redirects=False keeps a
    # redirect from ever replaying the Authorization header to another host.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,), allow_redirects=False),
        f"{HETZNER_BASE_URL}/ssh_keys?per_page=1",
        headers={"Authorization": f"Bearer {api_token}", **_non_secret_headers()},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Hetzner Cloud API token"
    if status is None:
        return False, "Could not reach the Hetzner Cloud API"
    return False, f"Hetzner Cloud API returned HTTP {status}"
