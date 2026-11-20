from typing import Any

import pytest
from unittest.mock import patch

from parameterized import parameterized
from syrupy.extensions.json import JSONSnapshotExtension

from products.tasks.backend import model_catalog
from products.tasks.backend.constants import get_required_model_flag
from products.tasks.backend.facade.model_catalogue import GatewayModel, available_model_choices, runtime_adapter_for
from products.tasks.backend.facade.model_listing_testing import serve_gateway_listing
from products.tasks.backend.logic.services import gateway_model_pin
from products.tasks.backend.models import Task
from products.tasks.backend.temporal.process_task.utils import (
    ReasoningEffort,
    RuntimeAdapter,
    get_reasoning_effort_error,
)


def _resolved_catalog() -> dict[str, Any]:
    """The catalog as data, read back through the public resolver rather than the tables.

    Every value here is what a caller actually gets, so the snapshot moves when resolution
    changes even if the literals did not.
    """
    return {
        "reasoning_efforts": list(model_catalog.REASONING_EFFORTS),
        "runtimes": [
            {"runtime": option.runtime, "runtime_adapter": option.runtime_adapter, "label": option.label}
            for option in model_catalog.RUNTIME_OPTIONS
        ],
        "runtime_adapters": {
            adapter: {
                "provider": model_catalog.PROVIDER_BY_RUNTIME_ADAPTER[adapter],
                "default_model": model_catalog.DEFAULT_MODEL_BY_RUNTIME_ADAPTER[adapter],
                "fallback_reasoning_efforts": list(
                    model_catalog.FALLBACK_REASONING_EFFORTS_BY_RUNTIME_ADAPTER.get(adapter, ())
                ),
                "models": {
                    model_id: {
                        "reasoning_efforts": list(model_catalog.reasoning_efforts_for(adapter, model_id)),
                        "cost_multiplier": model_catalog.cost_multiplier_label(model_id),
                        "supports_1m_context": model_catalog.supports_1m_context(model_id),
                        "supports_fast_mode": model_catalog.supports_fast_mode(model_id),
                        "offered": model_catalog.is_offered_model(model_id),
                    }
                    for model_id in model_catalog.models_for_runtime_adapter(adapter)
                },
            }
            for adapter in model_catalog.RUNTIME_ADAPTERS
        },
        "model_families": [
            {"runtime_adapter": adapter, "prefix": prefix, "reasoning_efforts": list(efforts)}
            for adapter, prefix, efforts in model_catalog.FAMILY_REASONING_EFFORTS
        ],
        "reasoning_effort_labels": dict(model_catalog.REASONING_EFFORT_LABELS),
        "capability_ladders": {
            adapter: [{"model": notch.model, "effort": notch.effort} for notch in ladder]
            for adapter, ladder in model_catalog.CAPABILITY_LADDER_BY_RUNTIME_ADAPTER.items()
        },
    }


def test_every_model_resolves_to_the_recorded_triple(snapshot) -> None:
    # The parametrized cases below pin the resolution rules; this pins the whole answer for
    # every model at once, so a change to a shared effort tuple, a default, or a provider
    # lands in review as a readable data diff instead of one line of Python.
    # Refresh with: pytest products/tasks/backend/tests/test_model_catalog.py --snapshot-update
    assert _resolved_catalog() == snapshot(extension_class=JSONSnapshotExtension)


def test_every_runtime_adapter_has_catalog_models() -> None:
    for adapter in RuntimeAdapter:
        assert model_catalog.models_for_runtime_adapter(adapter.value), (
            f"runtime adapter '{adapter.value}' has no models in the catalog, so every picker "
            f"and validator would treat it as serving nothing"
        )


def test_every_catalog_effort_is_a_known_reasoning_effort() -> None:
    known = {effort.value for effort in ReasoningEffort}
    used = {effort for entry in model_catalog.MODELS for effort in entry.reasoning_efforts}
    assert used <= known, f"catalog names efforts the ReasoningEffort enum lacks: {sorted(used - known)}"


