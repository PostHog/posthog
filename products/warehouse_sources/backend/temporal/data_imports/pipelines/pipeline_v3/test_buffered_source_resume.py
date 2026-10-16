import json
import asyncio
import threading
from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.test_pipeline import (
    _MemoryRedis,
    run_attempts_until_done,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common import boundary_checkpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot import hubspot
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo import klaviyo
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.settings import KLAVIYO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.temporalio import temporalio as temporalio_source

_START_MS = 1_700_000_000_000


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = json.dumps(payload)
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _HubspotSearchServer:
    def __init__(self, rows_per_window: list[int], fail_from_request: int) -> None:
        self.rows: list[dict[str, Any]] = [
            {"id": f"{window}-{index}", "modified": _START_MS + 1 + window * (hubspot.WINDOW_SIZE_MS + 1) + index + 1}
            for window, count in enumerate(rows_per_window)
            for index in range(count)
        ]
        self.now_ms = _START_MS + len(rows_per_window) * (hubspot.WINDOW_SIZE_MS + 1)
        self.requests = 0
        self.fail_from_request: int | None = fail_from_request

    def post(self, url: str, headers: Any = None, json: Any = None, timeout: Any = None) -> _Response:
        self.requests += 1
        if self.fail_from_request is not None and self.requests >= self.fail_from_request:
            return _Response(500, {"message": "outage"})
        bounds = {item["operator"]: int(item["value"]) for item in json["filterGroups"][0]["filters"]}
        matched = [row for row in self.rows if bounds["GTE"] <= row["modified"] <= bounds["LTE"]]
        start = int(json.get("after") or 0)
        page = matched[start : start + json["limit"]]
        payload: dict[str, Any] = {
            "results": [
                {
                    "id": row["id"],
                    "properties": {"hs_object_id": row["id"], "hs_lastmodifieddate": str(row["modified"])},
                }
                for row in page
            ]
        }
        if start + json["limit"] < len(matched):
            payload["paging"] = {"next": {"after": str(start + json["limit"])}}
        return _Response(200, payload)


@pytest.mark.parametrize(
    "fail_from_request,rows_written_two_times",
    # 2,300 rows in window 1 are 12 search pages. Request 13 is the first request of window 2.
    [(5, None), (13, 0), (17, None)],
    ids=["fails_in_window_1", "fails_at_the_start_of_window_2", "fails_in_window_3"],
)
@pytest.mark.asyncio
async def test_hubspot_search_resumes_at_a_window_end_only_after_the_rows_of_the_window(
    fail_from_request: int, rows_written_two_times: int | None
) -> None:
    server = _HubspotSearchServer([2300, 700, 400], fail_from_request)
    redis = _MemoryRedis()

    def build_items(manager: Any):
        def items():
            try:
                yield from hubspot.get_rows_via_search(
                    api_key="key",
                    refresh_token="refresh",
                    endpoint="deals",
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_START_MS,
                    include_custom_props=False,
                    now_ms=server.now_ms,
                    api_version=hubspot.HUBSPOT_API_VERSION_V3,
                )
            finally:
                server.fail_from_request = None

        return items

    with (
        patch.object(hubspot, "make_tracked_session", lambda *args, **kwargs: server),
        patch("tenacity.nap.time.sleep", lambda seconds: None),
        patch.object(boundary_checkpoint, "PARTIAL_FLUSH_INTERVAL_SECONDS", 0),
    ):
        first, second = await run_attempts_until_done(redis, build_items, hubspot.HubspotResumeConfig)

    assert set(first) | set(second) == {row["id"] for row in server.rows}
    if rows_written_two_times is not None:
        assert len(set(first) & set(second)) == rows_written_two_times


@pytest.mark.parametrize("fail_on_request", [2, 3, 4])
@pytest.mark.asyncio
async def test_klaviyo_fan_out_bookmarks_the_next_parent_only_after_the_rows_of_the_parent(
    fail_on_request: int,
) -> None:
    parents = ["L1", "L2", "L3", "L4"]
    served = [f"{parent}-{index}" for parent in parents for index in range(3)]
    requests = {"count": 0, "fail_on": fail_on_request}
    redis = _MemoryRedis()

    def fetch_page(session: Any, url: str, headers: Any, logger: Any, json_body: Any = None) -> dict[str, Any]:
        requests["count"] += 1
        if requests["count"] == requests["fail_on"]:
            raise RuntimeError("request failed after its retries")
        parent = next(parent for parent in parents if f"/lists/{parent}/" in url)
        return {"data": [{"id": f"{parent}-{index}"} for index in range(3)], "links": {"next": None}}

    def build_items(manager: Any):
        def items():
            # Four rows for each table, so a table ends in the middle of a parent.
            batcher = Batcher(MagicMock(), chunk_size=4)
            yield from klaviyo._get_fan_out_rows(
                MagicMock(), {}, MagicMock(), batcher, manager, KLAVIYO_ENDPOINTS["list_profiles"], {}
            )
            if batcher.should_yield(include_incomplete_chunk=True):
                yield batcher.get_table()

        return items

    with (
        patch.object(klaviyo, "_iter_fan_out_parents", lambda *args: [({}, parent) for parent in parents]),
        patch.object(klaviyo, "_fetch_page", fetch_page),
        patch.object(boundary_checkpoint, "PARTIAL_FLUSH_INTERVAL_SECONDS", 0),
    ):
        attempts = await run_attempts_until_done(
            redis, build_items, klaviyo.KlaviyoResumeConfig, id_column="profile_id"
        )

    assert sorted({row_id for attempt in attempts for row_id in attempt}) == served
    assert len(attempts) == 2 and len(attempts[1]) < len(served)


class _WorkflowPages:
    def __init__(self, total: int, page_size: int, start: int, on_last_page: threading.Event) -> None:
        self._total = total
        self._page_size = page_size
        self._position = start
        self._on_last_page = on_last_page
        self.next_page_token: bytes | None = str(start).encode() if start else None
        self.current_page: list[Any] | None = None

    async def fetch_next_page(self) -> None:
        end = min(self._position + self._page_size, self._total)
        self.current_page = [
            SimpleNamespace(id=f"wf-{index}", run_id=f"run-{index}", close_time=None)
            for index in range(self._position, end)
        ]
        self._position = end
        self.next_page_token = str(end).encode() if end < self._total else None
        if end >= self._total:
            self._on_last_page.set()


@pytest.mark.parametrize("shutdown_after_items", [250, 450])
@pytest.mark.asyncio
async def test_temporalio_commits_a_page_token_only_for_rows_the_pipeline_received(shutdown_after_items: int) -> None:
    total = 1000
    redis = _MemoryRedis()
    producer_read_every_page = threading.Event()

    class Client:
        def list_workflows(self, query: Any = None, next_page_token: bytes | None = None, page_size: int = 100):
            start = int(next_page_token.decode()) if next_page_token else 0
            return _WorkflowPages(total, page_size, start, producer_read_every_page)

    async def get_client(*args: Any, **kwargs: Any) -> Client:
        return Client()

    async def on_write(ids: list[str]) -> None:
        # The producer thread reads ahead of the pipeline. Wait until it has read every page, so
        # the first cursor commit comes when the producer is as far ahead as it can be.
        await asyncio.to_thread(producer_read_every_page.wait, 30)

    def build_items(manager: Any):
        return lambda: temporalio_source._async_iter_to_sync(
            temporalio_source._get_workflows(MagicMock(), None, False, manager, MagicMock(), 1),
            save_resume_state=manager.save_state,
        )

    with patch.object(temporalio_source, "_get_temporal_client", get_client):
        first, second = await run_attempts_until_done(
            redis,
            build_items,
            temporalio_source.TemporalIOResumeConfig,
            on_write=on_write,
            chunk_size=200,
            shutdown_after_items=shutdown_after_items,
        )

    assert set(first) | set(second) == {f"wf-{index}" for index in range(total)}
