"""Tests for intent-based developer environment system."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

import yaml
from hogli_commands.devenv.generator import DevenvConfig, MprocsGenerator, load_devenv_config
from hogli_commands.devenv.registry import ProcessRegistry, create_mprocs_registry
from hogli_commands.devenv.resolver import Capability, Intent, IntentMap, IntentResolver, load_intent_map
from parameterized import parameterized


class MockRegistry(ProcessRegistry):
    """Mock registry for testing that returns predefined capability→units mappings."""

    def __init__(self, capability_units: dict[str, list[str]], ask_skip: list[str] | None = None):
        self._capability_units = capability_units
        self._ask_skip = ask_skip or []
        # dict[str, Any] since proc configs are heterogeneous
        # (shell: str, capability: str, autostart: bool, ...)
        self._processes: dict[str, dict[str, Any]] = {
            unit: {"shell": f"./bin/start-{unit}", "capability": cap}
            for cap, units in capability_units.items()
            for unit in units
        }

    def get_processes(self) -> dict:
        return {
            name: {"shell": config["shell"], "capability": config["capability"]}
            for name, config in self._processes.items()
        }

    def get_capability_units(self, capability: str) -> list[str]:
        return self._capability_units.get(capability, [])

    def get_all_capabilities(self) -> set[str]:
        return set(self._capability_units.keys())

    def get_process_config(self, name: str) -> dict:
        return self._processes.get(name, {}).copy()

    def get_global_settings(self) -> dict:
        return {"mouse_scroll_speed": 1, "scrollback": 10000}

    def get_ask_skip_processes(self) -> list[str]:
        return self._ask_skip


def create_test_intent_map() -> IntentMap:
    """Create a minimal intent map for testing."""
    return IntentMap(
        version="1.0",
        capabilities={
            "core_infra": Capability(
                name="core_infra",
                description="Core infrastructure",
                requires=[],
            ),
            "event_ingestion": Capability(
                name="event_ingestion",
                description="Event pipeline",
                requires=["core_infra"],
            ),
            "error_symbolication": Capability(
                name="error_symbolication",
                description="Error symbolication",
                requires=["event_ingestion"],
            ),
            "replay_storage": Capability(
                name="replay_storage",
                description="Replay storage",
                requires=["event_ingestion"],
            ),
            "flag_evaluation": Capability(
                name="flag_evaluation",
                description="Feature flags",
                requires=["core_infra"],
            ),
        },
        intents={
            "error_tracking": Intent(
                name="error_tracking",
                description="Error tracking",
                capabilities=["event_ingestion", "error_symbolication"],
            ),
            "session_replay": Intent(
                name="session_replay",
                description="Session replay",
                capabilities=["event_ingestion", "replay_storage"],
            ),
            "feature_flags": Intent(
                name="feature_flags",
                description="Feature flags",
                capabilities=["flag_evaluation"],
            ),
            "product_analytics": Intent(
                name="product_analytics",
                description="Product analytics",
                capabilities=["event_ingestion"],
            ),
        },
        always_required=["backend", "frontend", "docker-compose"],
    )


def create_test_registry() -> MockRegistry:
    """Create a mock registry matching the test intent map."""
    return MockRegistry(
        {
            "core_infra": ["docker-compose", "migrate-postgres"],
            "event_ingestion": ["nodejs", "capture"],
            "error_symbolication": ["cymbal"],
            "replay_storage": ["capture-replay"],
            "flag_evaluation": ["feature-flags"],
        }
    )


class TestIntentResolver:
    """Test intent resolution logic."""

    @parameterized.expand(
        [
            # (intents, expected_units_subset, description)
            (["error_tracking"], {"cymbal", "nodejs", "capture"}, "error_tracking includes cymbal"),
            (["session_replay"], {"capture-replay", "nodejs", "capture"}, "session_replay includes capture-replay"),
            (["feature_flags"], {"feature-flags"}, "feature_flags includes feature-flags"),
            (["product_analytics"], {"nodejs", "capture"}, "product_analytics includes event pipeline"),
        ]
    )
    def test_resolve_single_intent(self, intents: list[str], expected_subset: set[str], description: str) -> None:
        """Single intent resolves to expected units."""
        intent_map = create_test_intent_map()
        registry = create_test_registry()
        resolver = IntentResolver(intent_map, registry)

        result = resolver.resolve(intents)

        assert expected_subset <= result.units, f"{description}: missing {expected_subset - result.units}"

    def test_resolve_always_includes_required(self) -> None:
        """Resolution always includes always_required units."""
        intent_map = create_test_intent_map()
        registry = create_test_registry()
        resolver = IntentResolver(intent_map, registry)

        result = resolver.resolve(["feature_flags"])

        assert "backend" in result.units
        assert "frontend" in result.units
        assert "docker-compose" in result.units

    def test_resolve_expands_capability_dependencies(self) -> None:
        """Capabilities transitively expand their dependencies."""
        intent_map = create_test_intent_map()
        registry = create_test_registry()
        resolver = IntentResolver(intent_map, registry)

        # error_tracking requires error_symbolication which requires event_ingestion
        # which requires core_infra
        result = resolver.resolve(["error_tracking"])

        # Should include core_infra units (docker-compose, migrate-postgres)
        assert "docker-compose" in result.units
        assert "migrate-postgres" in result.units
        # Should include event_ingestion units
        assert "nodejs" in result.units
        assert "capture" in result.units
        # Should include error_symbolication units
        assert "cymbal" in result.units

    def test_resolve_multiple_intents_unions_units(self) -> None:
        """Multiple intents union their required units."""
        intent_map = create_test_intent_map()
        registry = create_test_registry()
        resolver = IntentResolver(intent_map, registry)

        result = resolver.resolve(["error_tracking", "session_replay"])

        # Should have units from both
        assert "cymbal" in result.units  # error_tracking
        assert "capture-replay" in result.units  # session_replay

    @parameterized.expand(
        [
            (["storybook"], [], {"storybook"}, "include adds units"),
            ([], ["nodejs"], set(), "exclude removes units"),
        ]
    )
    def test_resolve_with_overrides(
        self,
        include: list[str],
        exclude: list[str],
        expected_diff: set[str],
        description: str,
    ) -> None:
        """Overrides modify the resolved units."""
        intent_map = create_test_intent_map()
        registry = create_test_registry()
        resolver = IntentResolver(intent_map, registry)

        result = resolver.resolve(
            ["product_analytics"],
            include_units=include,
            exclude_units=exclude,
        )

        if include:
            assert expected_diff <= result.units, f"{description}"
        if exclude:
            assert not (expected_diff & result.units), f"{description}"

    def test_resolve_unknown_intent_raises(self) -> None:
        """Unknown intent raises ValueError."""
        intent_map = create_test_intent_map()
        registry = create_test_registry()
        resolver = IntentResolver(intent_map, registry)

        with pytest.raises(ValueError, match="Unknown intent"):
            resolver.resolve(["nonexistent"])

    def test_explain_resolution_includes_all_sections(self) -> None:
        """Explanation includes intents, capabilities, and units."""
        intent_map = create_test_intent_map()
        registry = create_test_registry()
        resolver = IntentResolver(intent_map, registry)

        result = resolver.resolve(["error_tracking"])
        explanation = resolver.explain_resolution(result)

        assert "error_tracking" in explanation
        assert "error_symbolication" in explanation
        assert "cymbal" in explanation


class TestDockerProfiles:
    """Test docker profile resolution."""

    def test_capability_with_docker_profile(self) -> None:
        """Capability with docker_profiles includes them in resolution."""
        intent_map = IntentMap(
            version="1.0",
            capabilities={
                "core_infra": Capability(
                    name="core_infra",
                    description="Core",
                    docker_profiles=[],
                ),
                "temporal_workflows": Capability(
                    name="temporal_workflows",
                    description="Temporal",
                    requires=["core_infra"],
                    docker_profiles=["temporal"],
                ),
            },
            intents={
                "data_warehouse": Intent(
                    name="data_warehouse",
                    description="Data warehouse",
                    capabilities=["temporal_workflows"],
                ),
            },
            always_required=[],
        )
        registry = MockRegistry(
            {
                "core_infra": [],
                "temporal_workflows": ["temporal-worker"],
            }
        )
        resolver = IntentResolver(intent_map, registry)

        result = resolver.resolve(["data_warehouse"])

        assert "temporal" in result.docker_profiles

    def test_multiple_capabilities_aggregate_profiles(self) -> None:
        """Multiple capabilities aggregate their docker profiles."""
        intent_map = IntentMap(
            version="1.0",
            capabilities={
                "core_infra": Capability(
                    name="core_infra",
                    description="Core",
                    docker_profiles=[],
                ),
                "replay_storage": Capability(
                    name="replay_storage",
                    description="Replay",
                    requires=["core_infra"],
                    docker_profiles=["replay"],
                ),
                "observability": Capability(
                    name="observability",
                    description="Observability",
                    requires=["core_infra"],
                    docker_profiles=["observability"],
                ),
            },
            intents={
                "session_replay": Intent(
                    name="session_replay",
                    description="Session replay",
                    capabilities=["replay_storage"],
                ),
            },
            always_required=[],
        )
        registry = MockRegistry(
            {
                "core_infra": [],
                "replay_storage": [],
                "observability": [],
            }
        )
        resolver = IntentResolver(intent_map, registry)

        result = resolver.resolve(["session_replay"], include_capabilities=["observability"])

        assert "replay" in result.docker_profiles
        assert "observability" in result.docker_profiles

    def test_no_profiles_returns_empty_set(self) -> None:
        """Resolution without docker profiles returns empty set."""
        intent_map = create_test_intent_map()
        registry = create_test_registry()
        resolver = IntentResolver(intent_map, registry)

        result = resolver.resolve(["product_analytics"])

        assert result.docker_profiles == set()

    def test_real_intent_map_resolves_docker_profiles(self) -> None:
        """Real intent map resolves docker profiles for relevant intents."""
        intent_map = load_intent_map()
        registry = create_mprocs_registry()
        resolver = IntentResolver(intent_map, registry)

        # data_warehouse needs temporal
        result = resolver.resolve(["data_warehouse"])
        assert "temporal" in result.docker_profiles

        # session_replay needs replay (seaweedfs)
        result = resolver.resolve(["session_replay"])
        assert "replay" in result.docker_profiles

        # feature_flags needs etcd (coordination)
        result = resolver.resolve(["feature_flags"])
        assert "etcd" in result.docker_profiles


class TestIntentMapLoading:
    """Test intent map loading from YAML."""

    def test_load_real_intent_map(self) -> None:
        """Can load the real intent-map.yaml from the repo."""
        intent_map = load_intent_map()

        assert intent_map.version == "1.0"
        assert len(intent_map.intents) > 0
        assert len(intent_map.capabilities) > 0

    def test_real_intent_map_has_key_intents(self) -> None:
        """Real intent map includes key product intents."""
        intent_map = load_intent_map()

        key_intents = ["error_tracking", "session_replay", "product_analytics", "feature_flags"]
        for intent in key_intents:
            assert intent in intent_map.intents, f"Missing intent: {intent}"

    def test_real_intent_map_resolves_without_errors(self) -> None:
        """All intents in real map resolve successfully."""
        intent_map = load_intent_map()
        registry = create_mprocs_registry()
        resolver = IntentResolver(intent_map, registry)

        for intent_name in intent_map.intents:
            # Should not raise
            result = resolver.resolve([intent_name])
            assert len(result.units) > 0

    def test_real_intent_map_has_docker_profiles(self) -> None:
        """Real intent map capabilities have docker_profiles defined."""
        intent_map = load_intent_map()

        # Check that capabilities with docker services have profiles
        assert intent_map.capabilities["temporal_workflows"].docker_profiles == ["temporal"]
        assert intent_map.capabilities["replay_storage"].docker_profiles == ["replay"]
        assert intent_map.capabilities["observability"].docker_profiles == ["observability"]
        assert intent_map.capabilities["dev_tools"].docker_profiles == ["dev_tools"]
        assert intent_map.capabilities["coordination"].docker_profiles == ["etcd"]


class TestMprocsRegistry:
    """Test MprocsRegistry reads capability from mprocs.yaml."""

    def test_registry_loads_capabilities(self) -> None:
        """Registry correctly maps processes to capabilities."""
        registry = create_mprocs_registry()

        # Check some known mappings
        assert "cymbal" in registry.get_capability_units("error_symbolication")
        assert "capture" in registry.get_capability_units("event_ingestion")
        assert "nodejs" in registry.get_capability_units("event_ingestion")
        assert "temporal-worker" in registry.get_capability_units("temporal_workflows")

    def test_registry_get_all_capabilities(self) -> None:
        """Registry returns all declared capabilities."""
        registry = create_mprocs_registry()
        capabilities = registry.get_all_capabilities()

        assert "core_infra" in capabilities
        assert "event_ingestion" in capabilities
        assert "error_symbolication" in capabilities

    def test_registry_get_process_config(self) -> None:
        """Registry returns process config for generation."""
        registry = create_mprocs_registry()
        config = registry.get_process_config("backend")

        assert "shell" in config
        assert "start-backend" in config["shell"]


class TestDevenvConfig:
    """Test DevenvConfig data class."""

    def test_config_model_dump_minimal(self) -> None:
        """Minimal config converts to dict cleanly."""
        config = DevenvConfig(intents=["error_tracking"])

        data = config.model_dump(exclude_defaults=True)

        assert data["intents"] == ["error_tracking"]
        assert "exclude_units" not in data  # Empty lists not included

    def test_config_model_dump_with_overrides(self) -> None:
        """Config with overrides includes them."""
        config = DevenvConfig(
            intents=["error_tracking"],
            exclude_units=["typegen"],
        )

        data = config.model_dump(exclude_defaults=True)

        assert data["intents"] == ["error_tracking"]
        assert data["exclude_units"] == ["typegen"]

    def test_config_model_validate_roundtrip(self) -> None:
        """Config survives dict roundtrip via Pydantic."""
        original = DevenvConfig(
            intents=["error_tracking", "session_replay"],
            exclude_units=["dagster", "typegen"],
        )

        data = original.model_dump()
        restored = DevenvConfig.model_validate(data)

        assert restored.intents == original.intents
        assert restored.exclude_units == original.exclude_units


class TestConfigPersistence:
    """Test config persistence via generated mprocs.yaml."""

    def test_save_and_load_config(self) -> None:
        """Config can be saved and loaded via generated mprocs.yaml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "mprocs.yaml"
            config = DevenvConfig(intents=["error_tracking"])
            registry = create_test_registry()
            intent_map = create_test_intent_map()
            resolver = IntentResolver(intent_map, registry)

            resolved = resolver.resolve(config.intents)
            generator = MprocsGenerator(registry)
            generator.generate_and_save(resolved, output_path, config)

            loaded = load_devenv_config(output_path)
            assert loaded is not None
            assert loaded.intents == ["error_tracking"]

    def test_load_nonexistent_config(self) -> None:
        """Loading nonexistent config returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "nonexistent.yaml"

            loaded = load_devenv_config(output_path)

            assert loaded is None


class TestInfoProcess:
    """Test info process generation."""

    def _generate_with_intents(self, intents: list[str]) -> dict[str, dict]:
        """Helper to generate mprocs config and return the procs dict."""
        intent_map = create_test_intent_map()
        registry = create_test_registry()
        resolver = IntentResolver(intent_map, registry)
        resolved = resolver.resolve(intents)
        generator = MprocsGenerator(registry)
        config = generator.generate(resolved)
        return config.procs

    def test_info_process_always_present(self) -> None:
        """Generated config always contains info process regardless of intents."""
        procs = self._generate_with_intents(["feature_flags"])
        assert "info" in procs

    def test_info_process_is_first(self) -> None:
        """Info process is the first entry in the procs dict."""
        procs = self._generate_with_intents(["error_tracking"])
        assert next(iter(procs.keys())) == "info"

    @parameterized.expand(
        [
            (["error_tracking"], {"error_tracking"}),
            (["error_tracking", "session_replay"], {"error_tracking", "session_replay"}),
            (["feature_flags"], {"feature_flags"}),
        ]
    )
    def test_info_process_includes_product_names(self, intents: list[str], expected_products: set[str]) -> None:
        """Info process shell includes product names."""
        procs = self._generate_with_intents(intents)
        shell = procs["info"]["shell"]
        for product in expected_products:
            assert product in shell

    def test_info_process_includes_process_count(self) -> None:
        """Info process shell includes the active process count."""
        intent_map = create_test_intent_map()
        registry = create_test_registry()
        resolver = IntentResolver(intent_map, registry)
        resolved = resolver.resolve(["error_tracking"])
        expected_count = len(resolved.units)

        generator = MprocsGenerator(registry)
        config = generator.generate(resolved)

        shell = config.procs["info"]["shell"]
        assert f"{expected_count} active" in shell

    def test_info_process_reads_news_at_runtime(self) -> None:
        """Info process shell reads news.txt at runtime, not at generation time."""
        procs = self._generate_with_intents(["feature_flags"])
        shell = procs["info"]["shell"]

        assert "devenv/news.txt" in shell
        assert "News:" in shell

    def test_info_process_includes_commands(self) -> None:
        """Info process shell includes useful commands."""
        procs = self._generate_with_intents(["feature_flags"])
        shell = procs["info"]["shell"]

        assert "hogli dev:setup" in shell
        assert "hogli dev:explain" in shell


class TestMprocsGeneratorRegression:
    """Regression tests for generator behavior with the real intent map."""

    def test_product_analytics_keeps_native_core_services(self) -> None:
        intent_map = load_intent_map()
        registry = create_mprocs_registry()
        resolver = IntentResolver(intent_map, registry)
        resolved = resolver.resolve(["product_analytics"])
        config = MprocsGenerator(registry).generate(resolved)

        assert "capture" in resolved.units
        assert "capture" in config.procs
        assert "feature-flags" in config.procs
        assert "property-defs-rs" in config.procs
        assert "docker-compose" in config.procs


class TestMprocsGeneratorPreservesCapability:
    """Generated procs retain `capability:` so phrocs can group by capability.

    phrocs copies ProcConfig.Capability into Groups["capability"] at load
    time; the generator must therefore pass the field through.
    """

    def test_capability_preserved_in_generated_procs(self) -> None:
        intent_map = create_test_intent_map()
        registry = create_test_registry()
        resolver = IntentResolver(intent_map, registry)
        resolved = resolver.resolve(["session_replay"])
        config = MprocsGenerator(registry).generate(resolved)

        # Spot-check procs from different capabilities
        assert config.procs["capture"].get("capability") == "event_ingestion"
        assert config.procs["capture-replay"].get("capability") == "replay_storage"
        assert config.procs["docker-compose"].get("capability") == "core_infra"

    def test_always_required_without_capability_gets_synthetic_bucket(self) -> None:
        """Procs in always_required that don't declare a capability get "always_required"."""
        intent_map = create_test_intent_map()  # always_required = [backend, frontend, docker-compose]
        registry = create_test_registry()
        # Register backend/frontend without a capability (they're the app itself)
        registry._processes["backend"] = {"shell": "./bin/start-backend", "capability": ""}
        registry._processes["frontend"] = {"shell": "./bin/start-frontend", "capability": ""}
        resolver = IntentResolver(intent_map, registry)
        resolved = resolver.resolve(["product_analytics"])
        config = MprocsGenerator(registry).generate(resolved)

        assert config.procs["backend"].get("capability") == "always_required"
        assert config.procs["frontend"].get("capability") == "always_required"
        # docker-compose has a real capability; synthetic bucket must not overwrite it
        assert config.procs["docker-compose"].get("capability") == "core_infra"

    def test_manual_start_without_capability_gets_tools_bucket(self) -> None:
        """Procs with autostart: false and no capability get "tools"."""
        intent_map = create_test_intent_map()
        registry = create_test_registry()
        # Manual-start tool: no capability, autostart: false, not in always_required
        registry._processes["storybook"] = {
            "shell": "pnpm storybook",
            "capability": "",
            "autostart": False,
        }
        resolver = IntentResolver(intent_map, registry)
        resolved = resolver.resolve(["product_analytics"])
        config = MprocsGenerator(registry).generate(resolved)

        assert "storybook" in config.procs
        assert config.procs["storybook"].get("capability") == "tools"

    def test_always_required_wins_over_manual_start(self) -> None:
        """A proc that is both always_required and autostart: false (e.g. typegen)
        goes to the "always_required" bucket, not "tools"."""
        intent_map = create_test_intent_map()
        intent_map.always_required = [*intent_map.always_required, "typegen"]
        registry = create_test_registry()
        registry._processes["typegen"] = {
            "shell": "pnpm typegen:watch",
            "capability": "",
            "autostart": False,
        }
        resolver = IntentResolver(intent_map, registry)
        resolved = resolver.resolve(["product_analytics"])
        config = MprocsGenerator(registry).generate(resolved)

        assert config.procs["typegen"].get("capability") == "always_required"

    def test_capability_survives_yaml_round_trip(self, tmp_path: Path) -> None:
        """End-to-end check: generator output -> YAML file -> parse.

        phrocs' Go-side inference (inferGroupFromCapability) relies on the
        `capability:` field being present on each emitted proc. This test
        catches regressions where the generator, yaml.dump, or MprocsConfig
        serialization silently drops the field somewhere in the pipeline.
        The Go side has its own tests that the field, once present in YAML,
        is copied into Groups["capability"].
        """
        # Use the real intent-map and registry so we exercise the live wiring,
        # including the synthetic always_required/tools buckets.
        intent_map = load_intent_map()
        registry = create_mprocs_registry()
        resolver = IntentResolver(intent_map, registry)
        resolved = resolver.resolve(["product_analytics"])
        config = MprocsGenerator(registry).generate(resolved)

        out = tmp_path / "mprocs.yaml"
        MprocsGenerator(registry).save(config, out)

        with open(out) as f:
            data = yaml.safe_load(f)

        # Every proc in the output (except info, which is pinned by YAML) must
        # carry a non-empty capability so the capability dimension has content.
        missing = [name for name, cfg in data["procs"].items() if name != "info" and not cfg.get("capability")]
        assert not missing, f"procs missing capability in serialized YAML: {missing}"

        # Spot-check the three flavors: real, always_required, tools.
        assert data["procs"]["capture"]["capability"] == "event_ingestion"
        assert data["procs"]["backend"]["capability"] == "always_required"
        assert data["procs"]["storybook"]["capability"] == "tools"