def test_reasoning_effort_enum_covers_the_catalog() -> None:
    assert set(model_catalog.REASONING_EFFORTS) <= {effort.value for effort in ReasoningEffort}


def test_every_effort_has_a_label() -> None:
    assert set(model_catalog.REASONING_EFFORT_LABELS) == set(model_catalog.REASONING_EFFORTS), (
        "a depth with no label renders as its raw id in every picker"
    )


def test_every_ladder_rung_is_one_a_run_can_actually_use() -> None:
    # A surface filters the ladder against what the gateway serves, which cannot hide a rung
    # the catalog itself contradicts — that one reaches the picker and fails on send.
    for adapter, ladder in model_catalog.CAPABILITY_LADDER_BY_RUNTIME_ADAPTER.items():
        for notch in ladder:
            assert notch.model in model_catalog.models_for_runtime_adapter(adapter), (
                f"'{adapter}' ladder names '{notch.model}', which that adapter does not drive"
            )
            assert notch.effort in model_catalog.reasoning_efforts_for(adapter, notch.model), (
                f"'{notch.model}' does not support '{notch.effort}', so that rung's run would be rejected"
            )


def test_every_runtime_adapter_has_a_capability_ladder() -> None:
    assert set(model_catalog.CAPABILITY_LADDER_BY_RUNTIME_ADAPTER) == set(model_catalog.RUNTIME_ADAPTERS), (
        "an adapter with no ladder leaves its picker without a Faster/Smarter slider"
    )


def test_runtime_options_agree_with_the_task_runtime_column() -> None:
    assert list(Task.Runtime.values) == list(model_catalog.RUNTIMES)


def test_every_runtime_adapter_is_offered_exactly_once() -> None:
    offered = [option.runtime_adapter for option in model_catalog.RUNTIME_OPTIONS if option.runtime_adapter]
    assert sorted(offered) == sorted(model_catalog.RUNTIME_ADAPTERS)


@pytest.mark.parametrize(
    "adapter,model,expected",
    [
        ("claude", "claude-sonnet-4-6", ("low", "medium", "high")),
        ("claude", "moonshotai/kimi-k3", ()),
        ("claude", "claude-imaginary-9", ()),
        ("claude", "anthropic/claude-sonnet-4-6", ("low", "medium", "high")),
        ("codex", "GPT-5.5", ("low", "medium", "high", "xhigh")),
        ("codex", "gpt-5.5-codex", ("low", "medium", "high", "xhigh")),
        ("codex", "gpt-9", ("low", "medium", "high")),
        ("codex", "gpt-5.6-sol", ("low", "medium", "high", "xhigh", "max")),
    ],
    ids=[
        "exact_id",
        "no_effort_control",
        "unknown_claude_model_has_no_fallback",
        "provider_qualified_id",
        "uppercase_id",
        "codex_family_variant",
        "unknown_codex_model_falls_back",
        "exact_id_beats_family",
    ],
)
def test_efforts_resolve_by_id_then_family_then_adapter(adapter: str, model: str, expected: tuple[str, ...]) -> None:
    assert model_catalog.reasoning_efforts_for(adapter, model) == expected


@pytest.mark.parametrize(
    "model,provider_efforts,expected",
    [
        ("gpt-9-sol", ["low", "medium", "high", "xhigh", "max"], ("low", "medium", "high", "xhigh", "max")),
        ("gpt-9-sol", ["none", "minimal", "low", "high"], ("low", "high")),
        ("gpt-9-sol", ["max", "low"], ("low", "max")),
        ("gpt-9-sol", [], ()),
        (
            "claude-opus-9",
            ["low", "medium", "high", "xhigh", "max"],
            ("low", "medium", "high", "xhigh", "max", "ultracode"),
        ),
        ("claude-opus-9", ["low", "medium", "high", "max"], ("low", "medium", "high", "max")),
        ("zai-org/glm-9", ["high", "xhigh", "max"], ("high", "xhigh", "max")),
    ],
    ids=[
        "every_tier",
        "tiers_the_catalog_lacks_are_dropped",
        "catalog_order",
        "no_effort_control",
        "claude_with_xhigh_gains_ultracode",
        "claude_without_xhigh",
        "hosted_model_with_xhigh_gains_nothing",
    ],
)
def test_provider_efforts_map_onto_catalog_tiers(
    model: str, provider_efforts: list[str], expected: tuple[str, ...]
) -> None:
    assert model_catalog.reasoning_efforts_from_provider(model, provider_efforts) == expected


