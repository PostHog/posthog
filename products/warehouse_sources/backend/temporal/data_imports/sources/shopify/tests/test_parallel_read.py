import re
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shopify import (
    ShopifyAuthMethodConfig,
    ShopifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.constants import (
    ABANDONED_CHECKOUTS,
    SHOPIFY_GRAPHQL_OBJECTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.parallel import ReadWindow, _split
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import (
    PHASE_PARALLEL,
    ShopifyReadStopped,
    ShopifyResumeConfig,
    iter_shopify_pages,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source import ShopifySource

_SHOPIFY = "products.warehouse_sources.backend.temporal.data_imports.sources.shopify"
_CLUSTER_START = datetime(2022, 6, 20, tzinfo=UTC)


def _orders() -> list[dict[str, Any]]:
    # Most orders share a few minutes, the way a bulk update leaves them, and the rest spread over years.
    clustered = [_CLUSTER_START + timedelta(seconds=3 * index) for index in range(200)]
    spread = [datetime(2019, 1, 1, tzinfo=UTC) + timedelta(days=21 * index) for index in range(100)]
    return [
        {"id": f"order-{index}", "updatedAt": moment.isoformat().replace("+00:00", "Z")}
        for index, moment in enumerate(sorted(clustered + spread))
    ]


_ORDERS = _orders()
_ORDER_IDS = {order["id"] for order in _ORDERS}


class _Store:
    """Answers the orders search the way Shopify does: filtered on `updated_at`, sorted by it, paged by cursor."""

    def __init__(self, fail_windows_from: datetime | None = None):
        self.fail_windows_from = fail_windows_from

    def __call__(self, request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/admin/oauth/access_token":
            return ScriptedResponse(json={"access_token": "tok"})
        if request.method == "GET":
            return ScriptedResponse(json={"access_scopes": []})
        variables = request.json()["variables"]
        search = variables.get("query") or ""
        lower = re.search(r"updated_at:>='([^']+)'", search)
        upper = re.search(r"updated_at:<'([^']+)'", search)
        low = datetime.fromisoformat(lower.group(1)) if lower else None
        high = datetime.fromisoformat(upper.group(1)) if upper else None
        if self.fail_windows_from is not None and low is not None and low >= self.fail_windows_from:
            return ScriptedResponse(status=500)
        matching = [
            order
            for order in _ORDERS
            if (low is None or datetime.fromisoformat(order["updatedAt"]) >= low)
            and (high is None or datetime.fromisoformat(order["updatedAt"]) < high)
        ]
        offset = int(variables.get("cursor") or 0)
        page = matching[offset : offset + variables["pageSize"]]
        end = offset + len(page)
        return ScriptedResponse(
            json={
                "data": {
                    "orders": {
                        "nodes": page,
                        "pageInfo": {"hasNextPage": end < len(matching), "endCursor": str(end)},
                    }
                }
            }
        )


def _run(store: _Store, *, flag_enabled: bool = True, incremental: bool = True, **inputs: Any) -> DriveResult:
    config = ShopifySourceConfig(
        shopify_store_id="my-store",
        auth_method=ShopifyAuthMethodConfig(
            selection="client_credentials", shopify_client_id="cid", shopify_client_secret="secret"
        ),
    )
    with patch(f"{_SHOPIFY}.source._is_parallel_read_enabled", return_value=flag_enabled):
        return SourceDriver(ShopifySource(), config).run(
            "orders", store, should_use_incremental_field=incremental, **inputs
        )


def _searches(result: DriveResult) -> list[str]:
    return [
        request.json()["variables"].get("query") or ""
        for request in result.requests
        if request.path.endswith("/graphql.json")
    ]


def test_parallel_read_returns_every_order_once_and_splits_a_dense_range() -> None:
    result = _run(_Store())

    assert result.raised is None
    ids = [row["id"] for row in result.rows]
    assert sorted(ids) == sorted(_ORDER_IDS)
    lower_bounds = {re.search(r"updated_at:>='([^']+)'", search).group(1) for search in _searches(result)}  # type: ignore[union-attr]
    # The dense minutes get windows of their own, so more than the first window runs.
    assert sum(1 for bound in lower_bounds if datetime.fromisoformat(bound) >= _CLUSTER_START) >= 2
    assert all("updated_at:<'" in search for search in _searches(result))


def test_resumed_parallel_read_returns_exactly_the_orders_the_first_attempt_did_not_hand_over() -> None:
    first = _run(_Store(fail_windows_from=_CLUSTER_START + timedelta(seconds=150)))

    assert first.raised is not None
    assert isinstance(first.final_state, ShopifyResumeConfig)
    assert first.final_state.phase == PHASE_PARALLEL

    second = _run(_Store(), resume_state=first.final_state, flag_enabled=False)

    assert second.raised is None
    first_ids = {row["id"] for row in first.rows}
    second_ids = [row["id"] for row in second.rows]
    assert len(second_ids) == len(set(second_ids))
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | set(second_ids) == _ORDER_IDS


@pytest.mark.parametrize(
    "kwargs",
    [{"flag_enabled": False}, {"incremental": False}],
    ids=["flag_off", "full_refresh"],
)
def test_reads_pages_in_one_chain_when_the_parallel_read_does_not_apply(kwargs: dict[str, Any]) -> None:
    result = _run(_Store(), **kwargs)

    assert sorted(row["id"] for row in result.rows) == sorted(_ORDER_IDS)
    assert not any("updated_at" in search for search in _searches(result))


def test_a_resumed_window_splits_above_the_rows_it_already_handed_over() -> None:
    window = ReadWindow(
        lo=_CLUSTER_START, query_hi=_CLUSTER_START + timedelta(hours=4), stop_hi=_CLUSTER_START + timedelta(hours=4)
    )
    window.progress = _CLUSTER_START + timedelta(hours=3)
    window.cursor = "40"

    resumed = ReadWindow.from_state(window.to_state())
    new_window = _split([resumed], [resumed])

    assert new_window is not None
    # Splitting from `lo` would give the new window a range the resumed window already read.
    assert new_window.lo > window.progress
    assert resumed.stop_hi == new_window.lo


def test_a_stopped_read_asks_shopify_for_no_more_pages() -> None:
    stop = threading.Event()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "data": {ABANDONED_CHECKOUTS: {"nodes": [{"id": "1"}], "pageInfo": {"hasNextPage": True, "endCursor": "2"}}}
    }
    sess = MagicMock()
    sess.post.return_value = response

    pages = iter_shopify_pages(
        "https://example.invalid/graphql",
        sess,
        SHOPIFY_GRAPHQL_OBJECTS[ABANDONED_CHECKOUTS],
        MagicMock(),
        stop=stop,
    )

    assert next(pages).next_cursor == "2"
    stop.set()
    with pytest.raises(ShopifyReadStopped):
        next(pages)
    assert sess.post.call_count == 1
