from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.settings import (
    EASYPROMOS_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.source import EasypromosSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.easypromos import (
    EasypromosSourceConfig,
)


class TestSourceConfig:
    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog, so the public docs can render the table list.
        assert EasypromosSource.lists_tables_without_credentials is True


class TestGetSchemas:
    def test_returns_every_endpoint(self) -> None:
        schemas = EasypromosSource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_full_refresh_only(self) -> None:
        for schema in EasypromosSource().get_schemas(MagicMock(), team_id=1):
            assert schema.supports_incremental is False, schema.name
            assert schema.supports_append is False, schema.name

    def test_should_sync_default_mirrors_settings(self) -> None:
        schemas = {s.name: s for s in EasypromosSource().get_schemas(MagicMock(), team_id=1)}
        for name, config in EASYPROMOS_ENDPOINTS.items():
            assert schemas[name].should_sync_default is config.should_sync_default

    def test_names_filter(self) -> None:
        schemas = EasypromosSource().get_schemas(MagicMock(), team_id=1, names=["promotions", "users"])
        assert {s.name for s in schemas} == {"promotions", "users"}

    def test_fan_out_description_mentions_per_promotion(self) -> None:
        schemas = {s.name: s for s in EasypromosSource().get_schemas(MagicMock(), team_id=1)}
        assert "per promotion" in (schemas["users"].description or "")


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.easypromosapp.com/v2/promotions"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.easypromosapp.com/v2/users/1"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        errors = EasypromosSource().get_non_retryable_errors()
        assert any(key in observed for key in errors)

    @parameterized.expand(
        [
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.easypromosapp.com/v2/promotions",
            ),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.easypromosapp.com/v2/users/1",
            ),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed: str) -> None:
        errors = EasypromosSource().get_non_retryable_errors()
        assert not any(key in observed for key in errors)


class TestSourceForPipeline:
    def test_plumbs_endpoint_and_keys(self) -> None:
        config = EasypromosSourceConfig(access_token="tok")
        inputs = MagicMock()
        inputs.schema_name = "participations"
        inputs.logger = MagicMock()
        response = EasypromosSource().source_for_pipeline(config, MagicMock(), inputs)
        assert response.name == "participations"
        assert response.primary_keys == EASYPROMOS_ENDPOINTS["participations"].primary_keys


class TestCanonicalDescriptions:
    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = EasypromosSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
