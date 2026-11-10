from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from requests import HTTPError

from products.warehouse_sources.sources.scrunch.settings import (
    AGENT_TRAFFIC_DIMENSIONS,
    AGENT_TRAFFIC_HISTORY_DAYS,
    AGENT_TRAFFIC_PAGE_SIZE,
    BASE_URL,
    ENDPOINTS,
    FANOUT_PARENTS,
    INCREMENTAL_FIELDS,
    NON_RETRYABLE_ERRORS,
    PAGE_SIZE,
    PRIMARY_KEYS,
    SIGNAL_ANCHOR_LIMIT,
    SITEMAP_METRICS,
    FanoutParent,
)
from products.warehouse_sources.sources.sdk import (
    BearerTokenAuth,
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceInputs,
    SourceResponse,
    frozen,
    make_parent_key_name,
    parse_datetime_value,
    rename_parent_fields,
    rest_api_resources,
    schema_for_resource,
)


@frozen
class ScrunchResumeConfig:
    paginator_state: dict[str, Any] | None
    start_date: str | None
    end_date: str | None
    complete: bool = False


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    client = RESTClient(
        base_url=BASE_URL,
        auth=BearerTokenAuth(api_key),
        request_timeout=60,
        allowed_hosts=[],
        allow_redirects=False,
    )
    try:
        next(
            client.paginate(
                "brands",
                params={"limit": 1},
                paginator=SinglePagePaginator(),
                data_selector="items",
                data_selector_required=True,
            )
        )
    except HTTPError as error:
        for pattern, message in NON_RETRYABLE_ERRORS.items():
            if pattern in str(error):
                return False, message
        raise
    return True, None


def _watermark_date(inputs: SourceInputs) -> str | None:
    if not inputs.should_use_incremental_field or inputs.db_incremental_field_last_value is None:
        return None
    watermark = parse_datetime_value(inputs.db_incremental_field_last_value)
    if watermark is None:
        raise ValueError(f"Invalid Scrunch {inputs.schema_name} watermark. Reset this table's sync.")
    # Date filters include the whole watermark day; merging prevents duplicate rows.
    return watermark.date().isoformat()


@frozen
class _DateWindow:
    start_date: str | None
    end_date: str | None


def _date_window(inputs: SourceInputs) -> _DateWindow:
    today = datetime.now(UTC).date()
    start_date = _watermark_date(inputs) if inputs.schema_name in INCREMENTAL_FIELDS else None
    if inputs.schema_name == "responses":
        # Exclude the open UTC day so new responses cannot move offsets during a sync.
        return _DateWindow(start_date=start_date, end_date=today.isoformat())
    if inputs.schema_name == "agent_traffic":
        if start_date is None:
            history_start = (
                inputs.history_start.date()
                if inputs.history_start
                else today - timedelta(days=AGENT_TRAFFIC_HISTORY_DAYS)
            )
            start_date = history_start.isoformat()
        return _DateWindow(start_date=start_date, end_date=today.isoformat())
    return _DateWindow(start_date=start_date, end_date=None)


BRAND_KEY = make_parent_key_name("brands", "id")


def _explode_page_metrics(row: dict[str, Any]) -> list[dict[str, Any]]:
    page = {
        "brand_id": row[make_parent_key_name("sitemap_pages", BRAND_KEY)],
        "page_id": row[make_parent_key_name("sitemap_pages", "id")],
        "page_url": row[make_parent_key_name("sitemap_pages", "url")],
        "granularity": row.get("granularity"),
    }
    metrics = row.get("metrics") or {}
    return [
        {**page, "metric": metric, "date": bucket["date"], "platform": platform, "count": count}
        for metric in SITEMAP_METRICS
        for bucket in metrics.get(metric) or []
        for platform, count in (bucket.get("count_by_platform") or {}).items()
    ]


def _detection_days(start_date: str | None, row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"date": day, BRAND_KEY: row[BRAND_KEY]}
        for day in row.get("dates") or []
        if start_date is None or day >= start_date
    ]


def _middle_resource(parent: FanoutParent, window: _DateWindow) -> EndpointResource:
    params: dict[str, Any] = {"brand_id": {"type": "resolve", "resource": "brands", "field": "id"}}
    endpoint: Endpoint = {"path": parent.path, "params": params}
    middle: EndpointResource = {"name": parent.name, "include_from_parent": ["id"], "endpoint": endpoint}
    if parent.name == "sites":
        # The sites list takes no paging params and returns every site at once.
        endpoint["paginator"] = "single_page"
        # Other sites of the brand return 404 on the agent traffic route.
        middle["data_map"] = lambda site: site if site.get("agent_traffic_active") else []
    elif parent.name == "sitemap_pages":
        # A brand without a completed sitemap crawl answers 404.
        endpoint["response_actions"] = [{"status_code": 404, "action": "ignore"}]
    else:
        params["limit"] = SIGNAL_ANCHOR_LIMIT
        endpoint |= {"paginator": "single_page", "data_selector": None, "data_selector_required": False}
        middle["data_map"] = partial(_detection_days, window.start_date)
    return middle


