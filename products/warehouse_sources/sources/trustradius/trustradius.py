from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

from requests.exceptions import HTTPError
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.sources.sdk import (
    APIKeyAuth,
    OffsetPaginator,
    RESTAPIConfig,
    RESTClient,
    SinglePagePaginator,
    SourceResponse,
    reach_safe_point,
    rest_api_resource,
    schema_for_resource,
)
from products.warehouse_sources.sources.trustradius.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    INTENT_HISTORY_DAYS,
    PERMISSION_ERROR,
    PRODUCT_IDS_PER_REQUEST,
    REPORT_HISTORY_DAYS,
    REPORT_PAGE_SIZE,
    EndpointConfig,
)

REQUEST_TIMEOUT = (10, 60)


def _client(api_key: str) -> RESTClient:
    return RESTClient(
        base_url=BASE_URL,
        auth=APIKeyAuth(api_key=api_key, name="x-api-key", location="header"),
        headers={"Accept": "application/json"},
        paginator=SinglePagePaginator(),
        request_timeout=REQUEST_TIMEOUT,
        allow_redirects=False,
    )


def _watermark_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def _start_date(today: date, history_days: int, should_use_incremental_field: bool, last_value: Any) -> date:
    earliest = today - timedelta(days=history_days)
    watermark = _watermark_date(last_value) if should_use_incremental_field else None
    return max(earliest, watermark) if watermark else earliest


def _report_pages(
    client: RESTClient, settings: EndpointConfig, start: date, end: date
) -> Iterator[list[dict[str, Any]]]:
    params: dict[str, Any] = {
        "start-date": start.isoformat(),
        "end-date": end.isoformat(),
        "group": "day",
        "sort": settings["sort"],
        "format": "json",
    }
    batches: list[dict[str, Any]] = [params]
    if settings.get("requires_products"):
        product_ids = [
            row["_id"]
            for page in client.paginate("product-ids", data_selector="", data_selector_required=True)
            for row in page
        ]
        reach_safe_point()
        batches = [
            {**params, "products": ",".join(product_ids[index : index + PRODUCT_IDS_PER_REQUEST])}
            for index in range(0, len(product_ids), PRODUCT_IDS_PER_REQUEST)
        ]

    for batch_params in batches:
        paginator = OffsetPaginator(limit=REPORT_PAGE_SIZE, offset_param="skip", limit_param="limit", total_path=None)
        for page in client.paginate(
            settings["path"], params=batch_params, paginator=paginator, data_selector="", data_selector_required=True
        ):
            if page:
                yield page
            reach_safe_point()
            if len(page) < REPORT_PAGE_SIZE:
                break


def _intent_pages(
    client: RESTClient, start: date, end: date, logger: FilteringBoundLogger | None
) -> Iterator[list[dict[str, Any]]]:
    # The API returns `more` without a way to fetch the rest, so one day per request keeps each
    # response as small as possible.
    day = start
    while day < end:
        next_day = day + timedelta(days=1)
        params = {"start-date": day.isoformat(), "end-date": next_day.isoformat(), "detailed": "true"}
        # Without a data selector the client hands back the whole object body as a one-item page.
        for page in client.paginate("intent", params=params, data_selector=None):
            body = page[0] if len(page) == 1 and isinstance(page[0], dict) else {}
            accounts = body.get("accounts")
            if not isinstance(accounts, list):
                raise ValueError("TrustRadius intent response has no accounts list.")
            if body.get("more") and logger is not None:
                logger.warning("TrustRadius intent data for one day is incomplete", day=day.isoformat())
            if accounts:
                yield [{**account, "date": day.isoformat()} for account in accounts]
        reach_safe_point()
        day = next_day


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    client = _client(api_key)
    try:
        next(client.paginate("product-ids", data_selector="", data_selector_required=True), None)
    except HTTPError as error:
        if error.response is not None:
            if error.response.status_code == 401:
                return False, AUTH_ERROR
            if error.response.status_code == 403:
                return False, PERMISSION_ERROR
        raise
    return True, None


def trustradius_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    last_value: Any = None,
    logger: FilteringBoundLogger | None = None,
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    partition_key = settings["partition_key"]
    partitioning: dict[str, Any] = {
        "partition_keys": [partition_key] if partition_key else None,
        "partition_mode": "datetime" if partition_key else None,
        "partition_format": "month" if partition_key else None,
    }

    if endpoint == "intent" or settings.get("report"):
        today = datetime.now(UTC).date()

        def items() -> Iterator[list[dict[str, Any]]]:
            client = _client(api_key)
            if endpoint == "intent":
                # The last full day is yesterday, and the end date is exclusive.
                start = _start_date(today, INTENT_HISTORY_DAYS, should_use_incremental_field, last_value)
                yield from _intent_pages(client, start, today, logger)
            else:
                start = _start_date(today, REPORT_HISTORY_DAYS, should_use_incremental_field, last_value)
                yield from _report_pages(client, settings, start, today)

        return SourceResponse(
            name=endpoint,
            items=items,
            primary_keys=settings["primary_keys"],
            sort_mode=None,
            supports_resume=False,
            **partitioning,
        )

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "api_key": api_key, "name": "x-api-key", "location": "header"},
            "paginator": "single_page",
            "headers": {"Accept": "application/json"},
            "request_timeout": REQUEST_TIMEOUT,
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "table_format": "delta",
                "write_disposition": "replace",
                "endpoint": {
                    "path": settings["path"],
                    "data_selector": settings["data_selector"],
                    "data_selector_required": True,
                    "params": {"include-anonymous": "true"} if endpoint == "trustquotes" else {},
                },
            }
        ],
    }
    resource = rest_api_resource(config, team_id, job_id, None)
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=settings["primary_keys"],
        column_hints=resource.column_hints,
        sort_mode=None,
        supports_resume=False,
        **partitioning,
    )
