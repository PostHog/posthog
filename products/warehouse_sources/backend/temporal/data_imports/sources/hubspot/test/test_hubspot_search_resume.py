import json
from collections.abc import Callable, Iterable
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.sources.common import boundary_checkpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot import hubspot


class _MemoryRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def exists(self, key: str) -> int:
        return int(key in self.store)

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


def _row_ids(item: Any, id_column: str) -> list[Any]:
    if isinstance(item, pa.Table):
        return item.column(id_column).to_pylist()
    rows = item if isinstance(item, list) else [item]
    return [row[id_column] for row in rows]


def _run_attempt(
    manager: ResumableSourceManager[Any], items: Callable[[], Iterable[Any]], id_column: str
) -> tuple[list[Any], bool]:
    """Read one attempt. Commit the cursor after each item and at each safe point.

    This is the earliest the pipeline can commit, so a cursor saved ahead of rows the source still
    holds loses those rows.
    """
    received: list[Any] = []

    def hand_over() -> None:
        manager.confirm()
        manager.commit()

    try:
        with activate_safe_point(hand_over, covers_framework_checkpoints=False):
            for item in items():
                received.extend(_row_ids(item, id_column))
                hand_over()
    except Exception:
        return received, False
    return received, True


def _run_attempts_until_done(
    build_items: Callable[[ResumableSourceManager[Any]], Callable[[], Iterable[Any]]],
    data_class: type,
    *,
    id_column: str = "id",
    max_attempts: int = 4,
) -> list[list[Any]]:
    """Run attempts of one job, each with a new manager, until one ends without an error."""
    redis = _MemoryRedis()
    attempts: list[list[Any]] = []
    with patch.object(ResumableSourceManager, "_get_redis", lambda self: nullcontext(redis)):
        for _ in range(max_attempts):
            inputs = cast(SourceInputs, SimpleNamespace(team_id=1, job_id="job-1", logger=MagicMock()))
            manager: ResumableSourceManager[Any] = ResumableSourceManager(inputs, data_class)
            received, finished = _run_attempt(manager, build_items(manager), id_column)
            attempts.append(received)
            if finished:
                return attempts
    raise AssertionError(f"The import did not end in {max_attempts} attempts")


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
def test_hubspot_search_resumes_at_a_window_end_only_after_the_rows_of_the_window(
    fail_from_request: int, rows_written_two_times: int | None
) -> None:
    server = _HubspotSearchServer([2300, 700, 400], fail_from_request)

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
        first, second = _run_attempts_until_done(build_items, hubspot.HubspotResumeConfig)

    assert set(first) | set(second) == {row["id"] for row in server.rows}
    if rows_written_two_times is not None:
        assert len(set(first) & set(second)) == rows_written_two_times