def _child_endpoint(schema_name: str, path: str, window: _DateWindow) -> Endpoint:
    parent = FANOUT_PARENTS.get(schema_name)
    params: dict[str, Any] = {"brand_id": {"type": "resolve", "resource": "brands", "field": "id"}}
    if parent is not None:
        params = {
            "brand_id": {"type": "resolve", "resource": parent.name, "field": BRAND_KEY},
            parent.param: {"type": "resolve", "resource": parent.name, "field": parent.field},
        }
    endpoint: Endpoint = {"path": path, "params": params}
    if schema_name == "prompts":
        params["status"] = "all"
    elif schema_name == "responses":
        params["end_date"] = window.end_date
        if window.start_date is not None:
            params["start_date"] = window.start_date
    elif schema_name == "signals":
        params["sort"] = "detected_desc"
        # A path that ends in a placeholder defaults to a single page.
        endpoint["paginator"] = {"type": "offset", "limit": PAGE_SIZE, "total_path": "total"}
    elif schema_name == "agent_traffic":
        params |= {
            "start_date": window.start_date,
            "end_date": window.end_date,
            "fields": ",".join(AGENT_TRAFFIC_DIMENSIONS),
            "time_bucket": "day",
        }
        # The response carries no total, so a short page ends the walk.
        endpoint["paginator"] = {"type": "offset", "limit": AGENT_TRAFFIC_PAGE_SIZE, "total_path": None}
        endpoint["data_selector"] = "data"
    elif schema_name in ("site_audit_score", "sitemap_page_metrics"):
        # One object per request; the site score is null for a brand with no audit yet.
        endpoint |= {"paginator": "single_page", "data_selector": None, "data_selector_required": False}
    return endpoint


def _child_resources(schema_name: str, path: str, window: _DateWindow) -> list[EndpointResource]:
    endpoint = _child_endpoint(schema_name, path, window)
    parent = FANOUT_PARENTS.get(schema_name)
    if parent is None:
        return [
            {
                "name": schema_name,
                "include_from_parent": ["id"],
                "endpoint": endpoint,
                "data_map": rename_parent_fields("brands", {"id": "brand_id"}),
            }
        ]

    child: EndpointResource = {"name": schema_name, "endpoint": endpoint}
    if schema_name == "agent_traffic":
        child["include_from_parent"] = ["id", BRAND_KEY]
        child["data_map"] = rename_parent_fields(parent.name, {"id": "site_id", BRAND_KEY: "brand_id"})
    elif schema_name == "sitemap_page_metrics":
        child["include_from_parent"] = ["id", "url", BRAND_KEY]
        child["data_map"] = _explode_page_metrics
    else:
        child["include_from_parent"] = [BRAND_KEY]
        child["data_map"] = rename_parent_fields(parent.name, {BRAND_KEY: "brand_id"})
    return [_middle_resource(parent, window), child]


def scrunch_source(
    api_key: str,
    inputs: SourceInputs,
    manager: ResumableSourceManager[ScrunchResumeConfig],
) -> SourceResponse:
    schema_name = inputs.schema_name
    path = schema_for_resource(ENDPOINTS, schema_name)
    is_responses = schema_name == "responses"
    is_partitioned = schema_name in ("responses", "signals")
    resume = manager.load_state() if manager.can_resume() else None
    window = (
        _DateWindow(start_date=resume.start_date, end_date=resume.end_date)
        if resume is not None
        else _date_window(inputs)
    )

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        manager.save_state(
            ScrunchResumeConfig(
                paginator_state=state,
                start_date=window.start_date,
                end_date=window.end_date,
                complete=state is None,
            )
        )

    parent: EndpointResource = {"name": "brands", "endpoint": {"path": ENDPOINTS["brands"]}}
    resources: list[str | EndpointResource] = [parent]
    if schema_name != "brands":
        resources.extend(_child_resources(schema_name, path, window))

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": api_key},
            "paginator": {"type": "offset", "limit": PAGE_SIZE, "total_path": "total"},
            "request_timeout": 60,
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resource_defaults": {"endpoint": {"data_selector": "items", "data_selector_required": True}},
        "resources": resources,
    }
    resource = next(
        resource
        for resource in rest_api_resources(
            config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        )
        if resource.name == schema_name
    )
    return SourceResponse(
        name=schema_name,
        items=(lambda: []) if resume and resume.complete else (lambda: resource),
        primary_keys=PRIMARY_KEYS[schema_name],
        sort_mode="desc" if is_responses else None,
        partition_keys=["created_at"] if is_partitioned else None,
        partition_mode="datetime" if is_partitioned else None,
        partition_format="month" if is_partitioned else None,
    )
