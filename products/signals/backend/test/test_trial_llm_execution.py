import asyncio
from threading import Barrier
from uuid import uuid4

import pytest
from unittest.mock import patch

from products.signals.backend.trial_llm_execution import trial_llm_execution
from products.signals.backend.trial_reports import report_trial_context


@pytest.mark.asyncio
async def test_trial_gateway_preparation_does_not_serialize_concurrent_activities() -> None:
    barrier = Barrier(2)
    report_id = str(uuid4())

    def prepare(*, team_id: int | None, model: str) -> None:
        assert report_trial_context.get() == (team_id, report_id)
        barrier.wait(timeout=5)

    async def execute() -> None:
        token = report_trial_context.set((1, report_id))
        try:
            async with trial_llm_execution(team_id=1, model="test-model"):
                pass
        finally:
            report_trial_context.reset(token)

    with patch("products.signals.backend.trial_llm_execution.TrialLLMExecution.prepare", side_effect=prepare):
        await asyncio.gather(execute(), execute())
