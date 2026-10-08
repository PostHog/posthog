import asyncio
import threading
import contextvars

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.abandonable_iterate import (
    AbandonableSourcePuller,
)

_probe: contextvars.ContextVar[str] = contextvars.ContextVar("probe", default="unset")


@pytest.mark.asyncio
async def test_the_source_thread_keeps_one_copy_of_the_callers_context():
    _probe.set("outer")

    def source():
        yield _probe.get()
        _probe.set("inner")
        yield _probe.get()
        yield _probe.get()

    puller = AbandonableSourcePuller(source())
    seen = [(await puller.pull())[1] for _ in range(3)]
    has_more, _ = await puller.pull()
    await puller.stop()

    assert seen == ["outer", "inner", "inner"]
    assert has_more is False
    assert _probe.get() == "outer"


@pytest.mark.asyncio
async def test_stopping_a_sync_source_waits_for_its_pull_and_closes_on_the_daemon_thread():
    release = threading.Event()
    blocked = threading.Event()
    closed = threading.Event()
    thread: list[threading.Thread] = []

    def source():
        try:
            thread.append(threading.current_thread())
            blocked.set()
            release.wait()
            yield "late"
        finally:
            closed.set()

    puller = AbandonableSourcePuller(source())
    pull = puller.pull()
    await asyncio.to_thread(blocked.wait, 5)

    with patch.object(asyncio, "to_thread", side_effect=AssertionError("stop used the shared executor")):
        stopping = asyncio.create_task(puller.stop())
        await asyncio.sleep(0)
        assert not stopping.done()

        release.set()
        await stopping

    assert await asyncio.to_thread(closed.wait, 5)
    await asyncio.to_thread(thread[0].join, 5)
    assert thread[0].daemon
    assert not thread[0].is_alive()
    assert not pull.done()


@pytest.mark.asyncio
async def test_a_stopped_async_source_gets_a_cancellation():
    started = asyncio.Event()
    outcome: list[str] = []

    async def source():
        try:
            started.set()
            await asyncio.Event().wait()
            yield "never"
        except asyncio.CancelledError:
            outcome.append("cancelled")
            raise

    puller = AbandonableSourcePuller(source())
    pull = puller.pull()
    await started.wait()

    await puller.stop()
    await asyncio.wait({pull})

    assert outcome == ["cancelled"]