def test_default_model_is_one_the_catalog_serves() -> None:
    for adapter, model in model_catalog.DEFAULT_MODEL_BY_RUNTIME_ADAPTER.items():
        assert model in model_catalog.models_for_runtime_adapter(adapter), (
            f"the default model for '{adapter}' is not in its catalog, so a run that pins no model "
            f"would resolve to one validation rejects"
        )


def test_cost_baseline_is_a_model_the_catalog_prices() -> None:
    assert model_catalog.cost_for_model(model_catalog.COST_BASELINE_MODEL) is not None, (
        f"the cost baseline '{model_catalog.COST_BASELINE_MODEL}' carries no cost, so every multiplier "
        f"raises and no picker can render"
    )


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-sonnet-5", "1×"),
        ("claude-opus-5", "2.5×"),
        ("anthropic/claude-opus-5", "2.5×"),
        ("gpt-5.6-sol", "≈2.8×"),
        ("gpt-6.1-sol", "1× base"),
        ("zai-org/glm-5.3-flash", "≈0.06×"),
        ("gpt-5", None),
        ("claude-imaginary-9", None),
    ],
    ids=[
        "baseline_is_one",
        "input_and_output_agree",
        "provider_qualified_id",
        "diverging_rates_are_approximate",
        "tiered_model_marks_base_rate",
        "cheap_model_keeps_two_decimals",
        "unpriced_model",
        "unknown_model",
    ],
)
def test_cost_multiplier_reads_against_the_baseline(model: str, expected: str | None) -> None:
    assert model_catalog.cost_multiplier_label(model) == expected


def test_tiered_cost_summary_describes_both_rates() -> None:
    cost = model_catalog.cost_for_model("gpt-6.1-sol")
    assert cost is not None
    assert model_catalog.format_cost_rates(cost) == (
        "Per 1M tokens: $2 input/$10 output to 272K; $4 input/$15 output above"
    )


def test_labels_are_set_only_where_the_derived_name_is_wrong() -> None:
    # A pin that the formatter would produce anyway is dead weight that outlives the
    # formatter improving, so assert the property rather than restating the six strings.
    for entry in model_catalog.MODELS:
        if entry.label is None:
            continue
        assert entry.label != model_catalog.format_model_id(entry.id), (
            f"'{entry.id}' pins the label the formatter already derives; drop the pin"
        )


_BASELINE = GatewayModel(
    id="claude-sonnet-5",
    owned_by="anthropic",
    context_window=1000000,
    input_per_mtok=2.0,
    output_per_mtok=10.0,
    api_shapes=("anthropic-messages",),
)
_CODEX_SHAPES = ("openai-chat-completions", "openai-responses")


def _codex(model: str, **facts: Any) -> GatewayModel:
    return GatewayModel(id=model, owned_by="openai", context_window=1050000, api_shapes=_CODEX_SHAPES, **facts)


