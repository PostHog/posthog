from collections.abc import Callable, Iterable, Iterator
from datetime import date
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.settings import (
    HOORAYHR_BASE_URL,
    HOORAYHR_ENDPOINTS,
    PUBLIC_HOLIDAYS_YEARS_AHEAD,
    PUBLIC_HOLIDAYS_YEARS_BACK,
)


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": HOORAYHR_BASE_URL,
        "headers": {"Accept": "application/json"},
        # Both personal API keys (pk_ prefixed) and partner OAuth access tokens are sent as
        # `Authorization: Bearer <token>`.
        "auth": {"type": "bearer", "token": api_key},
        # No pagination is documented on any list endpoint — each table is a single bare-array
        # page, full refresh only.
        "paginator": "single_page",
        "request_timeout": (10.0, 60.0),
        # Responses carry employee records and leave balances the generic sample scrubbers don't target.
        "capture": False,
    }


def _public_holiday_pages(api_key: str, team_id: int, job_id: str, today: date) -> Iterator[list[dict[str, Any]]]:
    path = HOORAYHR_ENDPOINTS["public_holidays"].path
    for year in range(today.year - PUBLIC_HOLIDAYS_YEARS_BACK, today.year + PUBLIC_HOLIDAYS_YEARS_AHEAD + 1):
        rest_config: RESTAPIConfig = {
            "client": _client_config(api_key),
            "resource_defaults": None,
            "resources": [
                {
                    "name": "public_holidays",
                    "endpoint": {
                        "path": path,
                        "params": {"date[$gte]": f"{year}-01-01", "date[$lte]": f"{year}-12-31"},
                    },
                }
            ],
        }
        merged: dict[tuple[Any, Any], dict[str, Any]] = {}
        for page in rest_api_resource(rest_config, team_id, job_id, None):
            for row in page:
                user_ids = row.get("userIds") or []
                existing = merged.get((row["id"], row["date"]))
                if existing is None:
                    merged[(row["id"], row["date"])] = {**row, "userIds": list(dict.fromkeys(user_ids))}
                else:
                    existing["userIds"] = list(dict.fromkeys([*existing["userIds"], *user_ids]))
        if merged:
            yield list(merged.values())


def hoorayhr_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = HOORAYHR_ENDPOINTS[endpoint]

    items: Callable[[], Iterable[Any]]
    if endpoint == "public_holidays":
        items = lambda: _public_holiday_pages(api_key, team_id, job_id, date.today())
    else:
        rest_config: RESTAPIConfig = {
            "client": _client_config(api_key),
            "resource_defaults": None,
            "resources": [{"name": endpoint, "endpoint": {"path": config.path}}],
        }
        resource = rest_api_resource(rest_config, team_id, job_id, None)
        items = lambda: resource

    has_partition_key = config.partition_key is not None
    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        # Month is the coarsest datetime tier; the auto-repartitioner only steps finer, so this
        # gives it the most headroom. Endpoints without a stable creation field stay unpartitioned.
        partition_mode="datetime" if has_partition_key else None,
        partition_format="month" if has_partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    # /leave-types is the cheapest authenticated read: a handful of rows per company. The probe runs
    # before the source is saved, so `redact_values` masks the API key in tracked telemetry here too.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{HOORAYHR_BASE_URL}{HOORAYHR_ENDPOINTS['leave_types'].path}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=15,
    )
    return ok
