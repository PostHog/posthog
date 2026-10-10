from uuid import UUID

from temporalio import activity

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.heartbeat import Heartbeater

from products.web_analytics.backend.heatmap_history import HeatmapHistoryService
from products.web_analytics.backend.models import HeatmapCaptureRequest
from products.web_analytics.backend.temporal.page_history.scheduling import prune_history, schedule_due_captures
from products.web_analytics.backend.temporal.page_history.types import (
    RENDER_ATTEMPTS,
    CaptureInputs,
    ClaimedCapture,
    DueCapture,
    FinishInputs,
    RenderOutcome,
)


def _load(capture: ClaimedCapture) -> HeatmapCaptureRequest | None:
    return HeatmapHistoryService.load_claimed(
        team_id=capture.team_id, request_id=UUID(capture.request_id), claim_id=UUID(capture.claim_id)
    )


@activity.defn(name="heatmap-page-history-claim")
async def claim_capture(inputs: CaptureInputs) -> str | None:
    request = await database_sync_to_async_pool(HeatmapHistoryService.claim)(
        team_id=inputs.team_id, request_id=UUID(inputs.request_id)
    )
    return None if request is None else str(request.claim_id)


def _render(capture: ClaimedCapture, final_attempt: bool) -> RenderOutcome:
    request = _load(capture)
    if request is None:
        return RenderOutcome(failure_cause="capture_cancelled")
    return HeatmapHistoryService.render_and_store(request, final_attempt=final_attempt)


@activity.defn(name="heatmap-page-history-render")
async def render_capture(capture: ClaimedCapture) -> RenderOutcome:
    async with Heartbeater(details=(capture.request_id,), factor=4):
        return await database_sync_to_async_pool(_render)(capture, activity.info().attempt >= RENDER_ATTEMPTS)


def _finish(inputs: FinishInputs) -> None:
    request = _load(inputs.capture)
    if request is None:
        return
    outcome = inputs.outcome
    if outcome.failure_cause is None:
        HeatmapHistoryService.publish(request, outcome.has_thumbnail)
    else:
        HeatmapHistoryService.fail(request, outcome.failure_cause, outcome.page_status)


@activity.defn(name="heatmap-page-history-finish")
async def finish_capture(inputs: FinishInputs) -> None:
    await database_sync_to_async_pool(_finish)(inputs)


@activity.defn(name="heatmap-page-history-prune")
async def prune_page_history() -> int:
    return await database_sync_to_async_pool(prune_history)()


@activity.defn(name="heatmap-page-history-schedule")
async def schedule_page_history() -> list[DueCapture]:
    return await database_sync_to_async_pool(schedule_due_captures)()
