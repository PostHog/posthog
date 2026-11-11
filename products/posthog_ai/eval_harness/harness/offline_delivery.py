from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from posthog.dataclasses import frozen

from ..offline_results import OfflineUploadError

if TYPE_CHECKING:
    from ..offline_results import OfflineEvalPublisher, OfflineEvalUpload
    from .reporting import ProgressReporter

logger = logging.getLogger(__name__)


@frozen
class _PendingUpload:
    publisher: OfflineEvalPublisher
    upload: OfflineEvalUpload


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
        self._uploading: set[asyncio.Task[None]] = set()
        self._paused_jobs: dict[asyncio.Task[None], _PendingUpload] = {}
        self._paused = False
        self._closed = False

    async def _report_failed(self, job: _PendingUpload, reason: str) -> None:
        await self._reporter.record_posthog_offline_result(
            job.upload.experiment_name, f"upload failed: {reason}. Results were not saved for retry."
        )

    async def _deliver(self, job: _PendingUpload) -> None:
        task = asyncio.current_task()
        assert task is not None
        reason: str | None = None
        url: str | None = None
        try:
            async with self._slots:
                url = await asyncio.wait_for(job.publisher.publish(job.upload), timeout=self._upload_timeout)
        except TimeoutError:
            reason = "upload deadline exceeded"
        except Exception as error:
            reason = str(error) if isinstance(error, OfflineUploadError) else type(error).__name__
        finally:
            self._uploading.discard(task)
        if reason is not None:
            await self._report_failed(job, reason)
        else:
            await self._reporter.record_posthog_offline_result(job.upload.experiment_name, "uploaded", url=url)
            await job.publisher.tag(job.upload)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.pop(task, None)
        self._uploading.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Failed to report offline evaluation upload", exc_info=error)

    def _start(self, job: _PendingUpload) -> None:
        task = asyncio.create_task(self._deliver(job))
        self._tasks[task] = job
        self._uploading.add(task)
        task.add_done_callback(self._finished)

    def submit(self, publisher: OfflineEvalPublisher, upload: OfflineEvalUpload) -> bool:
        if self._closed or self._paused or sum(not task.done() for task in self._tasks) >= self._max_pending:
            return False
        self._start(_PendingUpload(publisher=publisher, upload=upload))
        return True

    def _pending_uploads(self) -> dict[asyncio.Task[None], _PendingUpload]:
        return {task: job for task, job in self._tasks.items() if not task.done() and task in self._uploading}

    async def _cancel(self, tasks: Iterable[asyncio.Task[None]], reason: str | None) -> None:
        pending = {task: self._tasks[task] for task in tasks if not task.done()}
        uploads = [job for task, job in pending.items() if task in self._uploading]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if reason is not None:
            for job in uploads:
                await self._report_failed(job, reason)

    async def pause(self) -> None:
        if self._closed:
            return
        self._paused = True
        self._paused_jobs.update(self._pending_uploads())
        await self._cancel(tuple(self._paused_jobs), None)

    async def cancel(self) -> None:
        self._closed = True
        pending = {**self._paused_jobs, **self._pending_uploads()}
        await self._cancel(tuple(self._tasks), None)
        self._paused_jobs.clear()
        for job in pending.values():
            await self._report_failed(job, "upload interrupted")

    async def drain(self, timeout: float | None = None) -> None:
        self._closed = True
        for job in self._paused_jobs.values():
            self._start(job)
        self._paused_jobs.clear()
        tasks = tuple(self._tasks)
        if not tasks:
            return
        try:
            _, pending = await asyncio.wait(tasks, timeout=self._upload_timeout if timeout is None else timeout)
            await self._cancel(pending, "shutdown deadline exceeded")
        except asyncio.CancelledError:
            await self.cancel()
            raise
