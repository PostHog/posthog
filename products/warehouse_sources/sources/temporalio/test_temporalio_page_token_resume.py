import threading
from collections.abc import Callable, Iterable
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.sources.sdk import ResumableSourceManager, SourceInputs
from products.warehouse_sources.sources.sdk.testing import activate_safe_point
from products.warehouse_sources.sources.temporalio import temporalio as temporalio_source


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


class _WorkerShutdown(Exception):
    pass


def _run_attempt(
    manager: ResumableSourceManager[Any],
    items: Callable[[], Iterable[Any]],
    *,
    before_first_commit: Callable[[], None],
    shutdown_at_item: int | None,
) -> tuple[list[Any], bool]:
    """Read one attempt. Commit the cursor after each item and at each safe point.

    This is the earliest the pipeline can commit, so a cursor saved ahead of rows the source still
    holds loses those rows. `shutdown_at_item` stops the attempt the way a worker shutdown does.
    """
    received: list[Any] = []
    committed = False

    def hand_over() -> None:
        nonlocal committed
        if not committed:
            before_first_commit()
            committed = True
        manager.confirm()
        manager.commit()

    try:
        with activate_safe_point(hand_over, covers_framework_checkpoints=False):
            for item in items():
                if shutdown_at_item is not None and len(received) + 1 == shutdown_at_item:
                    raise _WorkerShutdown()
                received.append(item["id"])
                hand_over()
    except _WorkerShutdown:
        return received, False
    return received, True


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
def test_temporalio_commits_a_page_token_only_for_rows_the_pipeline_received(shutdown_after_items: int) -> None:
    total = 1000
    redis = _MemoryRedis()
    producer_read_every_page = threading.Event()

    class Client:
        def list_workflows(self, query: Any = None, next_page_token: bytes | None = None, page_size: int = 100):
            start = int(next_page_token.decode()) if next_page_token else 0
            return _WorkflowPages(total, page_size, start, producer_read_every_page)

    async def get_client(*args: Any, **kwargs: Any) -> Client:
        return Client()

    def wait_for_the_producer() -> None:
        # The producer thread reads ahead of the consumer. Wait until it has read every page, so
        # the first cursor commit comes when the producer is as far ahead as it can be.
        assert producer_read_every_page.wait(30)

    attempts: list[list[Any]] = []
    with (
        patch.object(temporalio_source, "_get_temporal_client", get_client),
        patch.object(ResumableSourceManager, "_get_redis", lambda self: nullcontext(redis)),
    ):
        for shutdown_at_item in (shutdown_after_items, None):
            inputs = cast(SourceInputs, SimpleNamespace(team_id=1, job_id="job-1", logger=MagicMock()))
            manager: ResumableSourceManager[Any] = ResumableSourceManager(
                inputs, temporalio_source.TemporalIOResumeConfig
            )

            def read_workflows(manager: ResumableSourceManager[Any] = manager) -> Iterable[Any]:
                return temporalio_source._async_iter_to_sync(
                    temporalio_source._get_workflows(MagicMock(), None, False, manager, MagicMock(), 1),
                    save_resume_state=manager.save_state,
                )

            received, finished = _run_attempt(
                manager,
                read_workflows,
                before_first_commit=wait_for_the_producer,
                shutdown_at_item=shutdown_at_item,
            )
            attempts.append(received)
            assert finished is (shutdown_at_item is None)

    first, second = attempts
    assert set(first) | set(second) == {f"wf-{index}" for index in range(total)}
    assert len(second) < total
