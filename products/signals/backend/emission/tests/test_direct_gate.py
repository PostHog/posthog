import uuid
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from products.signals.backend.contracts import DIRECT_STEERABLE_SOURCES
from products.signals.backend.emission.direct_gate import steering_filters_signal
from products.signals.backend.emission.registry import _SIGNAL_TABLE_CONFIGS
from products.signals.backend.facade.api import emit_signal

GATE_MODULE_PATH = "products.signals.backend.emission.direct_gate"
FACADE_MODULE_PATH = "products.signals.backend.facade.api"


def _make_llm_response(verdict: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = verdict
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "end_turn"
    return response


def _make_team() -> MagicMock:
    return MagicMock(id=1, uuid=uuid.uuid4())


async def _run_gate(source_config: dict, *, verdict: str = "NOT_ACTIONABLE", extra: dict | None = None):
    """Run the gate against a stubbed source config and LLM, returning (dropped, anthropic client)."""
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_make_llm_response(verdict))
    client.__aenter__.return_value = client
    with (
        patch(f"{GATE_MODULE_PATH}.afetch_source_config", AsyncMock(return_value=source_config)),
        patch(f"{GATE_MODULE_PATH}.build_async_anthropic_client", return_value=client),
        patch(f"{GATE_MODULE_PATH}.resolve_ai_gateway_config", return_value=None),
        patch(f"{GATE_MODULE_PATH}.capture_pipeline_stage") as capture,
    ):
        dropped = await steering_filters_signal(
            team=_make_team(),
            organization=MagicMock(),
            source_product="error_tracking",
            source_type="issue_created",
            source_id="issue-1",
            description="TypeError: undefined is not a function",
            weight=1.0,
            extra=extra or {"fingerprint": "abc123"},
        )
    return dropped, client, capture


class TestSteeringFiltersSignal:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "source_config",
        [{}, {"steering": "   "}, {"steering": None}, {"other_key": "value"}, {"default_not_actionable": True}],
        ids=["no_config", "blank_steering", "null_steering", "unrelated_keys", "retired_posture_flag_only"],
    )
    async def test_a_source_with_no_steering_keeps_every_signal_and_never_calls_the_llm(self, source_config):
        # Direct sources emitted straight through before this gate existed. A team that wrote no
        # rules must keep that behavior exactly, and must not start paying for an LLM call per signal.
        dropped, client, _ = await _run_gate(source_config)

        assert dropped is False
        client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_steering_drops_the_signal_and_reports_it_as_filtered(self):
        dropped, client, capture = await _run_gate({"steering": "Ignore errors from localhost."})

        assert dropped is True
        prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "Ignore errors from localhost." in prompt
        # `extra` reaches the gate too, so a rule can name a fact the description does not carry.
        assert '"fingerprint": "abc123"' in prompt
        event, _team, _organization, output, properties = capture.call_args.args
        assert event == "signal_data_source_filtered"
        assert properties == {"steering_applied": True}
        assert output.source_id == "issue-1"

    @pytest.mark.asyncio
    async def test_a_row_carrying_the_retired_posture_flag_still_keeps_the_lenient_posture(self):
        # The flag tells the model to keep only records that clearly match the prompt's ACTIONABLE
        # criteria. This prompt states none, so honoring it here would drop nearly everything.
        _dropped, client, _capture = await _run_gate(
            {"steering": "Ignore errors from localhost.", "default_not_actionable": True}
        )

        prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "When in doubt, classify as ACTIONABLE." in prompt
        assert "err on the side of filtering" not in prompt

    @pytest.mark.asyncio
    async def test_a_steered_signal_the_rules_do_not_exclude_still_emits(self):
        dropped, _client, capture = await _run_gate({"steering": "Ignore errors from localhost."}, verdict="ACTIONABLE")

        assert dropped is False
        capture.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_stalled_gateway_gives_up_on_the_gate_rather_than_holding_the_emit(self):
        # The caller emits inside its own activity timeout. Waiting out every retry would blow that
        # budget, fail the activity, and have Temporal replay the emit instead of sending it.
        async def never_answers(**_kwargs):
            await asyncio.sleep(60)

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=never_answers)
        client.__aenter__.return_value = client
        with (
            patch(f"{GATE_MODULE_PATH}.afetch_source_config", AsyncMock(return_value={"steering": "Skip noise."})),
            patch(f"{GATE_MODULE_PATH}.build_async_anthropic_client", return_value=client),
            patch(f"{GATE_MODULE_PATH}.resolve_ai_gateway_config", return_value=None),
            patch(f"{GATE_MODULE_PATH}.GATE_TIMEOUT_SECONDS", 0.01),
        ):
            dropped = await steering_filters_signal(
                team=_make_team(),
                organization=MagicMock(),
                source_product="error_tracking",
                source_type="issue_created",
                source_id="issue-1",
                description="TypeError: undefined is not a function",
                weight=1.0,
                extra={},
            )

        assert dropped is False

    @pytest.mark.asyncio
    async def test_the_gate_fails_open_when_the_llm_client_cannot_be_built(self):
        # Dropping signals whenever the gateway is unreachable would lose real problems silently,
        # which is worse than letting a noisy one through.
        with (
            patch(f"{GATE_MODULE_PATH}.afetch_source_config", AsyncMock(return_value={"steering": "Skip noise."})),
            patch(f"{GATE_MODULE_PATH}.build_async_anthropic_client", side_effect=RuntimeError("no gateway")),
        ):
            dropped = await steering_filters_signal(
                team=_make_team(),
                organization=MagicMock(),
                source_product="error_tracking",
                source_type="issue_created",
                source_id="issue-1",
                description="TypeError: undefined is not a function",
                weight=1.0,
                extra={},
            )

        assert dropped is False


class TestEmitSignalWiring:
    @pytest.mark.asyncio
    async def test_emit_signal_consults_the_gate_and_drops_a_filtered_signal_before_queueing(self):
        # The gate reaches production only through the membership check in `emit_signal`, whose
        # `(source_product, source_type)` tuple has to match the enum values the set is built from.
        team = _make_team()
        team.organization.is_ai_data_processing_approved = True
        connect = AsyncMock()
        with (
            patch(f"{FACADE_MODULE_PATH}.SignalSourceConfig") as source_config,
            patch(f"{FACADE_MODULE_PATH}.posthoganalytics"),
            patch(f"{FACADE_MODULE_PATH}.async_connect", connect),
            patch(f"{GATE_MODULE_PATH}.steering_filters_signal", AsyncMock(return_value=True)) as gate,
        ):
            source_config.is_source_enabled.return_value = True
            await emit_signal(
                team=team,
                source_product="error_tracking",
                source_type="issue_created",
                source_id="record-1",
                description="Something happened",
                extra={"fingerprint": "abc123"},
            )

        assert gate.called
        # A signal the gate drops never reaches Temporal, so it cannot become a report.
        assert not connect.called


def test_no_pipeline_source_is_listed_as_directly_steerable():
    # A source registered for the batch pipeline already runs its own steered actionability gate.
    # Listing it here too would judge every one of its records twice, at twice the LLM cost.
    pipeline_sources = {(config.source_product, config.source_type) for config in _SIGNAL_TABLE_CONFIGS.values()}

    assert DIRECT_STEERABLE_SOURCES.isdisjoint(pipeline_sources)
