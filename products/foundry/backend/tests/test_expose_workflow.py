import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from unittest.mock import patch

from django.conf import settings

from asgiref.sync import sync_to_async
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.foundry.backend.facade import api
from products.foundry.backend.facade.contracts import BetDTO, CreateBetInput
from products.foundry.backend.facade.enums import BetEventKind
from products.foundry.backend.logic.scout import GuardrailEvaluation
from products.foundry.backend.models import BetEvent
from products.foundry.backend.temporal.activities import record_bet_event_activity
from products.foundry.backend.temporal.expose_activities import evaluate_guardrails_activity, set_flag_rollout_activity
from products.foundry.backend.temporal.expose_workflow import (
    ExposureStepSpec,
    FoundryExposeBetInput,
    FoundryExposeBetWorkflow,
)

ACTIVITIES: list[Callable[..., Any]] = [
    record_bet_event_activity,
    set_flag_rollout_activity,
    evaluate_guardrails_activity,
]


def _funded_bet(team, user, *, guardrails=None) -> BetDTO:
    bet = api.create_bet(
        CreateBetInput(
            team_id=team.id,
            slug=f"expose-workflow-test-{uuid.uuid4().hex[:8]}",
            hypothesis="a guarded rollout ramp advances the flag",
            success_metric={"name": "conversion"},
            guardrails=guardrails or [],
            budget={},
            exposure_plan={},
            sources=[],
        ),
        user=user,
    )
    return api.fund_bet(team.id, bet.id, user=user)


def _flag_rollout_pct(flag_id: int) -> float:
    flag = FeatureFlag.objects.get(id=flag_id)
    return flag.filters["groups"][0]["rollout_percentage"]


def _flag_active(flag_id: int) -> bool:
    return FeatureFlag.objects.get(id=flag_id).active


def _events_of_kind(bet_id, kind: BetEventKind) -> list[dict]:
    return [e.payload for e in BetEvent.objects.filter(bet_id=bet_id, kind=kind).order_by("created_at")]


async def _run_expose(
    *, bet: BetDTO, team, steps: list[ExposureStepSpec], guardrails: list[dict] | None = None
) -> dict:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=settings.FOUNDRY_TASK_QUEUE,
            workflows=[FoundryExposeBetWorkflow],
            activities=ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=10),
        ):
            return await env.client.execute_workflow(
                FoundryExposeBetWorkflow.run,
                FoundryExposeBetInput(
                    bet_id=str(bet.id),
                    team_id=team.id,
                    bet_slug=bet.slug,
                    flag_id=bet.feature_flag_id,
                    guardrails=guardrails or [],
                    steps=steps,
                ),
                id=f"foundry-expose-test-{uuid.uuid4()}",
                task_queue=settings.FOUNDRY_TASK_QUEUE,
            )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_multi_step_ramp_advances_flag_rollout_and_activates_on_first_step(team, user) -> None:
    bet = await sync_to_async(_funded_bet)(team, user)
    assert await sync_to_async(_flag_active)(bet.feature_flag_id) is False  # a freshly-funded experiment flag
    steps = [
        ExposureStepSpec(rollout_pct=10, min_hours=0.001),
        ExposureStepSpec(rollout_pct=100, min_hours=0.001),
    ]

    result = await _run_expose(bet=bet, team=team, steps=steps)

    assert result["outcome"] == "completed"
    assert await sync_to_async(_flag_rollout_pct)(bet.feature_flag_id) == 100
    assert await sync_to_async(_flag_active)(bet.feature_flag_id) is True
    advanced = await sync_to_async(_events_of_kind)(bet.id, BetEventKind.EXPOSURE_ADVANCED)
    assert [(e["step"], e["rollout_pct"]) for e in advanced] == [(0, 10), (1, 100)]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_guardrail_breach_halts_the_ramp_and_resets_rollout_to_zero(team, user) -> None:
    guardrail = {
        "name": "error rate",
        "metric": {"metric_kind": "error_rate", "query_ref": "abc"},
        "threshold": 0.05,
        "direction": "above",
    }
    bet = await sync_to_async(_funded_bet)(team, user, guardrails=[guardrail])
    steps = [
        ExposureStepSpec(rollout_pct=50, min_hours=0.001),
        ExposureStepSpec(rollout_pct=100, min_hours=0.001),
    ]

    with patch(
        "products.foundry.backend.logic.scout.evaluate_guardrails",
        return_value=[
            GuardrailEvaluation(name="error rate", parameterized=True, breached=True, detail="0.08 vs threshold 0.05")
        ],
    ):
        result = await _run_expose(bet=bet, team=team, steps=steps, guardrails=[guardrail])

    assert result == {"outcome": "halted", "step": 0}
    assert await sync_to_async(_flag_rollout_pct)(bet.feature_flag_id) == 0
    halted = await sync_to_async(_events_of_kind)(bet.id, BetEventKind.EXPOSURE_HALTED)
    assert halted[0]["reason"] == "guardrail_breach"
    assert halted[0]["guardrail"] == "error rate"
    # Never reached step 1's advance.
    advanced = await sync_to_async(_events_of_kind)(bet.id, BetEventKind.EXPOSURE_ADVANCED)
    assert len(advanced) == 1


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_no_breach_advances_past_a_parameterized_guardrail(team, user) -> None:
    guardrail = {
        "name": "error rate",
        "metric": {"metric_kind": "error_rate", "query_ref": "abc"},
        "threshold": 0.05,
        "direction": "above",
    }
    bet = await sync_to_async(_funded_bet)(team, user, guardrails=[guardrail])

    with patch(
        "products.foundry.backend.logic.scout.evaluate_guardrails",
        return_value=[
            GuardrailEvaluation(name="error rate", parameterized=True, breached=False, detail="0.01 vs threshold 0.05")
        ],
    ):
        result = await _run_expose(
            bet=bet, team=team, steps=[ExposureStepSpec(rollout_pct=100, min_hours=0.001)], guardrails=[guardrail]
        )

    assert result == {"outcome": "completed"}
    assert await sync_to_async(_flag_rollout_pct)(bet.feature_flag_id) == 100


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_step_opting_out_of_halt_skips_the_guardrail_check_entirely(team, user) -> None:
    """halt_on_guardrail_breach: false must not even evaluate guardrails for that step —
    a breaching guardrail must not halt it, and the check must never run at all."""
    guardrail = {
        "name": "error rate",
        "metric": {"metric_kind": "error_rate", "query_ref": "abc"},
        "threshold": 0.05,
        "direction": "above",
    }
    bet = await sync_to_async(_funded_bet)(team, user, guardrails=[guardrail])

    with patch("products.foundry.backend.logic.scout.evaluate_guardrails") as mock_evaluate:
        result = await _run_expose(
            bet=bet,
            team=team,
            steps=[ExposureStepSpec(rollout_pct=100, min_hours=0.001, halt_on_guardrail_breach=False)],
            guardrails=[guardrail],
        )

    mock_evaluate.assert_not_called()
    assert result == {"outcome": "completed"}
    assert await sync_to_async(_flag_rollout_pct)(bet.feature_flag_id) == 100
