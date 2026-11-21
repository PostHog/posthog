import dataclasses
from typing import Any

import pytest
from unittest.mock import patch

from parameterized import parameterized
from syrupy.extensions.json import JSONSnapshotExtension

from products.tasks.backend import model_catalog
from products.tasks.backend.constants import get_required_model_flag
from products.tasks.backend.facade.model_catalogue import GatewayModel, available_model_choices
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
        ("claude-opus-9", ["low", "medium", "high"], ("low", "medium", "high")),
        ("zai-org/glm-9", ["high", "max"], ("high", "max")),
    ],
    ids=[
        "every_tier",
        "tiers_the_catalog_lacks_are_dropped",
        "catalog_order",
        "no_effort_control",
        "claude_with_max_gains_ultracode",
        "claude_without_max",
        "hosted_model_with_max_gains_nothing",
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


class TestAvailableModelChoices:
    """The gateway-backed list the `/tasks/models` endpoint serves. Slack and the web read
    the catalog directly, so this path is the only one still asking what is served now."""

    def test_drops_providers_we_cannot_route(self) -> None:
        gateway = (
            GatewayModel(id="claude-fable-5", owned_by="anthropic", context_window=200000),
            GatewayModel(id="titan-express", owned_by="bedrock", context_window=8000),
        )
        with patch(
            "products.tasks.backend.logic.services.model_catalogue.list_gateway_models",
            return_value=gateway,
        ):
            assert [c.model for c in available_model_choices("posthog_code")] == ["claude-fable-5"]

    def test_drops_models_the_product_pin_does_not_admit(self) -> None:
        gateway = (
            GatewayModel(id="claude-opus-5-5", owned_by="anthropic", context_window=1000000),
            GatewayModel(id="gpt-4o", owned_by="openai", context_window=128000),
        )
        with patch(
            "products.tasks.backend.logic.services.model_catalogue.list_gateway_models",
            return_value=gateway,
        ):
            assert [c.model for c in available_model_choices("posthog_code")] == ["claude-opus-5-5"]

    @pytest.mark.parametrize(
        "listed,expected",
        [
            pytest.param(
                GatewayModel(
                    id="gpt-5.4",
                    owned_by="openai",
                    context_window=1050000,
                    name="GPT-5.4 (listed)",
                    reasoning_efforts=("low", "medium", "high", "xhigh"),
                    input_per_mtok=8.0,
                    output_per_mtok=40.0,
                ),
                ("GPT-5.4 (listed)", ("low", "medium", "high", "xhigh"), "4×"),
                id="every_fact",
            ),
            pytest.param(
                GatewayModel(id="gpt-5.4", owned_by="openai", context_window=1050000, name="GPT-5.4 (listed)"),
                ("GPT-5.4 (listed)", ("low", "medium", "high"), None),
                id="name_only",
            ),
            pytest.param(
                GatewayModel(id="gpt-5.4", owned_by="openai", context_window=1050000, input_per_mtok=8.0),
                ("GPT-5.4", ("low", "medium", "high"), None),
                id="half_a_price",
            ),
            pytest.param(
                GatewayModel(id="gpt-5.4", owned_by="openai", context_window=1050000),
                ("GPT-5.4", ("low", "medium", "high"), None),
                id="no_facts",
            ),
            pytest.param(
                GatewayModel(
                    id="claude-haiku-4-5",
                    owned_by="anthropic",
                    context_window=200000,
                    name="Claude Haiku 4.5 (latest)",
                ),
                ("Claude Haiku 4.5", (), None),
                id="alias_name",
            ),
            pytest.param(
                GatewayModel(
                    id="claude-sonnet-5",
                    owned_by="anthropic",
                    context_window=1000000,
                    name="Sonnet (listed)",
                    reasoning_efforts=("low",),
                    input_per_mtok=8.0,
                    output_per_mtok=40.0,
                ),
                ("Claude Sonnet 5", ("low", "medium", "high", "xhigh", "max", "ultracode"), "1×"),
                id="the_catalog_row_wins",
            ),
        ],
    )
    def test_describes_a_model_the_catalog_lacks_from_its_listing(
        self, listed: GatewayModel, expected: tuple[str, tuple[str, ...], str | None]
    ) -> None:
        with patch(
            "products.tasks.backend.logic.services.model_catalogue.list_gateway_models",
            return_value=(listed,),
        ):
            (choice,) = available_model_choices("posthog_code")

        assert (choice.label, choice.supported_efforts, choice.cost_multiplier) == expected

    @pytest.mark.parametrize(
        "model,listed_efforts,effort,accepted",
        [
            ("gpt-5.4", ("low", "medium", "high", "xhigh", "max"), "max", True),
            ("gpt-5.4", ("low", "medium", "high"), "max", False),
            ("gpt-5.4", None, "high", True),
            ("gpt-5.4", None, "max", False),
            ("gpt-6.2-sol", ("low",), "max", True),
        ],
        ids=[
            "listed_effort",
            "unlisted_effort",
            "no_listing_falls_back_to_the_adapter",
            "no_listing_rejects_past_the_fallback",
            "the_catalog_row_wins",
        ],
    )
    def test_effort_check_agrees_with_the_listing(
        self, model: str, listed_efforts: tuple[str, ...] | None, effort: str, accepted: bool
    ) -> None:
        listed = GatewayModel(id=model, owned_by="openai", context_window=1050000, reasoning_efforts=listed_efforts)
        with (
            patch(
                "products.tasks.backend.logic.services.model_catalogue.cached_gateway_models",
                return_value=(listed,),
            ),
            patch(
                "products.tasks.backend.logic.services.model_catalogue.list_gateway_models",
                side_effect=AssertionError("an effort check must not wait on the gateway"),
            ),
        ):
            error = get_reasoning_effort_error("codex", model, effort)

        assert (error is None) is accepted

    def test_keeps_vendor_served_models_the_catalog_routes(self) -> None:
        # The gateway owns these under the party serving them, not the harness that drives
        # them, so routing on the owner alone dropped every one from the web picker.
        gateway = (
            GatewayModel(id="deepseek-ai/deepseek-v4-flash-0731", owned_by="baseten", context_window=128000),
            GatewayModel(id="zai-org/glm-5.3-flash", owned_by="cloudflare", context_window=128000),
            GatewayModel(id="moonshotai/kimi-k3", owned_by="moonshotai", context_window=128000),
        )
        with patch(
            "products.tasks.backend.logic.services.model_catalogue.list_gateway_models",
            return_value=gateway,
        ):
            choices = available_model_choices("posthog_code")

        assert [c.model for c in choices] == [m.id for m in gateway]
        assert {c.runtime_adapter for c in choices} == {"claude"}
        assert [c.label for c in choices] == ["DeepSeek V4 Flash", "GLM-5.3 Flash", "Kimi K3"]


def test_every_model_resolves_to_its_catalog_flag() -> None:
    # The gate and the pickers read one field now, so this fails if a row gains an
    # access_flag the entitlement check cannot see, whichever spelling the caller sends.
    for model in model_catalog.MODELS:
        assert get_required_model_flag(model.id) == model.access_flag
        assert get_required_model_flag(f"anthropic/{model.id}") == model.access_flag


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gpt-6.2-sol", "tasks-sol-preview"),
        ("gpt-6.3-sol", "tasks-sol-preview"),
        ("openai/gpt-6.3-sol", "tasks-sol-preview"),
        ("gpt-6.1-sol", None),
        ("gpt-6.3-astra", None),
    ],
    ids=[
        "gated_catalog_row",
        "newer_version_of_the_gated_line",
        "provider_qualified_spelling",
        "ungated_catalog_row_of_the_line",
        "another_line",
    ],
)
def test_a_version_the_catalog_lacks_takes_the_flag_of_its_line(model: str, expected: str | None) -> None:
    gated = tuple(
        dataclasses.replace(entry, access_flag="tasks-sol-preview") if entry.id == "gpt-6.2-sol" else entry
        for entry in model_catalog.MODELS
    )
    with (
        patch.object(model_catalog, "MODELS", gated),
        patch.object(model_catalog, "_MODEL_BY_ID", {entry.id: entry for entry in gated}),
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
