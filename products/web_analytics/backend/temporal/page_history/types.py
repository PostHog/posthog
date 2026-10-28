from datetime import datetime, timedelta

from posthog.dataclasses import frozen

CAPTURE_WORKFLOW_NAME = "heatmap-page-history-capture"
TICK_WORKFLOW_NAME = "heatmap-page-history-tick"
TICK_SCHEDULE_ID = "heatmap-page-history-tick-schedule"
TICK_INTERVAL = timedelta(minutes=5)
RENDER_ATTEMPTS = 2
RENDER_RETRY_DELAY = timedelta(seconds=120)


def capture_workflow_id(request_id: str) -> str:
    return f"{CAPTURE_WORKFLOW_NAME}-{request_id}"


def tick_start(now: datetime) -> datetime:
    return now - (now - datetime.min.replace(tzinfo=now.tzinfo)) % TICK_INTERVAL


@frozen
class CaptureInputs:
    team_id: int
    request_id: str


@frozen
class ClaimedCapture:
    team_id: int
    request_id: str
    claim_id: str


@frozen
class RenderOutcome:
    has_thumbnail: bool = False
    failure_cause: str | None = None
    page_status: int | None = None


@frozen
class FinishInputs:
    capture: ClaimedCapture
    outcome: RenderOutcome


@frozen
class DueCapture:
    team_id: int
    request_id: str
    seconds_left: float


@frozen
class TickInputs:
    pass


@frozen
class TickResult:
    pruned: int = 0
    started: int = 0
    already_running: int = 0
