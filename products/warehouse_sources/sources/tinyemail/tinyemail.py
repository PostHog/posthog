from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast

from requests.exceptions import RequestException

from products.warehouse_sources.sources.sdk import (
    APIKeyAuth,
    BasePaginator,
    ClientConfig,
    Endpoint,
    EndpointResource,
    PageNumberPaginator,
    RESTAPIConfig,
    RESTClient,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    reach_safe_point,
    rest_api_resource,
)
from products.warehouse_sources.sources.tinyemail.settings import (
    NEW_SUBSCRIBER_ENGAGEMENT_HISTORY_DAYS,
    NEW_SUBSCRIBER_ENGAGEMENT_WINDOW_DAYS,
    TINYEMAIL_BASE_URL,
    TINYEMAIL_ENDPOINTS,
    TinyemailEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 30

ENGAGEMENT_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

INVALID_CREDENTIALS_MESSAGE = (
    "Invalid tinyEmail API key. Generate a new key in tinyEmail under My account > API keys and reconnect. "
    "Note that tinyEmail API access requires an Enterprise plan."
)


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": TINYEMAIL_BASE_URL,
        "auth": {"type": "api_key", "name": "X-API-KEY", "api_key": api_key, "location": "header"},
        "headers": {"Accept": "application/json"},
        # The API responds directly on a fixed host, and `requests` would replay the
        # X-API-KEY header across a cross-host redirect — so never follow one.
        "allow_redirects": False,
    }


def _paginator(config: TinyemailEndpointConfig) -> BasePaginator:
    if not config.paginated:
        return SinglePagePaginator()
    return PageNumberPaginator(base_page=config.base_page, page_param="page")


def get_resource(endpoint: str) -> EndpointResource:
    config = TINYEMAIL_ENDPOINTS[endpoint]
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": {"size": config.page_size} if config.paginated else {},
        "data_selector": config.data_selector,
        "paginator": _paginator(config),
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _rest_client(api_key: str) -> RESTClient:
    return RESTClient(
        base_url=TINYEMAIL_BASE_URL,
        auth=APIKeyAuth(api_key=api_key, name="X-API-KEY", location="header"),
        headers={"Accept": "application/json"},
        allow_redirects=False,
    )


def _list_rows(client: RESTClient, endpoint: str) -> Iterator[dict[str, Any]]:
    config = TINYEMAIL_ENDPOINTS[endpoint]
    for page in client.paginate(
        path=config.path,
        params={"size": config.page_size} if config.paginated else {},
        paginator=_paginator(config),
        data_selector=config.data_selector,
    ):
        yield from page


def _campaign_domain_stats_rows(client: RESTClient) -> Iterator[list[dict[str, Any]]]:
    config = TINYEMAIL_ENDPOINTS["campaign_domain_stats"]
    for campaign in _list_rows(client, "campaigns"):
        campaign_id = campaign["id"]
        # The docs return a paged body but list no page params for this POST. If the API ignores
        # `page`, every page repeats the first, so stop at the first page with no new domain.
        seen_domains: set[Any] = set()
        for page in client.paginate(
            path=config.path,
            method=config.method,
            params={"size": config.page_size},
            json={"campaignId": campaign_id},
            paginator=PageNumberPaginator(base_page=config.base_page, page_param="page", total_path="totalPages"),
            data_selector=config.data_selector,
        ):
            rows = [{**row, "campaign_id": campaign_id} for row in page if row.get("domainName") not in seen_domains]
            if page and not rows:
                break
            seen_domains.update(row.get("domainName") for row in rows)
            if rows:
                yield rows
            reach_safe_point()
        reach_safe_point()


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def engagement_windows(should_use_incremental_field: bool, last_value: Any, now: datetime) -> list[tuple[str, str]]:
    if should_use_incremental_field and last_value:
        start = _as_date(last_value)
    else:
        start = now.date() - timedelta(days=NEW_SUBSCRIBER_ENGAGEMENT_HISTORY_DAYS - 1)

    windows = []
    window_start = datetime.combine(start, time.min, tzinfo=UTC)
    while window_start <= now:
        # The range may not exceed 7 days, so each window ends one second before the next starts.
        window_end = min(window_start + timedelta(days=NEW_SUBSCRIBER_ENGAGEMENT_WINDOW_DAYS, seconds=-1), now)
        windows.append(
            (window_start.strftime(ENGAGEMENT_DATETIME_FORMAT), window_end.strftime(ENGAGEMENT_DATETIME_FORMAT))
        )
        window_start += timedelta(days=NEW_SUBSCRIBER_ENGAGEMENT_WINDOW_DAYS)
    return windows


def _new_subscriber_engagement_rows(
    client: RESTClient, windows: list[tuple[str, str]]
) -> Iterator[list[dict[str, Any]]]:
    config = TINYEMAIL_ENDPOINTS["new_subscriber_engagement"]
    for audience in _list_rows(client, "contacts"):
        audience_id = audience["id"]
        for window_from, window_to in windows:
            # Rows name the audience but carry no id, so each request asks for one audience.
            for page in client.paginate(
                path=config.path,
                method=config.method,
                json={"from": window_from, "to": window_to, "audienceIds": [audience_id]},
                paginator=SinglePagePaginator(),
                data_selector=config.data_selector,
            ):
                if page:
                    yield [{**row, "audience_id": audience_id} for row in page]
            reach_safe_point()


def _make_source_response(
    endpoint_config: TinyemailEndpointConfig, items_fn: Callable[[], Iterable[Any]]
) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_key
        if isinstance(endpoint_config.primary_key, list)
        else [endpoint_config.primary_key],
    )


def tinyemail_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    endpoint_config = TINYEMAIL_ENDPOINTS[endpoint]

    if endpoint == "campaign_domain_stats":
        return _make_source_response(endpoint_config, lambda: _campaign_domain_stats_rows(_rest_client(api_key)))

    if endpoint == "new_subscriber_engagement":
        windows = engagement_windows(should_use_incremental_field, db_incremental_field_last_value, datetime.now(UTC))
        return _make_source_response(
            endpoint_config, lambda: _new_subscriber_engagement_rows(_rest_client(api_key), windows)
        )

    if endpoint_config.fanout:
        parent_config = TINYEMAIL_ENDPOINTS[endpoint_config.fanout.parent_name]
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=TINYEMAIL_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=endpoint_config.fanout,
                client_config=_client_config(api_key),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                page_size_param="size" if endpoint_config.paginated else None,
                parent_endpoint_extra={
                    "paginator": _paginator(parent_config),
                    "data_selector": parent_config.data_selector,
                },
                child_endpoint_extra={
                    "method": endpoint_config.method,
                    "paginator": _paginator(endpoint_config),
                    "data_selector": endpoint_config.data_selector,
                },
            ),
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(endpoint)],
    }

    resource = rest_api_resource(config, team_id, job_id, None)
    return _make_source_response(endpoint_config, lambda: resource)


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    try:
        response = session.get(
            f"{TINYEMAIL_BASE_URL}/contacts",
            headers={"X-API-KEY": api_key, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except RequestException as exc:
        return False, f"Could not connect to the tinyEmail API: {exc}"

    if response.status_code == 200:
        return True, None
    # tinyEmail has no per-endpoint scopes, so both 401 and 403 mean the key itself is unusable.
    if response.status_code in (401, 403):
        return False, INVALID_CREDENTIALS_MESSAGE
    return False, f"tinyEmail API returned an unexpected status code {response.status_code}"
