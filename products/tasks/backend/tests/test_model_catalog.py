from typing import TYPE_CHECKING, Any, cast

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.tasks.backend import model_catalog
from products.tasks.backend.constants import get_required_model_flag
from products.tasks.backend.facade.model_catalogue import (
    FREE_TIER_PIN_KEY,
    GatewayModel,
    ModelChoice,
    available_model_choices,
    plan_model_choices,
    runtime_adapter_for,
)
from products.tasks.backend.facade.model_listing_testing import serve_gateway_listing
from products.tasks.backend.logic.services import gateway_model_pin
from products.tasks.backend.models import Task
from products.tasks.backend.temporal.process_task.utils import ReasoningEffort, get_reasoning_effort_error

if TYPE_CHECKING:
    from posthog.llm.gateway_client import Product

_FAMILY_PRODUCTS = sorted(model_catalog.PRODUCT_MODEL_FAMILIES)


def _offered(product: str) -> dict[str, ModelChoice]:
    return {choice.model: choice for choice in available_model_choices(cast("Product", product))}


def test_reasoning_effort_enum_covers_every_tier() -> None:
    assert set(model_catalog.REASONING_EFFORTS) <= {effort.value for effort in ReasoningEffort}


def test_every_effort_has_a_label() -> None:
    assert set(model_catalog.REASONING_EFFORT_LABELS) == set(model_catalog.REASONING_EFFORTS), (
        "a depth with no label renders as its raw id in every picker"
    )


@pytest.mark.parametrize("product", _FAMILY_PRODUCTS)
def test_every_ladder_rung_is_one_a_picker_offers(product: str) -> None:
    offered = _offered(product)
    for adapter, ladder in model_catalog.CAPABILITY_LADDER_BY_RUNTIME_ADAPTER.items():
        for notch in ladder:
            choice = offered.get(notch.model)
            assert choice is not None and choice.runtime_adapter == adapter, (
                f"'{adapter}' ladder names '{notch.model}', which '{product}' does not offer on that adapter"
            )
            assert notch.effort in choice.supported_efforts, (
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
        "tiers_a_picker_lacks_are_dropped",
        "tier_order",
        "no_effort_control",
        "claude_with_xhigh_gains_ultracode",
        "claude_without_xhigh",
        "hosted_model_with_xhigh_gains_nothing",
    ],
)
def test_provider_efforts_map_onto_the_reasoning_tiers(
    model: str, provider_efforts: list[str], expected: tuple[str, ...]
) -> None:
    assert model_catalog.reasoning_efforts_from_provider(model, provider_efforts) == expected


@pytest.mark.parametrize("product", _FAMILY_PRODUCTS)
def test_every_default_model_is_one_a_picker_offers(product: str) -> None:
    offered = _offered(product)
    for adapter, model in model_catalog.DEFAULT_MODEL_BY_RUNTIME_ADAPTER.items():
        choice = offered.get(model)
        assert choice is not None and choice.runtime_adapter == adapter, (
            f"the default model for '{adapter}' is not one '{product}' offers, so a run that pins no model "
            f"would start on one its picker cannot show"
        )


def test_the_cost_baseline_is_listed_with_a_price() -> None:
    choices = available_model_choices("posthog_code", include_unoffered=True)
    baseline = next(choice for choice in choices if choice.model == model_catalog.COST_BASELINE_MODEL)

    assert baseline.cost_multiplier == "1×"


@pytest.mark.parametrize(
    "cost,expected",
    [
        pytest.param(model_catalog.ModelCost(2, 10), "1×", id="baseline_is_one"),
        pytest.param(model_catalog.ModelCost(5, 25), "2.5×", id="input_and_output_agree"),
        pytest.param(model_catalog.ModelCost(5, 30), "≈2.8×", id="diverging_rates_are_approximate"),
        pytest.param(model_catalog.ModelCost(5, 20), "≈2.2×", id="a_half_rounds_to_even"),
        pytest.param(model_catalog.ModelCost(0.15, 0.5), "≈0.06×", id="cheap_model_keeps_two_decimals"),
        pytest.param(model_catalog.ModelCost(30, 150), "15×", id="a_large_multiple_drops_the_decimal"),
    ],
)
def test_cost_multiplier_reads_against_the_baseline(cost: model_catalog.ModelCost, expected: str) -> None:
    assert model_catalog.cost_multiplier_label_for_cost(cost, model_catalog.ModelCost(2, 10)) == expected


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
            choices = available_model_choices("posthog_code")

        assert [(choice.model, choice.context_window) for choice in choices] == [("claude-opus-5-5", 1)]

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
        "plan_pin,model,allowed",
        [
            ("posthog_code", "claude-opus-5-5", True),
            (FREE_TIER_PIN_KEY, "claude-opus-5-5", False),
            (FREE_TIER_PIN_KEY, "moonshotai/kimi-k3.1-pro", True),
        ],
    )
    def test_marks_whether_the_plan_pin_admits_each_model(self, plan_pin: str, model: str, allowed: bool) -> None:
        listing = tuple(
            GatewayModel(
                id=listed, owned_by="posthog", context_window=1, family=family, api_shapes=("anthropic-messages",)
            )
            for listed, family in (("claude-opus-5-5", "claude-opus"), ("moonshotai/kimi-k3.1-pro", "kimi-pro"))
        )
        with serve_gateway_listing(listing):
            choices = {choice.model: choice for choice in plan_model_choices("posthog_code", plan_pin)}

        assert choices[model].allowed is allowed


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
