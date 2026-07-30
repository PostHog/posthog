import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.redis import get_async_client

from products.error_tracking.backend.temporal.lifecycle.issue_created.types import (
    IssueCreatedSnapshot,
    IssueCreatedWorkflowInputs,
)
from products.error_tracking.backend.temporal.lifecycle.side_effects import emit_issue_lifecycle_signal
from products.error_tracking.backend.temporal.lifecycle.signal_throttle import MAX_LIFECYCLE_SIGNALS_PER_HOUR

SIDE_EFFECTS = "products.error_tracking.backend.temporal.lifecycle.side_effects"
THROTTLE = "products.error_tracking.backend.temporal.lifecycle.signal_throttle"


def _inputs(notification_id: str, issue_id: str) -> IssueCreatedWorkflowInputs:
    return IssueCreatedWorkflowInputs(
        notification_id=notification_id,
        team_id=42,
        issue_id=issue_id,
        issue=IssueCreatedSnapshot(
            name="TypeError",
            description="Something failed",
            status="active",
            created_at="2026-07-21T12:00:00Z",
        ),
        fingerprint="fingerprint",
        event_uuid="01982721-5e00-7000-8000-000000000003",
        event_timestamp="2026-07-21T12:05:00Z",
    )


@pytest.fixture(autouse=True)
async def _flush_redis():
    await get_async_client().flushall()
    yield


@pytest.fixture
def team() -> MagicMock:
    team = MagicMock()
    team.id = 42
    return team


def _patches(team: MagicMock, emit_signal: AsyncMock):
    return (
        patch(f"{SIDE_EFFECTS}.Team.objects.aget", new=AsyncMock(return_value=team)),
        patch(f"{SIDE_EFFECTS}.fetch_event_properties", return_value={}),
        patch(f"{SIDE_EFFECTS}.render_stacktrace", return_value="frame"),
        patch(f"{SIDE_EFFECTS}.emit_signal", new=emit_signal),
        patch(f"{THROTTLE}.posthoganalytics.capture"),
    )


async def _emit(team: MagicMock, emit_signal: AsyncMock, notification_id: str, issue_id: str) -> None:
    p1, p2, p3, p4, p5 = _patches(team, emit_signal)
    with p1, p2, p3, p4, p5:
        await emit_issue_lifecycle_signal(
            _inputs(notification_id, issue_id),
            source_type="issue_created",
            preamble="New issue",
        )


@pytest.mark.asyncio
async def test_issue_creation_storm_is_capped_per_team_and_hour(team: MagicMock) -> None:
    emit_signal = AsyncMock()
    overflow = 5
    for index in range(MAX_LIFECYCLE_SIGNALS_PER_HOUR + overflow):
        await _emit(team, emit_signal, f"notification-{index}", f"issue-{index}")

    assert emit_signal.await_count == MAX_LIFECYCLE_SIGNALS_PER_HOUR


@pytest.mark.asyncio
async def test_budget_is_tracked_per_source_type(team: MagicMock) -> None:
    emit_signal = AsyncMock()
    for index in range(MAX_LIFECYCLE_SIGNALS_PER_HOUR):
        await _emit(team, emit_signal, f"notification-{index}", f"issue-{index}")
    emit_signal.reset_mock()

    p1, p2, p3, p4, p5 = _patches(team, emit_signal)
    with p1, p2, p3, p4, p5:
        await emit_issue_lifecycle_signal(
            _inputs("notification-spiking", "issue-spiking"),
            source_type="issue_spiking",
            preamble="Issue is spiking",
        )

    emit_signal.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_retried_notification_does_not_burn_a_second_slot(team: MagicMock) -> None:
    emit_signal = AsyncMock()
    for _ in range(MAX_LIFECYCLE_SIGNALS_PER_HOUR + 3):
        await _emit(team, emit_signal, "notification-retried", "issue-retried")

    assert emit_signal.await_count == MAX_LIFECYCLE_SIGNALS_PER_HOUR + 3


@pytest.mark.asyncio
async def test_a_redis_failure_fails_open(team: MagicMock) -> None:
    emit_signal = AsyncMock()
    with patch(f"{THROTTLE}.get_async_client", side_effect=RuntimeError("redis is down")):
        for index in range(MAX_LIFECYCLE_SIGNALS_PER_HOUR + 3):
            await _emit(team, emit_signal, f"notification-{index}", f"issue-{index}")

    assert emit_signal.await_count == MAX_LIFECYCLE_SIGNALS_PER_HOUR + 3
