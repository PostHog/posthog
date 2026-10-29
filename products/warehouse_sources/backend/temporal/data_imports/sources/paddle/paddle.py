import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Optional

import requests
from dateutil import parser

from products.warehouse_sources.backend.models.external_table_definitions import get_dlt_mapping_for_external_table
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.constants import (
    EXPLORE_METRICS_RESOURCE_NAME,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.settings import (
    CREDENTIAL_CHECK_ENDPOINTS,
    INCREMENTAL_FIELDS,
)

PADDLE_BASE_URL = "https://api.paddle.com"
PAGE_SIZE = 200

EXPLORE_ENTITIES_PATH = "metrics/explore/entities"
EXPLORE_QUERY_PATH = "metrics/explore"
EXPLORE_REQUEST_TIMEOUT = (10, 60)
EXPLORE_RETRY_BUDGET_SECONDS = 180
# Finest first. Each query covers one calendar month, so a weekly bucket would straddle two queries.
EXPLORE_INTERVALS = ("day", "month")

PROBE_PATHS = {EXPLORE_METRICS_RESOURCE_NAME: EXPLORE_ENTITIES_PATH}


@dataclasses.dataclass(frozen=True)
class PaddleResumeConfig:
    # Self-contained next-page URL from Paddle's `meta.pagination.next`. Empty once the sync is done.
    next_url: str = ""
    # Explore metrics: the month window and the entity to query next.
    explore_window_start: str = ""
    explore_entity: str = ""


class PaddlePermissionError(Exception):
    pass


class PaddleUnreachableError(Exception):
    pass


class PaddlePaginator(JSONResponsePaginator):
    """Follows ``meta.pagination.next``, gated on ``meta.pagination.has_more``.

    Paddle populates ``next`` on every page, including the last one; per their
    pagination docs, ``has_more`` is the only end-of-results signal. Following
    ``next`` alone therefore refetches the final page forever.
    """

    def update_state(self, response: requests.Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = {}
        meta = body.get("meta") if isinstance(body, dict) else None
        pagination = meta.get("pagination") if isinstance(meta, dict) else None
        if isinstance(pagination, dict) and pagination.get("has_more") is False:
            self._has_next_page = False
            return
        # has_more missing or malformed: fall back to the next link, where the base
        # class still stops on a repeated URL.
        super().update_state(response, data)


def _format_paddle_datetime_query_value(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min, tzinfo=UTC)
    else:
        parsed = parser.isoparse(str(value))

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    else:
        parsed = parsed.astimezone(UTC)

    return parsed.isoformat().replace("+00:00", "Z")


def _get_paddle_session(api_key: str) -> requests.Session:
    # DEFAULT_RETRY backs off on 429/5xx (honoring Retry-After) but leaves auth/4xx
    # failures to surface immediately, so a transient rate-limit doesn't fail the sync.
    # The bearer token is set on the session and registered with redact_values so the
    # tracked transport scrubs it from logged URLs, headers, and captured samples.
    return make_tracked_session(
        retry=DEFAULT_RETRY,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        redact_values=(api_key,),
    )


def _explore_client(api_key: str) -> RESTClient:
    return RESTClient(
        base_url=PADDLE_BASE_URL,
        auth=BearerTokenAuth(token=api_key),
        request_timeout=EXPLORE_REQUEST_TIMEOUT,
        retry_budget_seconds=EXPLORE_RETRY_BUDGET_SECONDS,
        allowed_hosts=[],
        allow_redirects=False,
    )


def _explore_measures(entity: dict[str, Any]) -> list[dict[str, str]]:
    measures: list[dict[str, str]] = []
    for measure in entity.get("measures") or []:
        aggs = measure.get("aggs")
        if aggs is None:
            measures.append({"field": measure["name"]})
        else:
            measures.extend({"field": measure["name"], "agg": agg} for agg in aggs)
    return measures


def _next_month(day: date) -> date:
    return (day.replace(day=1) + timedelta(days=32)).replace(day=1)


def _explore_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    measures = {measure["name"]: measure for measure in (result.get("fields") or {}).get("measures") or []}
    rows: list[dict[str, Any]] = []
    for series in result.get("series") or []:
        for point in series.get("timeseries") or []:
            timestamp = _format_paddle_datetime_query_value(point["timestamp"])
            for name, value in (point.get("measures") or {}).items():
                measure = measures.get(name, {})
                rows.append(
                    {
                        "entity": result.get("entity"),
                        "interval": result.get("interval"),
                        "timestamp": timestamp,
                        "measure": name,
                        "field": measure.get("field"),
                        "agg": measure.get("agg"),
                        "value_type": measure.get("type"),
                        "value": None if value is None else str(value),
                        "currency_code": result.get("currency_code"),
                        "updated_at": result.get("updated_at"),
                    }
                )
    return rows


def _iter_explore_metrics(
    api_key: str,
    manager: ResumableSourceManager[PaddleResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
) -> Iterator[list[dict[str, Any]]]:
    client = _explore_client(api_key)
    try:
        catalog: list[dict[str, Any]] = []
        for page in client.paginate(path=EXPLORE_ENTITIES_PATH, data_selector="data", data_selector_required=True):
            catalog.extend(page)

        queries: list[tuple[str, str, list[dict[str, str]]]] = []
        lookback_days: list[int] = []
        for entity in sorted(catalog, key=lambda item: item["entity"]):
            time_dimension = entity.get("time_dimension") or {}
            interval = next((i for i in EXPLORE_INTERVALS if i in (time_dimension.get("intervals") or [])), None)
            measures = _explore_measures(entity)
            if interval is None or not measures:
                continue
            queries.append((entity["entity"], interval, measures))
            lookback_days.append(time_dimension["max_lookback_days"])
        if not queries:
            return

        today = datetime.now(UTC).date()
        # A day of margin keeps a query sent just after midnight UTC inside the lookback limit.
        earliest = today - timedelta(days=min(lookback_days) - 2)
        window = earliest if earliest.day == 1 else _next_month(earliest)
        if should_use_incremental_field and db_incremental_field_last_value:
            last_value = date.fromisoformat(_format_paddle_datetime_query_value(db_incremental_field_last_value)[:10])
            window = max(window, last_value.replace(day=1))

        resume_entity = ""
        resume = manager.load_state() if manager.can_resume() else None
        if resume is not None and resume.explore_window_start:
            window = date.fromisoformat(resume.explore_window_start)
            resume_entity = resume.explore_entity

        end = today + timedelta(days=1)
        while window < end:
            window_end = min(_next_month(window), end)
            for index, (entity_name, interval, measures) in enumerate(queries):
                if entity_name < resume_entity:
                    continue
                manager.safe_point()
                body = {
                    "entity": entity_name,
                    "from": window.isoformat(),
                    "to": window_end.isoformat(),
                    "interval": interval,
                    "measures": measures,
                }
                rows: list[dict[str, Any]] = []
                # With no breakdown dimension the result is a single series, so it fits on one page.
                for page in client.paginate(
                    path=EXPLORE_QUERY_PATH, method="POST", json=body, data_selector="data", data_selector_required=True
                ):
                    for result in page:
                        rows.extend(_explore_rows(result))

                next_entity = queries[index + 1][0] if index + 1 < len(queries) else ""
                next_window = window if next_entity else window_end
                manager.save_state(
                    PaddleResumeConfig(
                        explore_window_start=next_window.isoformat() if next_window < end else "",
                        explore_entity=next_entity,
                    )
                )
                if rows:
                    yield rows
                else:
                    manager.safe_point()
            resume_entity = ""
            window = window_end
    finally:
        client.session.close()


def paddle_explore_metrics_source(
    api_key: str,
    resumable_source_manager: ResumableSourceManager[PaddleResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    return SourceResponse(
        items=lambda: _iter_explore_metrics(
            api_key, resumable_source_manager, db_incremental_field_last_value, should_use_incremental_field
        ),
        primary_keys=["entity", "interval", "measure", "timestamp"],
        name=EXPLORE_METRICS_RESOURCE_NAME,
        # Rows restart at the window start for each entity. Every window is one calendar month, and the
        # next run starts at the month that holds the watermark, so it re-reads the whole window.
        sort_mode="asc",
        partition_keys=["timestamp"],
        partition_mode="datetime",
        partition_count=1,
        partition_size=1,
        partition_format="month",
    )


def paddle_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PaddleResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    if endpoint == EXPLORE_METRICS_RESOURCE_NAME:
        return paddle_explore_metrics_source(
            api_key,
            resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
        )

    column_mapping = get_dlt_mapping_for_external_table(f"paddle_{endpoint.lower()}")
    column_hints = {key: value.get("data_type") for key, value in column_mapping.items()}

    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else None

    params: dict[str, Any] = {"per_page": PAGE_SIZE}
    params["order_by"] = f"{incremental_field_name}[ASC]" if incremental_field_name else "id[ASC]"

    # Server-side incremental filter: Paddle supports a `<field>[GT]` query param, so only rows newer
    # than the last-synced watermark are returned. The paginator's self-contained `next` links carry
    # this filter forward, so it's set once on the first request.
    if should_use_incremental_field and incremental_field_name and db_incremental_field_last_value:
        params[f"{incremental_field_name}[GT]"] = _format_paddle_datetime_query_value(db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": PADDLE_BASE_URL,
            "headers": {"Content-Type": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": PaddlePaginator(next_url_path="meta.pagination.next"),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": endpoint,
                    "params": params,
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-yields the last page (merge dedupes) rather than
        # skipping it. Persist the self-contained next-page URL while pages remain, and an empty
        # marker once the last page is reached.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(PaddleResumeConfig(next_url=str(state["next_url"])))
        else:
            resumable_source_manager.save_state(PaddleResumeConfig(next_url=""))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        items=lambda: resource,
        primary_keys=["id"],
        name=endpoint,
        column_hints=column_hints,
        sort_mode="asc",
        partition_keys=[incremental_field_name] if incremental_field_name else None,
        partition_mode="datetime" if incremental_field_name else None,
        partition_count=1,
        partition_size=1,
        partition_format="week" if incremental_field_name else None,
    )


def validate_credentials(api_key: str, table_name: Optional[str] = None) -> bool:
    endpoints_to_check = [table_name] if table_name else CREDENTIAL_CHECK_ENDPOINTS

    for endpoint in endpoints_to_check:
        ok, status = validate_via_probe(
            lambda: _get_paddle_session(api_key),
            f"{PADDLE_BASE_URL}/{PROBE_PATHS.get(endpoint, endpoint)}",
        )
        if status == 403:
            raise PaddlePermissionError(f"Missing permissions for {endpoint}")
        if status is None:
            # validate_via_probe reports a missing status for any transport or session failure, so
            # Paddle never judged the key. That is not the same as Paddle rejecting it, and the
            # caller has to say so rather than tell the customer to replace a working key.
            raise PaddleUnreachableError(f"No response from Paddle for {endpoint}")
        if not ok:
            return False

    return True
