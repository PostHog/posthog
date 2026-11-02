from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import OAuth2Auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.trafficstars.settings import (
    CREATIVES_PAGE_SIZE,
    HISTORY_DAYS,
    TRAFFICSTARS_BASE_URL,
    TRAFFICSTARS_ENDPOINTS,
    TRAFFICSTARS_TOKEN_URL,
)

REQUEST_TIMEOUT = (10, 120)
# Setup waits on the probe, so each of its requests gets one short attempt.
PROBE_TIMEOUT = (10, 30)


@frozen
class TrafficStarsResumeConfig:
    next_page: int | None = None
    next_day: str | None = None


def _auth(api_key: str) -> OAuth2Auth:
    # TrafficStars hands out an offline token as the API key, and exchanges it like a refresh token.
    return OAuth2Auth(token_url=TRAFFICSTARS_TOKEN_URL, grant_type="refresh_token", refresh_token=api_key)


def to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _daily_statistics(
    client: RESTClient,
    path: str,
    data_selector: str,
    start: date,
    today: date,
    manager: ResumableSourceManager[TrafficStarsResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    day = start
    while day <= today:
        rows: list[dict[str, Any]] = []
        for page in client.paginate(
            path,
            method="post",
            # Both bounds are inclusive, so one day is a range from and to that day.
            json={
                "date_from": day.isoformat(),
                "date_to": day.isoformat(),
                "group_by": "campaign",
                "show_archived": True,
            },
            paginator=SinglePagePaginator(),
            data_selector=data_selector,
        ):
            rows.extend({**row, "date": day} for row in page)
        next_day = day + timedelta(days=1)
        if next_day <= today:
            manager.save_state(TrafficStarsResumeConfig(next_day=next_day.isoformat()))
        if rows:
            yield rows
        else:
            manager.safe_point()
        day = next_day


def trafficstars_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TrafficStarsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    history_start: Optional[datetime] = None,
) -> SourceResponse:
    config = TRAFFICSTARS_ENDPOINTS[endpoint]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    response_kwargs: dict[str, Any] = {
        "name": endpoint,
        "primary_keys": list(config.primary_keys),
        "partition_count": 1 if config.partition_key else None,
        "partition_size": 1 if config.partition_key else None,
        "partition_mode": "datetime" if config.partition_key else None,
        "partition_format": "month" if config.partition_key else None,
        "partition_keys": [config.partition_key] if config.partition_key else None,
    }

    if endpoint == "campaign_statistics_daily":
        today = datetime.now(UTC).date()
        if resume is not None and resume.next_day:
            start = date.fromisoformat(resume.next_day)
        elif should_use_incremental_field and db_incremental_field_last_value is not None:
            start = to_date(db_incremental_field_last_value)
        elif history_start is not None:
            start = history_start.date()
        else:
            start = today - timedelta(days=HISTORY_DAYS)
        client = RESTClient(base_url=TRAFFICSTARS_BASE_URL, auth=_auth(api_key), request_timeout=REQUEST_TIMEOUT)
        return SourceResponse(
            items=lambda: _daily_statistics(
                client, config.path, config.data_selector, start, today, resumable_source_manager
            ),
            # Days are requested in order, so rows arrive in date order.
            sort_mode="asc",
            **response_kwargs,
        )

    paginator: BasePaginator
    params: dict[str, Any] = {}
    if endpoint == "creatives":
        paginator = PageNumberPaginator(base_page=1, page_param="page", total_path="page_count")
        params["size"] = CREATIVES_PAGE_SIZE
    else:
        # The campaign list documents no paging and returns every campaign that is not archived.
        paginator = SinglePagePaginator()

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TRAFFICSTARS_BASE_URL,
            "auth": _auth(api_key),
            "paginator": paginator,
            "request_timeout": REQUEST_TIMEOUT,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "primary_key": list(config.primary_keys),
                "write_disposition": "replace",
                "endpoint": {"path": config.path, "params": params, "data_selector": config.data_selector},
                "table_format": "delta",
            }
        ],
    }

    def save_page(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page"):
            resumable_source_manager.save_state(TrafficStarsResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_page,
        initial_paginator_state={"page": resume.next_page} if resume is not None and resume.next_page else None,
    )
    return SourceResponse(items=lambda: resource, **response_kwargs)


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Exchange the API key for an access token, then read one creative to prove it reaches advertiser data."""
    could_not_connect = "Could not connect to TrafficStars. Try again in a minute."
    try:
        token_response = make_tracked_session(
            redact_values=(api_key,), capture=False, allow_redirects=False, retry=Retry(total=0)
        ).post(
            TRAFFICSTARS_TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": api_key},
            timeout=PROBE_TIMEOUT,
        )
        if token_response.status_code in (400, 401):
            return False, "TrafficStars rejected the API key. Copy it again from your TrafficStars profile."
        if token_response.status_code != 200:
            return False, could_not_connect
        access_token = str(token_response.json()["access_token"])
        # A publisher account's key passes the token exchange, and only the data endpoints refuse it.
        response = make_tracked_session(
            redact_values=(api_key, access_token), allow_redirects=False, retry=Retry(total=0)
        ).get(
            f"{TRAFFICSTARS_BASE_URL}{TRAFFICSTARS_ENDPOINTS['creatives'].path}",
            params={"page": 1, "size": 1},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=PROBE_TIMEOUT,
        )
    except Exception:  # noqa: BLE001 — a credential probe must never raise; any failure means "not validated"
        return False, could_not_connect
    if response.status_code == 200:
        return True, None
    if response.status_code == 403:
        return (
            False,
            "This TrafficStars account cannot read advertiser data. Use an API key from an advertiser account.",
        )
    return False, could_not_connect
