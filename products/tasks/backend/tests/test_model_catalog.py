import sys
import importlib.util
from pathlib import Path
from typing import Any

import pytest

from syrupy.extensions.json import JSONSnapshotExtension

from products.tasks.backend import model_catalog
from products.tasks.backend.temporal.process_task.utils import ReasoningEffort, RuntimeAdapter

REPO_ROOT = Path(__file__).resolve().parents[4]
GENERATOR = REPO_ROOT / "products" / "tasks" / "scripts" / "build_model_catalog.py"


def _load_generator():
    name = "build_task_model_catalog"
    spec = importlib.util.spec_from_file_location(name, GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution because @dataclass resolves annotations through
    # sys.modules[cls.__module__], which is unset for a module loaded by path alone.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _resolved_catalog() -> dict[str, Any]:
    """The catalog as data, read back through the public resolver rather than the tables.

    Every value here is what a caller actually gets, so the snapshot moves when resolution
    changes even if the literals did not.
    """
    return {
        "reasoning_efforts": list(model_catalog.REASONING_EFFORTS),
        "runtime_adapters": {
            adapter: {
                "provider": model_catalog.PROVIDER_BY_RUNTIME_ADAPTER[adapter],
                "default_model": model_catalog.DEFAULT_MODEL_BY_RUNTIME_ADAPTER[adapter],
                "fallback_reasoning_efforts": list(
                    model_catalog.FALLBACK_REASONING_EFFORTS_BY_RUNTIME_ADAPTER.get(adapter, ())
                ),
                "models": {
                    model_id: list(model_catalog.reasoning_efforts_for(adapter, model_id))
                    for model_id in model_catalog.models_for_runtime_adapter(adapter)
                },
            }
            for adapter in model_catalog.RUNTIME_ADAPTERS
        },
        "model_families": [
            {"runtime_adapter": adapter, "prefix": prefix, "reasoning_efforts": list(efforts)}
            for adapter, prefix, efforts in model_catalog.FAMILY_REASONING_EFFORTS
        ],
    }


def test_every_model_resolves_to_the_recorded_triple(snapshot) -> None:
    # The parametrized cases below pin the resolution rules; this pins the whole answer for
    # every model at once, so a change to a shared effort tuple, a default, or a provider
    # lands in review as a readable data diff instead of one line of Python.
    # Refresh with: pytest products/tasks/backend/tests/test_model_catalog.py --snapshot-update
    assert _resolved_catalog() == snapshot(extension_class=JSONSnapshotExtension)


@pytest.mark.parametrize("output,style", [("WEB_OUTPUT", "OXFMT"), ("DESKTOP_OUTPUT", "BIOME")], ids=["web", "desktop"])
def test_checked_in_projection_is_what_the_generator_emits(output: str, style: str) -> None:
    generator = _load_generator()
    expected = generator.render(vars(model_catalog), getattr(generator, style))

    path: Path = getattr(generator, output)
    assert path.exists(), f"{path} is missing — run `hogli build:task-model-catalog`"
    assert path.read_text() == expected, (
        f"{path.relative_to(REPO_ROOT)} is stale. The catalog changed without regenerating, so this "
        f"surface would offer a selection the backend rejects. Run `hogli build:task-model-catalog`."
    )


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


def test_default_model_is_one_the_catalog_serves() -> None:
    for adapter, model in model_catalog.DEFAULT_MODEL_BY_RUNTIME_ADAPTER.items():
        assert model in model_catalog.models_for_runtime_adapter(adapter), (
            f"the default model for '{adapter}' is not in its catalog, so a run that pins no model "
            f"would resolve to one validation rejects"
        )


def test_labels_are_set_only_where_the_derived_name_is_wrong() -> None:
    # A pin that the formatter would produce anyway is dead weight that outlives the
    # formatter improving, so assert the property rather than restating the six strings.
    from products.tasks.backend.logic.services.model_catalogue import format_model_id

    for entry in model_catalog.MODELS:
        if entry.label is None:
            continue
        assert entry.label != format_model_id(entry.id), (
            f"'{entry.id}' pins the label the formatter already derives; drop the pin"
        )
