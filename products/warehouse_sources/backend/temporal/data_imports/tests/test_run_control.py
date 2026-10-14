import asyncio

import pytest

from posthog.temporal.common.shutdown import WorkerShuttingDownError

from products.warehouse_sources.backend.temporal.data_imports.run_control import EventShutdownMonitor


def _monitor(event: asyncio.Event) -> EventShutdownMonitor:
    return EventShutdownMonitor(
        event,
        activity_id="job-1",
        activity_type="sync.extract",
        task_queue="warehouse-extract",
        attempt=2,
        workflow_id="wf-1",
        workflow_type="external-data-job",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("set_before_start", [True, False], ids=["set_before_start", "set_after_start"])
async def test_the_injected_event_trips_the_monitor_outside_an_activity(set_before_start: bool) -> None:
    event = asyncio.Event()
    if set_before_start:
        event.set()

    async with _monitor(event) as monitor:
        sync_wait = asyncio.create_task(asyncio.to_thread(monitor.wait_for_worker_shutdown_sync, 5))
        if not set_before_start:
            monitor.raise_if_is_worker_shutdown()
            event.set()

        await asyncio.wait_for(monitor.wait_for_worker_shutdown(), timeout=5)
        assert await asyncio.wait_for(sync_wait, timeout=5)
        assert monitor.is_worker_shutdown()
        with pytest.raises(WorkerShuttingDownError) as exc_info:
            monitor.raise_if_is_worker_shutdown()

    error = exc_info.value
    assert (error.activity_id, error.activity_type, error.task_queue, error.attempt) == (
        "job-1",
        "sync.extract",
        "warehouse-extract",
        2,
    )
    assert (error.workflow_id, error.workflow_type) == ("wf-1", "external-data-job")
