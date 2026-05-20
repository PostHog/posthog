import random

import pytest
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team

from products.signals.backend.models import SignalSourceConfig
from products.signals.backend.temporal.emit_eval_signal import (
    EmitEvalSignalInputs,
    EvalSignalSummary,
    _looks_like_internal_signals_call,
    emit_eval_signal_activity,
)


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"SignalsEvalOrg-{random.randint(1, 99999)}",
        is_ai_data_processing_approved=True,
    )
    yield organization
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsEvalTeam-{random.randint(1, 99999)}",
    )
    yield team
    await sync_to_async(team.delete)()


def _make_inputs(team_id: int = 1, **overrides) -> EmitEvalSignalInputs:
    base: dict = {
        "team_id": team_id,
        "evaluation_id": "eval-1",
        "evaluation_name": "Unhappy User",
        "evaluation_prompt": "Is the user unhappy?",
        "event_uuid": "00000000-0000-0000-0000-000000000001",
        "event_type": "$ai_generation",
        "trace_id": "trace-1",
        "reasoning": "User expressed frustration about repeated state loss.",
        "model": "gpt-5-mini",
        "provider": "openai",
        "service": "",
        "event_input_preview": "",
    }
    base.update(overrides)
    return EmitEvalSignalInputs(**base)


class TestLooksLikeInternalSignalsCall:
    @pytest.mark.parametrize(
        "service, expected",
        [
            ("temporal-worker-video-export", True),
            ("temporal-worker-llm-analytics", False),
            ("posthog-web", False),
            ("", False),
        ],
    )
    def test_service_denylist(self, service: str, expected: bool):
        assert _looks_like_internal_signals_call(_make_inputs(service=service)) is expected

    @pytest.mark.parametrize(
        "input_preview, expected",
        [
            (
                "user: You are a security classifier for an automated signal processing pipeline. Tell me about this.",
                True,
            ),
            (
                "system: You are a senior engineer reviewing whether a group of signals belongs in a single pull request.",
                True,
            ),
            (
                "system: You are a signal grouping assistant. Decide if signals match.",
                True,
            ),
            (
                "EXISTING GROUP:\n- Title: X\nNEW SIGNAL PROPOSED FOR ADDITION:\n- Source: signals",
                True,
            ),
            (
                "DISCOVERY STRENGTH (groups found by multiple independent queries are more likely related):\n...",
                True,
            ),
            (
                "user: I keep getting redirected and losing my work every time I try to save.",
                False,
            ),
            (
                "",
                False,
            ),
        ],
        ids=[
            "safety_filter_prompt",
            "specificity_check_prompt",
            "matching_prompt",
            "specificity_user_prompt_marker",
            "matching_user_prompt_marker",
            "real_end_user_complaint",
            "empty_preview",
        ],
    )
    def test_prompt_signature_fingerprint(self, input_preview: str, expected: bool):
        assert _looks_like_internal_signals_call(_make_inputs(event_input_preview=input_preview)) is expected

    def test_service_check_short_circuits_before_content_check(self):
        # Service alone is enough to flag the call, no preview needed.
        assert (
            _looks_like_internal_signals_call(
                _make_inputs(service="temporal-worker-video-export", event_input_preview="")
            )
            is True
        )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestEmitEvalSignalActivityGuard:
    """The activity must bail out before doing the summarizer LLM call when the source
    generation came from PostHog's own signals pipeline. The summarizer is the most
    expensive step, so we patch it and assert it's never awaited on the drop paths.
    """

    async def _enable_eval(self, team, evaluation_id: str = "eval-1") -> None:
        await sync_to_async(SignalSourceConfig.objects.create)(
            team=team,
            source_product=SignalSourceConfig.SourceProduct.LLM_ANALYTICS,
            source_type=SignalSourceConfig.SourceType.EVALUATION,
            enabled=True,
            config={"evaluation_ids": [evaluation_id]},
        )

    async def test_internal_service_short_circuits_before_summarizer(self, ateam):
        await self._enable_eval(ateam)
        inputs = _make_inputs(team_id=ateam.id, service="temporal-worker-video-export")
        with (
            patch(
                "products.signals.backend.temporal.emit_eval_signal.summarize_eval_for_signal",
                new_callable=AsyncMock,
            ) as mock_summarize,
            patch("products.signals.backend.api.emit_signal", new_callable=AsyncMock) as mock_emit,
        ):
            await emit_eval_signal_activity(inputs)
        mock_summarize.assert_not_awaited()
        mock_emit.assert_not_awaited()

    async def test_internal_prompt_signature_short_circuits_before_summarizer(self, ateam):
        await self._enable_eval(ateam)
        inputs = _make_inputs(
            team_id=ateam.id,
            event_input_preview=(
                "user: NEW SIGNAL PROPOSED FOR ADDITION:\n- Source: signals/exception\n- Description: ..."
            ),
        )
        with (
            patch(
                "products.signals.backend.temporal.emit_eval_signal.summarize_eval_for_signal",
                new_callable=AsyncMock,
            ) as mock_summarize,
            patch("products.signals.backend.api.emit_signal", new_callable=AsyncMock) as mock_emit,
        ):
            await emit_eval_signal_activity(inputs)
        mock_summarize.assert_not_awaited()
        mock_emit.assert_not_awaited()

    async def test_external_generation_still_reaches_summarizer_and_emits(self, ateam):
        # A real end-user $ai_generation has neither a denylisted service nor a
        # signals-pipeline prompt signature, so the activity proceeds to summarize
        # and (significance >= 0.1) emits a signal.
        await self._enable_eval(ateam)
        inputs = _make_inputs(
            team_id=ateam.id,
            service="customer-app-prod",
            event_input_preview="user: hi can you help me with my order",
        )
        summary = EvalSignalSummary(
            title="Customer needs help",
            description="Customer is asking for order help.",
            significance=0.5,
        )
        with (
            patch(
                "products.signals.backend.temporal.emit_eval_signal.summarize_eval_for_signal",
                new_callable=AsyncMock,
                return_value=summary,
            ) as mock_summarize,
            patch("products.signals.backend.api.emit_signal", new_callable=AsyncMock) as mock_emit,
        ):
            await emit_eval_signal_activity(inputs)
        mock_summarize.assert_awaited_once()
        mock_emit.assert_awaited_once()
