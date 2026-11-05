from collections.abc import Callable, Iterable
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa

from products.warehouse_sources.sources.klaviyo import klaviyo
from products.warehouse_sources.sources.klaviyo.settings import KLAVIYO_ENDPOINTS
from products.warehouse_sources.sources.sdk import ResumableSourceManager, SourceInputs
from products.warehouse_sources.sources.sdk.internals import Batcher
from products.warehouse_sources.sources.sdk.testing import activate_safe_point, boundary_checkpoint


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


@pytest.mark.parametrize("fail_on_request", [2, 3, 4])
def test_klaviyo_fan_out_bookmarks_the_next_parent_only_after_the_rows_of_the_parent(
    fail_on_request: int,
) -> None:
    parents = ["L1", "L2", "L3", "L4"]
    served = [f"{parent}-{index}" for parent in parents for index in range(3)]
    requests = {"count": 0, "fail_on": fail_on_request}

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
        attempts = _run_attempts_until_done(build_items, klaviyo.KlaviyoResumeConfig, id_column="profile_id")

    assert sorted({row_id for attempt in attempts for row_id in attempt}) == served
    assert len(attempts) == 2 and len(attempts[1]) < len(served)
