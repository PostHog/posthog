from dataclasses import replace
from functools import partial

import pytest
from unittest.mock import MagicMock, patch

from temporalio.common import RetryPolicy
from temporalio.testing import ActivityEnvironment

from products.signals.backend.temporal.agentic.select_repository import (
    _capture_repo_research_event,
    _repo_selection_failure_reason,
)
from products.tasks.backend.facade.agents import EmptyAgentTurnError, SandboxRunFailed


@pytest.mark.parametrize(
    "attempt,result,error,reason,final",
    [
        (1, "failed", ValueError("private model output"), "output_parse_failed", False),
        (2, "failed", ValueError("private model output"), "output_parse_failed", True),
        (1, "failed", EmptyAgentTurnError("empty", total_lines=0, printed_lines=0), "empty_output", False),
        (1, "failed", SandboxRunFailed("unavailable", error_type=None), "sandbox_failed", False),
        (2, "selected", None, None, True),
        (1, "no_repo", None, None, True),
    ],
)
def test_attempt_telemetry_distinguishes_retries_from_final_outcomes(attempt, result, error, reason, final) -> None:
    environment = ActivityEnvironment()
    environment.info = replace(
        environment.info,
        attempt=attempt,
        retry_policy=RetryPolicy(maximum_attempts=2),
        workflow_run_id="example-workflow-run",
    )
    with (
        patch("products.signals.backend.temporal.agentic.select_repository.posthoganalytics.capture") as capture,
        patch("products.signals.backend.temporal.agentic.select_repository.groups", return_value={}),
    ):
        environment.run(
            partial(
                _capture_repo_research_event,
                "signals_repo_research_completed",
                MagicMock(),
                MagicMock(),
                "example-report",
                result=result,
                failure_reason=_repo_selection_failure_reason(error, agent_started=True) if error else None,
                error=error,
                task_id="example-task",
                task_run_id="example-run",
            )
        )
    properties = capture.call_args.kwargs["properties"]
    assert properties["workflow_run_id"] == "example-workflow-run"
    assert properties["attempt"] == attempt
    assert properties["is_final_attempt"] is final
    assert properties.get("failure_reason") == reason
    assert properties["task_run_id"] == "example-run"
    assert "private model output" not in str(properties)
