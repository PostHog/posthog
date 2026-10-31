from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import PaginatorConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xsolla import XsollaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xsolla.settings import (
    API_BASE_URL,
    AUTH_ERROR,
    ENDPOINTS,
    HISTORY_START,
    NOT_FOUND_IGNORED_RESPONSE_ACTIONS,
    PAGE_SIZE,
    RESPONSE_ACTIONS,
    STORE_PAGE_SIZE,
    TRANSACTIONS_LOOKBACK_DAYS,
    XsollaEndpoint,
)

MERCHANT_ID_ERROR = "Enter the merchant ID as a number. You can find it in Publisher Account under Company settings."


@frozen
class XsollaResumeConfig:
    window_start: str | None = None
    project_id: int | None = None
    offset: int = 0
    promotion_id: int | None = None


def parse_merchant_id(merchant_id: str) -> str:
    merchant_id = merchant_id.strip()
    if not merchant_id.isascii() or not merchant_id.isdigit():
        raise ValueError(MERCHANT_ID_ERROR)
    return merchant_id


def validate_credentials(config: XsollaSourceConfig, api_version: str) -> tuple[bool, str | None]:
    try:
        merchant_id = parse_merchant_id(config.merchant_id)
    except ValueError as error:
        return False, str(error)

    session = make_tracked_session(redact_values=(config.api_key,))
    response = session.get(
        f"{API_BASE_URL}/{api_version}/merchants/{merchant_id}/projects",
        auth=(merchant_id, config.api_key),
        timeout=30,
    )
    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, AUTH_ERROR
    return False, f"Xsolla returned an unexpected response (HTTP {response.status_code}). Try again later."


