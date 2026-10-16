from __future__ import annotations

from typing import Any

import pytest
from unittest.mock import AsyncMock, Mock

from products.posthog_ai.eval_harness.engines.posthog import PostHogEngine
from products.posthog_ai.eval_harness.engines.types import CaseHooks, CaseSpec, ExperimentSpec


@pytest.mark.asyncio
@pytest.mark.parametrize("no_send_logs", [False, True])
async def test_posthog_engine_scores_without_braintrust_uploads(
    monkeypatch: pytest.MonkeyPatch, no_send_logs: bool
) -> None:
    monkeypatch.setenv("BRAINTRUST_API_KEY", "synthetic-key-that-must-not-be-used")
    monkeypatch.setattr("braintrust.framework.init_experiment", Mock(side_effect=AssertionError("Braintrust upload")))
    on_results = AsyncMock()

    async def task(input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        return {"answer": input["value"]}

    async def score(output: dict[str, Any]) -> float:
        return float(output["answer"] == 3)

    result = await PostHogEngine().run_experiment(
        ExperimentSpec(
            project_name="notebook-test",
            cases=[CaseSpec(input={"name": "arithmetic", "value": 3})],
            task=task,
            scorers=[score],
            trial_count=1,
            is_public=True,
            no_send_logs=no_send_logs,
            metadata={},
            on_results=on_results,
        )
    )

    assert result.results[0].scores == {"score": 1.0}
    assert result.summary.engine_name == "posthog"
    assert result.summary.experiment_url is None
    on_results.assert_awaited_once_with(result)