class TestPersonhogEnvInjection:
    """Test that personhog env vars are injected into backend when capability is active."""

    def _make_fixtures(self, *, with_personhog: bool):
        capabilities = {
            "core_infra": Capability(name="core_infra", description="Core", requires=[]),
            "flag_evaluation": Capability(name="flag_evaluation", description="Flags", requires=["core_infra"]),
        }
        intents = {
            "feature_flags": Intent(name="feature_flags", description="Flags", capabilities=["flag_evaluation"]),
        }
        capability_units = {
            "core_infra": ["docker-compose"],
            "flag_evaluation": ["feature-flags"],
        }

        if with_personhog:
            capabilities["personhog"] = Capability(name="personhog", description="PersonHog", requires=["core_infra"])
            intents["personhog"] = Intent(name="personhog", description="PersonHog", capabilities=["personhog"])
            capability_units["personhog"] = ["personhog-replica", "personhog-router"]

        intent_map = IntentMap(
            version="1.0",
            capabilities=capabilities,
            intents=intents,
            always_required=["backend", "nodejs"],
        )
        registry = MockRegistry(capability_units)
        registry._processes["backend"] = {"shell": "./bin/start-backend", "capability": ""}
        registry._processes["nodejs"] = {"shell": "./bin/posthog-node", "capability": "event_ingestion"}
        return intent_map, registry

    @parameterized.expand(
        [
            (True, ["personhog"], True),
            (False, ["feature_flags"], False),
        ]
    )
    def test_personhog_env_injection(self, with_personhog: bool, intents: list[str], should_inject: bool) -> None:
        intent_map, registry = self._make_fixtures(with_personhog=with_personhog)
        resolver = IntentResolver(intent_map, registry)
        resolved = resolver.resolve(intents)
        config = MprocsGenerator(registry).generate(resolved)

        for proc_name in ["backend", "nodejs"]:
            if proc_name not in config.procs:
                continue
            shell = config.procs[proc_name]["shell"]
            for var in ["PERSONHOG_ADDR", "PERSONHOG_ENABLED", "PERSONHOG_ROLLOUT_PERCENTAGE"]:
                if should_inject:
                    assert var in shell, f"{var} should be in {proc_name} shell"
                else:
                    assert var not in shell, f"{var} should not be in {proc_name} shell"