@pytest.mark.parametrize(
    "listed,expected",
    [
        pytest.param(
            GatewayModel(id="m", owned_by="anthropic", context_window=1, api_shapes=("anthropic-messages",)),
            "claude",
            id="anthropic_messages",
        ),
        pytest.param(
            GatewayModel(id="m", owned_by="openai", context_window=1, api_shapes=_CODEX_SHAPES),
            "codex",
            id="openai_responses",
        ),
        pytest.param(
            GatewayModel(
                id="m", owned_by="posthog", context_window=1, api_shapes=(*_CODEX_SHAPES, "anthropic-messages")
            ),
            "claude",
            id="both_shapes",
        ),
        pytest.param(
            GatewayModel(id="m", owned_by="openai", context_window=1, api_shapes=("openai-embeddings",)),
            None,
            id="a_shape_no_runtime_speaks",
        ),
        pytest.param(
            GatewayModel(id="m", owned_by="openai", context_window=1),
            "codex",
            id="no_shapes_from_a_known_owner",
        ),
        pytest.param(
            GatewayModel(id="m", owned_by="bedrock", context_window=1),
            None,
            id="no_shapes_from_an_unknown_owner",
        ),
        pytest.param(
            GatewayModel(id="another", owned_by="openai", context_window=1, api_shapes=_CODEX_SHAPES),
            None,
            id="not_listed",
        ),
    ],
)
def test_runtime_adapter_comes_from_the_listing_row(listed: GatewayModel, expected: str | None) -> None:
    with serve_gateway_listing((listed,)):
        assert runtime_adapter_for("m") == expected


