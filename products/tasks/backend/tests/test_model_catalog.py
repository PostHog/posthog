import sys
import importlib.util
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend import model_catalog
from products.tasks.backend.temporal.process_task.utils import ReasoningEffort, RuntimeAdapter

REPO_ROOT = Path(__file__).resolve().parents[4]
GENERATOR = REPO_ROOT / "bin" / "build-task-model-catalog.py"


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


class TestGeneratedProjectionsMatchTheCatalog(SimpleTestCase):
    @parameterized.expand(
        [
            ("web", "WEB_OUTPUT", "OXFMT"),
            ("desktop", "DESKTOP_OUTPUT", "BIOME"),
        ]
    )
    def test_checked_in_projection_is_what_the_generator_emits(self, _name: str, output: str, style: str) -> None:
        generator = _load_generator()
        catalog = vars(model_catalog)
        expected = generator.render(catalog, getattr(generator, style))

        path: Path = getattr(generator, output)
        assert path.exists(), f"{path} is missing — run `hogli build:task-model-catalog`"
        assert path.read_text() == expected, (
            f"{path.relative_to(REPO_ROOT)} is stale. The catalog changed without regenerating, so this "
            f"surface would offer a selection the backend rejects. Run `hogli build:task-model-catalog`."
        )


class TestCatalogAgreesWithTheRuntimeEnums(SimpleTestCase):
    def test_every_runtime_adapter_has_catalog_models(self) -> None:
        for adapter in RuntimeAdapter:
            assert model_catalog.models_for_runtime_adapter(adapter.value), (
                f"runtime adapter '{adapter.value}' has no models in the catalog, so every picker "
                f"and validator would treat it as serving nothing"
            )

    def test_every_catalog_effort_is_a_known_reasoning_effort(self) -> None:
        known = {effort.value for effort in ReasoningEffort}
        used = {effort for entry in model_catalog.MODELS for effort in entry.reasoning_efforts}
        assert used <= known, f"catalog names efforts the ReasoningEffort enum lacks: {sorted(used - known)}"


class TestReasoningEffortResolution(SimpleTestCase):
    @parameterized.expand(
        [
            ("exact_id", "claude", "claude-sonnet-4-6", ("low", "medium", "high")),
            ("no_effort_control", "claude", "moonshotai/kimi-k3", ()),
            ("unknown_claude_model_has_no_fallback", "claude", "claude-imaginary-9", ()),
            ("provider_qualified_id", "claude", "anthropic/claude-sonnet-4-6", ("low", "medium", "high")),
            ("uppercase_id", "codex", "GPT-5.5", ("low", "medium", "high", "xhigh")),
            ("codex_family_variant", "codex", "gpt-5.5-codex", ("low", "medium", "high", "xhigh")),
            ("unknown_codex_model_falls_back", "codex", "gpt-9", ("low", "medium", "high")),
            ("exact_id_beats_family", "codex", "gpt-5.6-sol", ("low", "medium", "high", "xhigh", "max")),
        ]
    )
    def test_efforts_resolve_by_id_then_family_then_adapter(
        self, _name: str, adapter: str, model: str, expected: tuple[str, ...]
    ) -> None:
        assert model_catalog.reasoning_efforts_for(adapter, model) == expected

    def test_default_model_is_one_the_catalog_serves(self) -> None:
        for adapter, model in model_catalog.DEFAULT_MODEL_BY_RUNTIME_ADAPTER.items():
            assert model in model_catalog.models_for_runtime_adapter(adapter), (
                f"the default model for '{adapter}' is not in its catalog, so a run that pins no model "
                f"would resolve to one validation rejects"
            )