def _rest_config(
    config: XsollaSourceConfig,
    merchant_id: str,
    name: str,
    endpoint: XsollaEndpoint,
    path: str,
    params: dict[str, Any],
    api_version: str,
    data_map: Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> RESTAPIConfig:
    paginator: PaginatorConfig = "single_page"
    if endpoint.store:
        paginator = {"type": "offset", "limit": STORE_PAGE_SIZE, "total_path": "total_items_count"}
    elif endpoint.paginated:
        paginator = {"type": "offset", "limit": PAGE_SIZE, "total_path": None}
    return {
        "client": {
            "base_url": endpoint.base_url or f"{API_BASE_URL}/{api_version}/",
            "auth": {"type": "http_basic", "username": merchant_id, "password": config.api_key},
            "paginator": paginator,
        },
        "resources": [
            {
                "name": name,
                "table_name": name,
                "endpoint": {
                    "path": path,
                    "params": params,
                    "response_actions": NOT_FOUND_IGNORED_RESPONSE_ACTIONS
                    if endpoint.ignore_not_found
                    else RESPONSE_ACTIONS,
                    # The projects list shape is not documented, so only the documented list endpoints fail loud.
                    "data_selector_required": endpoint.list_response and name != "projects",
                    **({"data_selector": "items"} if endpoint.store else {}),
                },
                "table_format": "delta",
                "data_map": data_map,
            }
        ],
    }


def _row_mapper(
    endpoint: XsollaEndpoint, extra_fields: dict[str, Any]
) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    if not endpoint.lifted_fields and not extra_fields:
        return None

    def map_row(row: dict[str, Any]) -> dict[str, Any]:
        for target, parent, child in endpoint.lifted_fields:
            nested = row.get(parent)
            row[target] = nested.get(child) if isinstance(nested, dict) else None
        row.update(extra_fields)
        return row

    return map_row


def _watermark_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def _window_params(name: str, window_start: date, window_end: date) -> dict[str, str]:
    if name == "transactions":
        # Transaction search accepts ISO 8601 date-times, so adjacent windows never overlap.
        return {
            "datetime_from": f"{window_start.isoformat()}T00:00:00Z",
            "datetime_to": f"{window_end.isoformat()}T23:59:59Z",
            "type": "all",
        }
    # Report endpoints accept YYYY-MM-DD only.
    params = {"datetime_from": window_start.isoformat(), "datetime_to": window_end.isoformat()}
    if name == "transaction_registry":
        # Required by the registry. 0 keeps amounts in the payment currency, as Xsolla does by default.
        params["in_transfer_currency"] = "0"
    return params


def _window_end(endpoint: XsollaEndpoint, window_start: date, today: date) -> date:
    if endpoint.monthly_windows:
        next_month = (window_start.replace(day=1) + timedelta(days=32)).replace(day=1)
        return min(next_month - timedelta(days=1), today)
    assert endpoint.window_days is not None
    return min(window_start + timedelta(days=endpoint.window_days - 1), today)


def _parent_state(scope: str, parent_id: int, offset: int = 0) -> XsollaResumeConfig:
    if scope == "promotion":
        return XsollaResumeConfig(promotion_id=parent_id, offset=offset)
    return XsollaResumeConfig(project_id=parent_id, offset=offset)


def list_parent_ids(
    config: XsollaSourceConfig, merchant_id: str, parent: str, team_id: int, job_id: str, api_version: str
) -> list[int]:
    endpoint = ENDPOINTS[parent]
    resource = rest_api_resource(
        _rest_config(
            config,
            merchant_id,
            parent,
            endpoint,
            endpoint.path.format(merchant_id=merchant_id),
            {},
            api_version,
            None,
        ),
        team_id,
        job_id,
        None,
    )
    return sorted({int(row["id"]) for page in resource for row in page if row.get("id") is not None})


def xsolla_source(
    config: XsollaSourceConfig,
    endpoint_name: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[XsollaResumeConfig],
    api_version: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    endpoint = ENDPOINTS.get(endpoint_name)
    if endpoint is None:
        raise ValueError(f"Unknown Xsolla table: {endpoint_name}. Select a table from the source configuration.")
    merchant_id = parse_merchant_id(config.merchant_id)

    start = HISTORY_START
    watermark = _watermark_date(db_incremental_field_last_value) if should_use_incremental_field else None
    if watermark is not None:
        start = max(start, watermark - timedelta(days=TRANSACTIONS_LOOKBACK_DAYS))

    def read(
        path: str,
        params: dict[str, Any],
        extra_fields: dict[str, Any],
        offset: int,
        save: Callable[[int | None], None],
    ) -> Iterator[list[dict[str, Any]]]:
        def resume_hook(paginator_state: dict[str, Any] | None) -> None:
            save(int(paginator_state["offset"]) if paginator_state else None)
            manager.safe_point()

        yield from rest_api_resource(
            _rest_config(
                config,
                merchant_id,
                endpoint_name,
                endpoint,
                path,
                params,
                api_version,
                _row_mapper(endpoint, extra_fields),
            ),
            team_id,
            job_id,
            None,
            resume_hook=resume_hook,
            initial_paginator_state={"offset": offset} if endpoint.paginated else None,
        )

    def windowed_items(state: XsollaResumeConfig) -> Iterator[list[dict[str, Any]]]:
        path = endpoint.path.format(merchant_id=merchant_id)
        today = datetime.now(UTC).date()
        window_start = date.fromisoformat(state.window_start) if state.window_start else start
        offset = state.offset
        # Report windows can return the same payout or report twice, and these tables stay small.
        seen: set[tuple[Any, ...]] = set()

        while window_start <= today:
            window_end = _window_end(endpoint, window_start, today)
            next_start = window_end + timedelta(days=1)

            def save(next_offset: int | None, current: date = window_start, following: date = next_start) -> None:
                if next_offset is None:
                    manager.save_state(XsollaResumeConfig(window_start=following.isoformat()))
                else:
                    manager.save_state(XsollaResumeConfig(window_start=current.isoformat(), offset=next_offset))

            period = (
                {"period_start": window_start.isoformat(), "period_end": window_end.isoformat()}
                if endpoint.monthly_windows
                else {}
            )
            for page in read(path, _window_params(endpoint_name, window_start, window_end), period, offset, save):
                if endpoint.paginated:
                    yield page
                    continue
                rows = []
                for row in page:
                    key = tuple(row.get(field) for field in endpoint.primary_keys)
                    if None in key or key not in seen:
                        seen.add(key)
                        rows.append(row)
                if rows:
                    yield rows

            window_start = next_start
            offset = 0

    def parent_items(state: XsollaResumeConfig) -> Iterator[list[dict[str, Any]]]:
        parent_key = f"{endpoint.scope}_id"
        resume_id = state.promotion_id if endpoint.scope == "promotion" else state.project_id
        parent_ids = list_parent_ids(config, merchant_id, f"{endpoint.scope}s", team_id, job_id, api_version)
        for parent_id in parent_ids:
            if resume_id is not None and parent_id < resume_id:
                continue
            offset = state.offset if parent_id == resume_id else 0

            def save(next_offset: int | None, current: int = parent_id) -> None:
                if next_offset is None:
                    # Parent IDs are read in ascending order, so the next run starts after this parent.
                    manager.save_state(_parent_state(endpoint.scope, current + 1))
                else:
                    manager.save_state(_parent_state(endpoint.scope, current, next_offset))

            path = endpoint.path.format(merchant_id=merchant_id, **{parent_key: parent_id})
            yield from read(path, {}, {parent_key: parent_id}, offset, save)

    def items() -> Iterator[list[dict[str, Any]]]:
        state = (manager.load_state() if manager.can_resume() else None) or XsollaResumeConfig()
        if endpoint.scope != "merchant":
            yield from parent_items(state)
        elif endpoint.window_days is not None or endpoint.monthly_windows:
            yield from windowed_items(state)
        else:
            yield from read(
                endpoint.path.format(merchant_id=merchant_id),
                {},
                {},
                state.offset,
                lambda next_offset: (
                    manager.save_state(XsollaResumeConfig(offset=next_offset)) if next_offset is not None else None
                ),
            )

    return SourceResponse(
        name=endpoint_name,
        items=items,
        primary_keys=list(endpoint.primary_keys),
        # Xsolla does not document the order of rows inside a window. The pipeline stores the
        # watermark of a "desc" source only after the sync completes.
        sort_mode="desc",
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
    )