class TestAvailableModelChoices:
    def test_drops_models_no_runtime_can_drive(self) -> None:
        listing = (
            GatewayModel(
                id="claude-fable-5", owned_by="anthropic", context_window=1, api_shapes=("anthropic-messages",)
            ),
            GatewayModel(
                id="gemini-2.5-pro", owned_by="google", context_window=1, api_shapes=("gemini-generate-content",)
            ),
        )
        with serve_gateway_listing(listing):
            assert [choice.model for choice in available_model_choices("signals")] == ["claude-fable-5"]

    def test_drops_models_outside_the_products_families(self) -> None:
        listing = (
            GatewayModel(
                id="claude-opus-5-5",
                owned_by="anthropic",
                context_window=1,
                family="claude-opus",
                api_shapes=("anthropic-messages",),
            ),
            _codex("gpt-4o", family="gpt-omni"),
        )
        with serve_gateway_listing(listing):
            assert [choice.model for choice in available_model_choices("posthog_code")] == ["claude-opus-5-5"]

    @pytest.mark.parametrize(
        "listed,expected",
        [
            pytest.param(
                _codex(
                    "gpt-5.4",
                    name="GPT-5.4 (listed)",
                    reasoning_efforts=("low", "medium", "high", "xhigh"),
                    input_per_mtok=8.0,
                    output_per_mtok=40.0,
                ),
                ("GPT-5.4 (listed)", ("low", "medium", "high", "xhigh"), "4×"),
                id="every_fact",
            ),
            pytest.param(
                _codex("gpt-5.4", name="GPT-5.4 (listed)"),
                ("GPT-5.4 (listed)", (), None),
                id="name_only",
            ),
            pytest.param(
                _codex("gpt-5.4", input_per_mtok=8.0),
                ("GPT-5.4", (), None),
                id="half_a_price",
            ),
            pytest.param(_codex("gpt-5.4"), ("GPT-5.4", (), None), id="no_facts"),
            pytest.param(
                GatewayModel(
                    id="claude-haiku-4-5",
                    owned_by="anthropic",
                    context_window=200000,
                    name="Claude Haiku 4.5 (latest)",
                    api_shapes=("anthropic-messages",),
                ),
                ("Claude Haiku 4.5", (), None),
                id="alias_name",
            ),
            pytest.param(
                GatewayModel(
                    id="deepseek-ai/deepseek-v4-flash-0731",
                    owned_by="posthog",
                    context_window=1048000,
                    api_shapes=(*_CODEX_SHAPES, "anthropic-messages"),
                ),
                ("Deepseek V4 Flash 0731", (), None),
                id="vendor_prefixed_id_without_a_name",
            ),
            pytest.param(
                _codex(
                    "gpt-6.2-sol",
                    name="Sol (listed)",
                    reasoning_efforts=("low",),
                    input_per_mtok=8.0,
                    output_per_mtok=40.0,
                ),
                ("Sol (listed)", ("low",), "4×"),
                id="a_cataloged_model_reads_its_listing_row_too",
            ),
        ],
    )
    def test_describes_a_model_from_its_listing_row(
        self, listed: GatewayModel, expected: tuple[str, tuple[str, ...], str | None]
    ) -> None:
        with serve_gateway_listing((_BASELINE, listed)):
            choice = next(choice for choice in available_model_choices("signals") if choice.model == listed.id)

        assert (choice.label, choice.supported_efforts, choice.cost_multiplier) == expected

    def test_quotes_no_cost_when_the_baseline_model_is_not_listed(self) -> None:
        priced = _codex("gpt-5.4", input_per_mtok=8.0, output_per_mtok=40.0)
        with serve_gateway_listing((priced,)):
            (choice,) = available_model_choices("signals")

        assert choice.cost_multiplier is None

    @pytest.mark.parametrize(
        "adapter,listed,effort,accepted",
        [
            pytest.param("codex", _codex("gpt-5.4", reasoning_efforts=("low", "max")), "max", True, id="listed_effort"),
            pytest.param("codex", _codex("gpt-5.4", reasoning_efforts=("low",)), "max", False, id="unlisted_effort"),
            pytest.param(
                "codex", _codex("gpt-5.4", reasoning_efforts=()), "low", False, id="a_model_listing_no_efforts"
            ),
            pytest.param("codex", _codex("gpt-5.4"), "low", True, id="a_model_the_gateway_does_not_describe"),
            pytest.param("codex", _codex("gpt-5.4"), "ultracode", False, id="an_effort_only_claude_code_takes"),
            pytest.param("claude", _codex("gpt-5.4"), "low", False, id="an_undescribed_model_another_runtime_drives"),
            pytest.param("codex", _codex("another-model", reasoning_efforts=("low",)), "max", True, id="not_listed"),
            pytest.param(
                "claude", _codex("gpt-5.4", reasoning_efforts=("low",)), "low", False, id="another_runtimes_model"
            ),
        ],
    )
    def test_effort_check_agrees_with_the_listing(
        self, adapter: str, listed: GatewayModel, effort: str, accepted: bool
    ) -> None:
        with serve_gateway_listing((listed,)):
            error = get_reasoning_effort_error(adapter, "gpt-5.4", effort)

        assert (error is None) is accepted


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gpt-6.2-sol", "tasks-sol-preview"),
        ("gpt-6.3-sol", "tasks-sol-preview"),
        ("openai/gpt-6.3-sol", "tasks-sol-preview"),
        ("gpt-6.3-sol-pro", "tasks-sol-preview"),
        ("gpt-6.3-astra", None),
        ("gpt-9-unlisted", None),
    ],
    ids=[
        "version_of_the_gated_family",
        "newer_version_of_the_gated_family",
        "provider_qualified_spelling",
        "suffixed_variant_of_the_gated_family",
        "another_family",
        "model_the_gateway_does_not_list",
    ],
)
def test_a_model_takes_the_rollout_flag_of_its_gateway_family(model: str, expected: str | None) -> None:
    listing = (
        _codex("gpt-6.2-sol", family="gpt-sol"),
        _codex("gpt-6.3-sol", family="gpt-sol"),
        _codex("gpt-6.3-sol-pro", family="gpt-sol"),
        _codex("gpt-6.3-astra", family="gpt-astra"),
    )
    with (
        patch.dict(gateway_model_pin.MODEL_FAMILY_ACCESS_FLAGS, {"gpt-sol": "tasks-sol-preview"}),
        serve_gateway_listing(listing),
    ):
        assert get_required_model_flag(model) == expected


@parameterized.expand(
    [
        ("claude-sonnet-5", True),
        ("anthropic/claude-opus-5", True),
        ("my-opus-alias", False),
        ("deepseek-ai/deepseek-v4-flash-0731", False),
        ("@cf/zai-org/glm-5.2", False),
        ("moonshotai/kimi-k3", False),
        (None, False),
    ]
)
def test_is_anthropic_served_model(model_id: str | None, expected: bool) -> None:
    assert model_catalog.is_anthropic_served_model(model_id) is expected
