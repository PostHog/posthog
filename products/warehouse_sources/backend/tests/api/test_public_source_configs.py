import json

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from django_redis.cache import RedisCache
from django_redis.pool import ConnectionFactory
from parameterized import parameterized
from rest_framework import status

from posthog.settings.data_stores import WAREHOUSE_SOURCE_CATALOG_CACHE_CONFIG

from products.warehouse_sources.backend.cache import WarehouseSourceCatalogConnectionFactory
from products.warehouse_sources.backend.facade.source_config import SourceConfigMapResponse
from products.warehouse_sources.backend.presentation.views.public_source_configs import (
    build_source_configs,
    shared_catalog_cache_key,
    tracer,
)

MODULE = "products.warehouse_sources.backend.presentation.views.public_source_configs"


@override_settings(
    DEBUG=False,
    CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "source-catalog-tests"},
        "warehouse_source_catalog": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "source-catalog-tests",
        },
    },
)
class TestSourceConfigCache(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch(f"{MODULE}.get_git_commit_full", return_value="test-commit"))
        self.addCleanup(build_source_configs.cache_clear)
        self.addCleanup(caches["warehouse_source_catalog"].clear)
        build_source_configs.cache_clear()
        caches["warehouse_source_catalog"].clear()

    @parameterized.expand([(False,), (True,)])
    def test_catalog_spans_only_cover_cache_misses(self, include_tables: bool) -> None:
        with patch.object(tracer, "start_as_current_span") as start_span:
            cold = build_source_configs(include_tables=include_tables)
            assert build_source_configs(include_tables=include_tables) is cold
            assert [call.args[0] for call in start_span.call_args_list] == [
                "warehouse_sources.catalog.imports",
                "warehouse_sources.catalog.registry",
                "warehouse_sources.catalog.build",
            ]

            build_source_configs.cache_clear()
            start_span.reset_mock()
            with patch(f"{MODULE}.SourceRegistry.get_all_sources", side_effect=AssertionError("registry was loaded")):
                assert build_source_configs(include_tables=include_tables) == cold
            start_span.assert_not_called()

    @parameterized.expand([(False, None), (False, ""), (True, "test-commit")])
    def test_shared_catalog_cache_is_skipped_without_a_deploy(self, debug: bool, commit: str | None) -> None:
        with (
            self.settings(DEBUG=debug),
            patch(f"{MODULE}.get_git_commit_full", return_value=commit),
            patch(f"{MODULE}.caches") as shared_caches,
        ):
            assert len(build_source_configs(include_tables=False)) > 0
        shared_cache = shared_caches["warehouse_source_catalog"]
        shared_cache.get.assert_not_called()
        shared_cache.set.assert_not_called()

    @parameterized.expand(
        [("get", ConnectionError), ("set", ConnectionError), ("get", TimeoutError), ("set", TimeoutError)]
    )
    def test_cache_failure_preserves_the_catalog(self, operation: str, error_type: type[Exception]) -> None:
        expected = build_source_configs(include_tables=False)
        build_source_configs.cache_clear()
        catalog_cache = caches["warehouse_source_catalog"]
        catalog_cache.clear()
        with patch.object(catalog_cache, operation, side_effect=error_type("cache unavailable")):
            assert build_source_configs(include_tables=False) == expected

    def test_partial_catalog_is_not_shared(self) -> None:
        expected = {"Demo": {"name": "Demo"}}
        with (
            patch(f"{MODULE}.load_all_sources_or_raise", side_effect=ImportError("source unavailable")),
            patch(f"{MODULE}._build_source_configs_from_registry", return_value=expected),
        ):
            assert build_source_configs(include_tables=False) == expected
        assert caches["warehouse_source_catalog"].get(shared_catalog_cache_key(include_tables=False)) is None

    def test_invalid_cached_json_is_replaced(self) -> None:
        expected = build_source_configs(include_tables=False)
        build_source_configs.cache_clear()
        shared_key = shared_catalog_cache_key(include_tables=False)
        caches["warehouse_source_catalog"].set(shared_key, "invalid json")

        assert build_source_configs(include_tables=False) == expected
        assert json.loads(caches["warehouse_source_catalog"].get(shared_key)) == expected

    def test_deploy_and_table_modes_use_separate_catalogs(self) -> None:
        without_tables = build_source_configs(include_tables=False)
        with_tables = build_source_configs(include_tables=True)
        assert all("tables" not in config for config in without_tables.values())
        assert all("tables" in config for config in with_tables.values())

        build_source_configs.cache_clear()
        caches["warehouse_source_catalog"].set(shared_catalog_cache_key(include_tables=False), "{}")
        with patch(f"{MODULE}.get_git_commit_full", return_value="next-commit"):
            assert build_source_configs(include_tables=False) == without_tables


