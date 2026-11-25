import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Optional

import requests
from dateutil import parser

from products.warehouse_sources.sources.paddle.constants import (
    CUSTOMER_ADDRESS_RESOURCE_NAME,
    CUSTOMER_BUSINESS_RESOURCE_NAME,
    EXPLORE_METRICS_RESOURCE_NAME,
    SUBSCRIPTION_HISTORY_RESOURCE_NAME,
)
from products.warehouse_sources.sources.paddle.settings import (
    CREDENTIAL_CHECK_ENDPOINTS,
    ENDPOINT_PATHS,
    ENDPOINTS,
    FANOUT_ENDPOINTS,
    INCREMENTAL_FIELDS,
    MANAGED_SCHEMA_ENDPOINTS,
    PAGE_SIZE,
    PARTITION_KEYS,
)
from products.warehouse_sources.sources.sdk import (
    DEFAULT_RETRY,
    BearerTokenAuth,
    ClientConfig,
    JSONResponsePaginator,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    get_dlt_mapping_for_external_table,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)

PADDLE_BASE_URL = "https://api.paddle.com"

EXPLORE_ENTITIES_PATH = "metrics/explore/entities"
EXPLORE_QUERY_PATH = "metrics/explore"
EXPLORE_REQUEST_TIMEOUT = (10, 60)
EXPLORE_RETRY_BUDGET_SECONDS = 180
# Finest first. Each query covers one calendar month, so a weekly bucket would straddle two queries.
EXPLORE_INTERVALS = ("day", "month")

# A fan-out table check reads the child path of the first parent. With no parent, it reads the parent listing.
PROBE_PATHS = {
    EXPLORE_METRICS_RESOURCE_NAME: EXPLORE_ENTITIES_PATH,
    CUSTOMER_ADDRESS_RESOURCE_NAME: "customers",
    CUSTOMER_BUSINESS_RESOURCE_NAME: "customers",
    SUBSCRIPTION_HISTORY_RESOURCE_NAME: "subscriptions",
    **ENDPOINT_PATHS,
}
PROBE_TIMEOUT = 10.0


@dataclasses.dataclass(frozen=True)
class PaddleResumeConfig:
    # Self-contained next-page URL from Paddle's `meta.pagination.next`. Empty once the sync is done.
    next_url: str = ""
    # Explore metrics: the month window and the entity to query next.
    explore_window_start: str = ""
    explore_entity: str = ""
    # Fan-out tables: the state `build_dependent_resource` saves over the parent listing.
    fanout_state: Optional[dict[str, Any]] = None
    # Subscription history: the upper bound of the run, kept so a resumed attempt reads up to the same time.
    fanout_read_until: str = ""


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


def _save_fanout_state(
    manager: ResumableSourceManager[PaddleResumeConfig], state: Optional[dict[str, Any]], read_until: str
) -> None:
    if state:
        manager.save_state(PaddleResumeConfig(fanout_state=state, fanout_read_until=read_until))


