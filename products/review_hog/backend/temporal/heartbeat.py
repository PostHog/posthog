import asyncio
import logging
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING

from django.utils import timezone

from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.review_hog.backend.models import ReviewReport

if TYPE_CHECKING:
    from types import TracebackType

logger = logging.getLogger(__name__)

REPORT_HEARTBEAT_INTERVAL = timedelta(minutes=1)


class ReviewActivityHeartbeater(Heartbeater):
    def __init__(self, *, team_id: int, report_id: str, head_sha: str) -> None:
        super().__init__()
        self.team_id = team_id
        self.report_id = report_id
        self.head_sha = head_sha
        self.report_heartbeat_task: asyncio.Task[None] | None = None

    def touch_report(self) -> None:
        now = timezone.now()
        ReviewReport.objects.for_team(self.team_id).filter(
            id=self.report_id,
            status=ReviewReport.Status.ACTIVE,
            head_sha=self.head_sha,
            updated_at__lt=now - REPORT_HEARTBEAT_INTERVAL,
        ).update(updated_at=now)

    async def _heartbeat_report(self) -> None:
        while True:
            try:
                await database_sync_to_async(self.touch_report, thread_sensitive=False)()
            except Exception:
                logger.exception("Could not refresh ReviewHog report activity for %s", self.report_id)
            await asyncio.sleep(REPORT_HEARTBEAT_INTERVAL.total_seconds())

    async def __aenter__(self) -> "ReviewActivityHeartbeater":
        await super().__aenter__()
        # Temporal heartbeats cannot keep the reviews API fresh while a sandbox has no results yet.
        self.report_heartbeat_task = asyncio.create_task(self._heartbeat_report())
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: "TracebackType | None"
    ) -> None:
        if self.report_heartbeat_task is not None:
            self.report_heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.report_heartbeat_task
            self.report_heartbeat_task = None
        await super().__aexit__(exc_type, exc, traceback)
