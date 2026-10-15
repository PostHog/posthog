from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.triplewhale import (
    TripleWhaleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.triple_whale.settings import (
    API_ROOT,
    ENDPOINTS,
    MAX_PAGE,
    PAGE_SIZE,
    TripleWhaleEndpoint,
)


@frozen
class TripleWhaleResumeConfig:
    window_start: str
    end_time: str
    page: int = 1
    seen: int = 0


class OrdersPaginator(PageNumberPaginator):
    def __init__(self) -> None:
        super().__init__(base_page=1, param_location="json")
        self.seen = 0

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        body = response.json()
        if body.get("error"):
            raise ValueError("Triple Whale returned an attribution error. Check the shop and API key scopes.")
        total = body.get("totalForRange")
        if not isinstance(total, int) or total < 0:
            raise ValueError("Triple Whale returned an invalid order count.")
        self.seen += len(data or [])
        if self.seen >= total:
            self._has_next_page = False
            return
        if not data:
            raise ValueError("Triple Whale returned an empty page before all orders were read.")
        if self.page >= MAX_PAGE:
            raise ValueError("Triple Whale reached its order page limit. Use a later import start date.")
        super().update_state(response, data)

    def get_resume_state(self) -> dict[str, Any] | None:
        state = super().get_resume_state()
        return {**state, "seen": self.seen} if state is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        super().set_resume_state(state)
        self.seen = int(state.get("seen", 0))


def next_window(start: date, endpoint: TripleWhaleEndpoint) -> date:
    if endpoint.window == "day":
        return start + timedelta(days=1)
    return (start.replace(day=1) + timedelta(days=32)).replace(day=1)


def request_endpoint(
    endpoint: TripleWhaleEndpoint, shop: str, start: date, end_time: datetime, *, probe: bool = False
) -> Endpoint:
    body: dict[str, Any] = {endpoint.shop_field: shop}
    if endpoint.window == "month":
        end = min(
            datetime.combine(next_window(start, endpoint), datetime.min.time(), UTC) - timedelta(milliseconds=1),
            end_time,
        )
        body.update(
            startDate=datetime.combine(start, datetime.min.time(), UTC).isoformat(timespec="milliseconds"),
            endDate=end.isoformat(timespec="milliseconds"),
            pageSize=1 if probe else PAGE_SIZE,
            page=1,
            excludeJourneyData=probe,
        )
    else:
        body.update(
            period={"start": start.isoformat(), "end": start.isoformat()},
            todayHour=end_time.hour + 1 if start == end_time.date() else 25,
        )
    return {
        "path": endpoint.path,
        "method": "POST",
        "json": body,
        "data_selector": endpoint.data_selector,
        "data_selector_required": True,
        "paginator": OrdersPaginator() if endpoint.window == "month" else "single_page",
    }


def probe_credentials(config: TripleWhaleSourceConfig, api_version: str, schema_name: str | None = None) -> Response:
    with make_tracked_session() as session:
        headers = {"x-api-key": config.api_key, "Accept": "application/json"}
        base_url = f"{API_ROOT}/{api_version}/"
        if schema_name is None:
            return session.get(f"{base_url}users/api-keys/me", headers=headers, timeout=(5, 10))
        endpoint = schema_for_resource(ENDPOINTS, schema_name)
        now = datetime.now(UTC)
        request = request_endpoint(endpoint, config.shop, now.date(), now, probe=True)
        return session.post(f"{base_url}{endpoint.path}", headers=headers, json=request["json"], timeout=(5, 10))


def triple_whale_source(
    config: TripleWhaleSourceConfig,
    manager: ResumableSourceManager[TripleWhaleResumeConfig],
    inputs: SourceInputs,
    api_version: str,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    if inputs.should_use_incremental_field:
        raise ValueError("Triple Whale supports full refresh only. Change the table sync mode to full refresh.")
    initial = TripleWhaleResumeConfig(window_start=config.start_date, end_time=datetime.now(UTC).isoformat())
    if manager.can_resume() and (saved := manager.load_state()) is not None:
        initial = saved
    end_time = datetime.fromisoformat(initial.end_time)

    def pages() -> Iterator[list[dict[str, Any]]]:
        start = date.fromisoformat(initial.window_start)
        page = initial.page
        seen = initial.seen
        while start <= end_time.date():
            following = next_window(start, endpoint)

            def checkpoint(state: dict[str, Any] | None, start: date = start, following: date = following) -> None:
                manager.save_state(
                    TripleWhaleResumeConfig(
                        window_start=start.isoformat() if state else following.isoformat(),
                        end_time=initial.end_time,
                        page=int(state["page"]) if state else 1,
                        seen=int(state["seen"]) if state else 0,
                    )
                )

            rest_config: RESTAPIConfig = {
                "client": {
                    "base_url": f"{API_ROOT}/{api_version}/",
                    "auth": {"type": "api_key", "name": "x-api-key", "api_key": config.api_key, "location": "header"},
                    "request_timeout": (5, 30),
                    "retry_budget_seconds": 120,
                    "retry_after_max_seconds": 60,
                },
                "resources": [
                    {
                        "name": inputs.schema_name,
                        "write_disposition": "replace",
                        "endpoint": request_endpoint(endpoint, config.shop, start, end_time),
                    }
                ],
            }
            resource = rest_api_resource(
                rest_config,
                inputs.team_id,
                inputs.job_id,
                None,
                resume_hook=checkpoint,
                initial_paginator_state={"page": page, "seen": seen} if endpoint.window == "month" else None,
            )
            if endpoint.window == "day":

                def add_date(row: dict[str, Any], day: str = start.isoformat()) -> dict[str, Any]:
                    return {**row, "date": day}

                resource.add_map(add_date)
            yield from resource
            manager.safe_point()
            start, page, seen = following, 1, 0

    # This wrapper forwards each page without buffering, so framework checkpoints cover the yielded rows.
    resource = Resource(pages, name=inputs.schema_name, hints={})
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=[endpoint.partition_key],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
        partition_count=1,
        sort_mode=endpoint.sort_mode,
        on_complete=manager.clear_state,
    )
