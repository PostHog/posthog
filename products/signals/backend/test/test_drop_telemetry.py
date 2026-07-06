import pytest
from unittest.mock import AsyncMock, patch

from temporalio.exceptions import ActivityError, ApplicationError

from products.signals.backend.temporal.drop_telemetry import (
    CaptureSignalDroppedInput,
    _summarize_drop_error,
    capture_signal_dropped,
    capture_signal_dropped_activity,
)
from products.signals.backend.temporal.types import EmitSignalInputs

PIPELINE_MODULE_PATH = "products.signals.backend.temporal.drop_telemetry"


def _make_signal(team_id: int = 1) -> EmitSignalInputs:
    return EmitSignalInputs(
        team_id=team_id,
        source_product="signals_scout",
        source_type="cross_source_issue",
        source_id="run:abc:finding:def",
        description="a finding",
        weight=0.7,
        extra={"skill_name": "error-tracking", "evidence": [{"nested": "customer content"}]},
    )


def _make_activity_error(cause: BaseException) -> ActivityError:
    error = ActivityError(
        "Activity task failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="worker",
        activity_type="get_embedding_activity",
        activity_id="1",
        retry_state=None,
    )
    error.__cause__ = cause
    return error


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_capture_signal_dropped_activity_emits_event(ateam):
    with patch(f"{PIPELINE_MODULE_PATH}.posthoganalytics.capture") as capture:
        await capture_signal_dropped_activity(
            CaptureSignalDroppedInput(
                team_id=ateam.id,
                source_product="signals_scout",
                source_type="cross_source_issue",
                source_id="run:abc:finding:def",
                weight=0.7,
                stage="grouping_parallel",
                error_type="OperationalError",
                error="the connection is closed",
                extra={
                    "skill_name": "error-tracking",
                    "task_run_id": "task-run-1",
                    "evidence": [{"nested": "customer content"}],
                },
            )
        )

    capture.assert_called_once()
    kwargs = capture.call_args.kwargs
    assert kwargs["event"] == "signal_dropped"
    assert kwargs["distinct_id"] == str(ateam.uuid)
    assert kwargs["properties"]["reason"] == "grouping_processing_error"
    assert kwargs["properties"]["stage"] == "grouping_parallel"
    assert kwargs["properties"]["error_type"] == "OperationalError"
    assert kwargs["properties"]["error"] == "the connection is closed"
    assert kwargs["properties"]["source_product"] == "signals_scout"
    assert kwargs["properties"]["source_type"] == "cross_source_issue"
    assert kwargs["properties"]["source_id"] == "run:abc:finding:def"
    assert kwargs["properties"]["weight"] == 0.7
    # extra is flattened to top-level scalars; nested customer-derived content is dropped
    assert kwargs["properties"]["skill_name"] == "error-tracking"
    assert kwargs["properties"]["task_run_id"] == "task-run-1"
    assert "evidence" not in kwargs["properties"]
    assert "extra" not in kwargs["properties"]
    assert "project" in kwargs["groups"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_capture_failure_is_swallowed(ateam):
    with (
        patch(f"{PIPELINE_MODULE_PATH}.posthoganalytics.capture", side_effect=RuntimeError("capture down")),
        patch(f"{PIPELINE_MODULE_PATH}.posthoganalytics.capture_exception") as capture_exception,
    ):
        await capture_signal_dropped_activity(
            CaptureSignalDroppedInput(
                team_id=ateam.id,
                source_product="error_tracking",
                source_type="issue_created",
                source_id="issue-1",
                weight=0.5,
                stage="grouping_sequential",
                error_type="TimeoutError",
                error="LLM match timed out",
            )
        )

    capture_exception.assert_called_once()


@pytest.mark.asyncio
async def test_helper_noops_when_patch_not_applied():
    with (
        patch(f"{PIPELINE_MODULE_PATH}.workflow.patched", return_value=False),
        patch(f"{PIPELINE_MODULE_PATH}.workflow.execute_activity", new_callable=AsyncMock) as execute_activity,
    ):
        await capture_signal_dropped(_make_signal(), ValueError("boom"), stage="grouping_sequential")

    execute_activity.assert_not_called()


@pytest.mark.asyncio
async def test_helper_schedules_capture_activity():
    with (
        patch(f"{PIPELINE_MODULE_PATH}.workflow.patched", return_value=True),
        patch(f"{PIPELINE_MODULE_PATH}.workflow.execute_activity", new_callable=AsyncMock) as execute_activity,
    ):
        await capture_signal_dropped(_make_signal(team_id=42), ValueError("boom"), stage="grouping_parallel")

    execute_activity.assert_called_once()
    activity_input = execute_activity.call_args.args[1]
    assert activity_input.team_id == 42
    assert activity_input.stage == "grouping_parallel"
    assert activity_input.error_type == "ValueError"
    assert activity_input.error == "boom"
    # extra is flattened before scheduling so nested customer-derived payloads
    # never enter workflow history via the activity input
    assert activity_input.extra == {"skill_name": "error-tracking"}


@pytest.mark.asyncio
async def test_helper_swallows_activity_failure():
    with (
        patch(f"{PIPELINE_MODULE_PATH}.workflow.patched", return_value=True),
        patch(
            f"{PIPELINE_MODULE_PATH}.workflow.execute_activity",
            new_callable=AsyncMock,
            side_effect=RuntimeError("activity failed"),
        ),
    ):
        await capture_signal_dropped(_make_signal(), ValueError("boom"), stage="grouping_sequential")


@pytest.mark.parametrize(
    "error,expected_type,expected_message",
    [
        (ValueError("bad input"), "ValueError", "bad input"),
        (
            _make_activity_error(ApplicationError("the connection is closed", type="OperationalError")),
            "OperationalError",
            "the connection is closed",
        ),
        (
            _make_activity_error(ApplicationError("untyped failure")),
            "ApplicationError",
            "untyped failure",
        ),
        (ValueError("x" * 2000), "ValueError", "x" * 500),
        (
            # Pydantic-style multi-line validation error: continuation lines carry
            # customer-derived input values and must not be forwarded
            _make_activity_error(
                ApplicationError(
                    "1 validation error for SignalMatchResult\nreport_id\n  Input should be a valid string [input_value={'customer': 'secret'}]",
                    type="ValidationError",
                )
            ),
            "ValidationError",
            "1 validation error for SignalMatchResult",
        ),
    ],
)
def test_summarize_drop_error(error, expected_type, expected_message):
    error_type, message = _summarize_drop_error(error)
    assert error_type == expected_type
    assert expected_message in message
    assert "\n" not in message