def paddle_fanout_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PaddleResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    config = FANOUT_ENDPOINTS[endpoint]
    if config.fanout is None:
        raise ValueError(f"Paddle endpoint {endpoint} is not a fan-out endpoint")

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    child_params_extra: dict[str, Any] = {}
    read_until = ""
    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    if incremental_field_config:
        field_name = incremental_field_config[0]["field"]
        # The run reads one parent at a time, and the watermark is the largest value read anywhere. Without this cap,
        # an entry written to an already-read parent before a newer entry read later would fall below the watermark.
        read_until = (resume.fanout_read_until if resume else "") or _format_paddle_datetime_query_value(
            datetime.now(UTC)
        )
        child_params_extra[f"{field_name}[LTE]"] = read_until
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            # Paddle offers only [GTE] here. The rows on the watermark come back again, and the merge dedupes them.
            child_params_extra[f"{field_name}[GTE]"] = _format_paddle_datetime_query_value(
                db_incremental_field_last_value
            )

    client_config: ClientConfig = {
        "base_url": PADDLE_BASE_URL,
        "headers": {"Content-Type": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        "paginator": PaddlePaginator(next_url_path="meta.pagination.next"),
    }

    child = build_dependent_resource(
        endpoint_configs=FANOUT_ENDPOINTS,
        child_endpoint=endpoint,
        fanout=config.fanout,
        client_config=client_config,
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        page_size_param="per_page",
        child_params_extra=child_params_extra or None,
        parent_endpoint_extra={"data_selector": "data"},
        child_endpoint_extra={"data_selector": "data"},
        resume_hook=lambda state: _save_fanout_state(resumable_source_manager, state, read_until),
        initial_paginator_state=resume.fanout_state if resume else None,
        resume_parent_pagination=True,
    )

    return SourceResponse(
        items=lambda: child,
        primary_keys=config.primary_keys,
        name=endpoint,
        # Rows arrive one parent at a time, so they are not in one order.
        sort_mode=None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_count=1,
        partition_size=1,
        partition_format="month" if config.partition_key else None,
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
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown Paddle endpoint: {endpoint}")

    if endpoint == EXPLORE_METRICS_RESOURCE_NAME:
        return paddle_explore_metrics_source(
            api_key,
            resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
        )

    fanout_config = FANOUT_ENDPOINTS.get(endpoint)
    if fanout_config is not None and fanout_config.fanout is not None:
        return paddle_fanout_source(
            api_key,
            endpoint,
            team_id,
            job_id,
            resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
        )

    column_hints: Optional[dict[str, Any]] = None
    if endpoint in MANAGED_SCHEMA_ENDPOINTS:
        column_mapping = get_dlt_mapping_for_external_table(f"paddle_{endpoint.lower()}")
        column_hints = {key: value.get("data_type") for key, value in column_mapping.items()}

    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else None
    partition_key = incremental_field_name or PARTITION_KEYS.get(endpoint)

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
                    "path": ENDPOINT_PATHS.get(endpoint, endpoint),
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
        partition_keys=[partition_key] if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_count=1,
        partition_size=1,
        partition_format="week" if partition_key else None,
    )


def _first_parent_id(api_key: str, endpoint: str) -> Optional[str]:
    fanout = FANOUT_ENDPOINTS[endpoint].fanout
    if fanout is None:
        return None
    try:
        response = _get_paddle_session(api_key).get(
            f"{PADDLE_BASE_URL}/{FANOUT_ENDPOINTS[fanout.parent_name].path}",
            params={**fanout.parent_params, "per_page": 1},
            timeout=PROBE_TIMEOUT,
        )
        data = response.json().get("data") if response.status_code == 200 else None
    except Exception:
        # The parent probe that follows reports the failure.
        return None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict) or not data[0].get("id"):
        return None
    return str(data[0]["id"])


def _probe_url(api_key: str, endpoint: str) -> str:
    config = FANOUT_ENDPOINTS.get(endpoint)
    if config is not None and config.fanout is not None:
        # The child endpoints have their own permissions, so the parent listing alone does not prove access.
        parent_id = _first_parent_id(api_key, endpoint)
        if parent_id is not None:
            child_path = config.path.replace(f"{{{config.fanout.resolve_param}}}", parent_id)
            return f"{PADDLE_BASE_URL}/{child_path}?per_page=1"
    return f"{PADDLE_BASE_URL}/{PROBE_PATHS.get(endpoint, endpoint)}"


def validate_credentials(api_key: str, table_name: Optional[str] = None) -> bool:
    endpoints_to_check = [table_name] if table_name else CREDENTIAL_CHECK_ENDPOINTS

    for endpoint in endpoints_to_check:
        ok, status = validate_via_probe(
            lambda: _get_paddle_session(api_key),
            _probe_url(api_key, endpoint),
            timeout=PROBE_TIMEOUT,
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