class TestCatalogCacheConnection(SimpleTestCase):
    def test_catalog_values_use_json_serialization(self) -> None:
        catalog = {**WAREHOUSE_SOURCE_CATALOG_CACHE_CONFIG, "LOCATION": "redis://localhost:6379/15"}
        with override_settings(
            CACHES={
                "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
                "warehouse_source_catalog": catalog,
            }
        ):
            catalog_cache = caches["warehouse_source_catalog"]
            assert isinstance(catalog_cache, RedisCache)
            serialized = json.dumps({"Demo": {"name": "Demo"}})
            encoded = catalog_cache.client.encode(serialized)
            assert isinstance(encoded, bytes)
            assert json.loads(encoded) == serialized
            assert catalog_cache.client.decode(encoded) == serialized

    @parameterized.expand([("default", "warehouse_source_catalog"), ("warehouse_source_catalog", "default")])
    def test_catalog_timeout_does_not_change_default_pool(self, first: str, second: str) -> None:
        url = "redis://localhost:6379/15?socket_connect_timeout=5&socket_timeout=5"
        default_pools = ConnectionFactory({})._pools
        default_pools.pop(url, None)
        WarehouseSourceCatalogConnectionFactory._pools.pop(url, None)
        self.addCleanup(default_pools.pop, url, None)
        self.addCleanup(WarehouseSourceCatalogConnectionFactory._pools.pop, url, None)
        default = {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": url,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        }
        catalog = {**WAREHOUSE_SOURCE_CATALOG_CACHE_CONFIG, "LOCATION": url}
        with override_settings(CACHES={"default": default, "warehouse_source_catalog": catalog}):
            first_cache = caches[first]
            second_cache = caches[second]
            assert isinstance(first_cache, RedisCache)
            assert isinstance(second_cache, RedisCache)
            first_pool = first_cache.client.get_client(write=True).connection_pool
            second_pool = second_cache.client.get_client(write=True).connection_pool

        pools = {first: first_pool, second: second_pool}
        assert pools["default"] is not pools["warehouse_source_catalog"]
        assert pools["default"].connection_kwargs["socket_connect_timeout"] == 5
        assert pools["default"].connection_kwargs["socket_timeout"] == 5
        assert pools["warehouse_source_catalog"].connection_kwargs["socket_connect_timeout"] == 0.2
        assert pools["warehouse_source_catalog"].connection_kwargs["socket_timeout"] == 0.2


class TestPublicSourceConfigs(APIBaseTest):
    def test_list_returns_source_configs(self):
        response = self.client.get("/api/public_source_configs/")
        assert response.status_code == status.HTTP_200_OK

        catalog = SourceConfigMapResponse.model_validate_json(response.content).root
        assert len(catalog) > 0

    def test_matches_wizard_response(self):
        """Public endpoint returns the same data as the authenticated /wizard endpoint, plus the
        docs-only `tables` catalog the wizard deliberately omits to keep its payload small."""
        response = self.client.get("/api/public_source_configs/")
        assert response.status_code == status.HTTP_200_OK

        wizard_response = self.client.get("/api/environments/@current/external_data_sources/wizard/")
        assert wizard_response.status_code == status.HTTP_200_OK

        wizard_data = wizard_response.json()
        assert not any("tables" in config for config in wizard_data.values())

        public_without_tables = {
            source_type: {k: v for k, v in config.items() if k != "tables"}
            for source_type, config in response.json().items()
        }
        assert public_without_tables == wizard_data

    def test_accessible_without_authentication(self):
        self.client.logout()
        response = self.client.get("/api/public_source_configs/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_every_config_has_tables_array(self):
        response = self.client.get("/api/public_source_configs/")
        data = response.json()

        for source_type, config in data.items():
            assert "tables" in config, f"{source_type} missing tables"
            assert isinstance(config["tables"], list), f"{source_type} tables is not a list"

    def test_fixed_schema_source_lists_tables(self):
        """Fixed-schema API sources (e.g. Stripe) expose their documented table catalog."""
        response = self.client.get("/api/public_source_configs/")
        stripe = response.json()["Stripe"]

        tables = stripe["tables"]
        assert len(tables) > 0
        names = {t["name"] for t in tables}
        assert "Customer" in names

        for table in tables:
            assert set(table.keys()) >= {
                "name",
                "label",
                "description",
                "sync_methods",
                "incremental_fields",
                "primary_keys",
            }
            assert isinstance(table["sync_methods"], list)
            assert len(table["sync_methods"]) > 0

    def test_sql_source_returns_no_tables(self):
        """SQL sources have user-defined schemas, so the catalog is empty (renders a generic note)."""
        response = self.client.get("/api/public_source_configs/")
        assert response.json()["Postgres"]["tables"] == []

    def test_cdc_engine_is_set_for_every_source_with_change_capture(self):
        response = self.client.get("/api/public_source_configs/")

        engines = {source_type: config["cdcEngine"] for source_type, config in response.json().items()}

        assert {source_type: engine for source_type, engine in engines.items() if engine is not None} == {
            "Postgres": "postgres",
            "Supabase": "postgres",
            "Neon": "postgres",
        }

    def test_every_config_exposes_version_fields(self):
        """The external version-update automation consumes these exact field names."""
        response = self.client.get("/api/public_source_configs/")
        data = response.json()

        for source_type, config in data.items():
            assert isinstance(config["versions"], list) and len(config["versions"]) > 0, source_type
            assert config["defaultVersion"] in config["versions"], source_type
            assert config["apiDocsUrl"] is None or config["apiDocsUrl"].startswith("https://"), source_type
            assert isinstance(config["deprecatedVersions"], list), source_type

        stripe = data["Stripe"]
        assert stripe["versions"] == ["2024-09-30.acacia", "2026-10-28.endive"]
        assert stripe["defaultVersion"] == "2026-10-28.endive"
        assert stripe["apiDocsUrl"] == "https://docs.stripe.com/changelog"

    def test_many_fixed_schema_sources_list_tables(self):
        """Guard the opt-in mechanism: a large share of sources expose a static table catalog.

        ~140 sources set `lists_tables_without_credentials`; if the mechanism regresses this
        collapses toward zero. The loose threshold tolerates sources being added or removed.
        """
        response = self.client.get("/api/public_source_configs/")
        with_tables = [name for name, config in response.json().items() if config["tables"]]
        assert len(with_tables) >= 100, f"only {len(with_tables)} sources list tables"
