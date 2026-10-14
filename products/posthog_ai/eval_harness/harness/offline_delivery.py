from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from posthog.dataclasses import frozen

from ..offline_results import OfflineEvalUpload, OfflineUploadError

if TYPE_CHECKING:
    from ..offline_results import OfflineEvalPublisher
    from .reporting import ProgressReporter

logger = logging.getLogger(__name__)


@frozen
class _PendingUpload:
    publisher: OfflineEvalPublisher
    upload_path: Path
    experiment_name: str


class OfflineEvalDelivery:
    def __init__(
        self,
        reporter: ProgressReporter,
        *,
        max_concurrency: int = 2,
        max_pending: int = 32,
        upload_timeout: float = 60.0,
    ) -> None:
        if max_concurrency < 1 or max_pending < 1 or upload_timeout < 0:
            raise ValueError("Upload concurrency and capacity must be positive, and timeout must be nonnegative")
        self._reporter = reporter
        self._slots = asyncio.Semaphore(max_concurrency)
        self._max_pending = max_pending
        self._upload_timeout = upload_timeout
        self._tasks: dict[asyncio.Task[None], _PendingUpload] = {}
        self._paused_jobs: dict[asyncio.Task[None], _PendingUpload] = {}
        self._paused = False
        self._closed = False

    async def _report_pending(self, job: _PendingUpload, reason: str) -> None:
        await self._reporter.record_posthog_offline_result(
            job.experiment_name, f"upload pending: {reason}. Saved requests: {job.upload_path}"
        )

    async def _deliver(self, job: _PendingUpload) -> None:
        try:
            async with self._slots:
                async with asyncio.timeout(self._upload_timeout):
                    upload = await asyncio.to_thread(OfflineEvalUpload.load, job.upload_path)
                    url = await job.publisher.publish(upload)
        except TimeoutError:
            await self._report_pending(job, "upload deadline exceeded")
        except Exception as error:
            detail = str(error) if isinstance(error, OfflineUploadError) else type(error).__name__
            await self._report_pending(job, detail)
        else:
            await self._reporter.record_posthog_offline_result(job.experiment_name, "uploaded", url=url)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.pop(task, None)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Failed to report offline evaluation upload", exc_info=error)

    def _start(self, job: _PendingUpload) -> None:
        task = asyncio.create_task(self._deliver(job))
        self._tasks[task] = job
        task.add_done_callback(self._finished)

    def submit(self, publisher: OfflineEvalPublisher, upload_path: Path, experiment_name: str) -> bool:
        if self._closed or self._paused or sum(not task.done() for task in self._tasks) >= self._max_pending:
            return False
        self._start(_PendingUpload(publisher=publisher, upload_path=upload_path, experiment_name=experiment_name))
        return True

    async def _cancel(self, tasks: Iterable[asyncio.Task[None]], reason: str | None) -> None:
        pending = {task: self._tasks[task] for task in tasks if not task.done()}
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if reason is not None:
            for job in pending.values():
                await self._report_pending(job, reason)

    async def pause(self) -> None:
        if self._closed:
            return
        self._paused = True
        self._paused_jobs.update({task: job for task, job in self._tasks.items() if not task.done()})
        await self._cancel(tuple(self._paused_jobs), None)

    async def cancel(self) -> None:
        self._closed = True
        pending = {**self._paused_jobs, **{task: job for task, job in self._tasks.items() if not task.done()}}
        await self._cancel(tuple(self._tasks), None)
        self._paused_jobs.clear()
        for job in pending.values():
            await self._report_pending(job, "upload interrupted")

    async def drain(self, timeout: float = 30.0) -> None:
        self._closed = True
        for job in self._paused_jobs.values():
            self._start(job)
        self._paused_jobs.clear()
        tasks = tuple(self._tasks)
        if not tasks:
            return
        try:
            _, pending = await asyncio.wait(tasks, timeout=timeout)
            await self._cancel(pending, "shutdown deadline exceeded")
        except asyncio.CancelledError:
            await self.cancel()
            raise
