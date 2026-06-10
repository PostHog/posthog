import pytest
from unittest.mock import patch

from temporalio.exceptions import ActivityError, ApplicationError

from products.signals.backend.temporal.drop_telemetry import (
    CaptureSignalDroppedInput,
    _summarize_drop_error,
    capture_signal_dropped_activity,
)

PIPELINE_MODULE_PATH = "products.signals.backend.temporal.drop_telemetry"


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
                extra={"skill_name": "error-tracking", "task_run_id": "task-run-1"},
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
    assert kwargs["properties"]["extra"]["skill_name"] == "error-tracking"
    assert kwargs["properties"]["extra"]["task_run_id"] == "task-run-1"
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


class TestSummarizeDropError:
    def test_plain_exception(self):
        error_type, message = _summarize_drop_error(ValueError("bad input"))
        assert error_type == "ValueError"
        assert message == "bad input"

    def test_activity_error_unwraps_application_error_type(self):
        cause = ApplicationError("the connection is closed", type="OperationalError")
        error_type, message = _summarize_drop_error(_make_activity_error(cause))
        assert error_type == "OperationalError"
        assert "the connection is closed" in message

    def test_message_truncated(self):
        _, message = _summarize_drop_error(ValueError("x" * 2000))
        assert len(message) == 500
