from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.firehydrant import (
    FireHydrantResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.settings import (
    ENDPOINTS,
    FIREHYDRANT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.source import FireHydrantSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> Any:
    return MagicMock(api_key="fhb_test", region="us")


class TestFireHydrantSourceConfig:
    def test_source_type(self) -> None:
        assert FireHydrantSource().source_type == ExternalDataSourceType.FIREHYDRANT

    def test_get_source_config_basics(self) -> None:
        config = FireHydrantSource().get_source_config
        assert config.label == "FireHydrant"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/firehydrant"
        # A finished source must not be hidden behind the unreleased flag.
        assert not config.unreleasedSource

    def test_api_key_field_is_secret_password(self) -> None:
        fields = FireHydrantSource().get_source_config.fields
        api_key = fields[0]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.name == "api_key"
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.required is True
        assert api_key.secret is True

    def test_region_field_offers_us_and_eu(self) -> None:
        # EU accounts are region-pinned; a missing EU option would leave those customers unable to
        # connect. Region is also a connection-host field so retargeting re-requires the key.
        region = next(f for f in FireHydrantSource().get_source_config.fields if isinstance(f, SourceFieldSelectConfig))
        assert region.name == "region"
        assert {o.value for o in region.options} == {"us", "eu"}
        assert region.defaultValue == "us"
        assert FireHydrantSource().connection_host_fields == ["region"]

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs table catalog can render.
        assert FireHydrantSource.lists_tables_without_credentials is True


class TestGetSchemas:
    def test_returns_every_endpoint_full_refresh_only(self) -> None:
        schemas = FireHydrantSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False

    def test_detected_primary_keys_match_settings(self) -> None:
        schemas = {s.name: s for s in FireHydrantSource().get_schemas(_config(), team_id=1)}
        for name, config in FIREHYDRANT_ENDPOINTS.items():
            assert schemas[name].detected_primary_keys == config.primary_keys

    def test_names_filter(self) -> None:
        schemas = FireHydrantSource().get_schemas(_config(), team_id=1, names=["incidents", "services"])
        assert {s.name for s in schemas} == {"incidents", "services"}

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = FireHydrantSource().get_documented_tables()
        by_name = {t["name"]: t for t in tables}
        assert set(by_name) == set(ENDPOINTS)
        # Canonical descriptions are surfaced and full refresh is always an available method.
        assert by_name["incidents"]["description"]
        assert "Full refresh" in by_name["incidents"]["sync_methods"]
        assert by_name["priorities"]["primary_keys"] == ["slug"]


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.firehydrant.io/v1/incidents?page=1&per_page=100",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.firehydrant.io/v1/runbooks?page=1&per_page=100",
            ),
            (
                "unauthorized_eu",
                "401 Client Error: Unauthorized for url: https://api.eu.firehydrant.io/v1/incidents?page=1&per_page=100",
            ),
            (
                "forbidden_eu",
                "403 Client Error: Forbidden for url: https://api.eu.firehydrant.io/v1/runbooks?page=1&per_page=100",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = FireHydrantSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.firehydrant.io', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.firehydrant.io/v1/incidents",
            ),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = FireHydrantSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestResumableWiring:
    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock(team_id=1, job_id="job-1", logger=MagicMock())
        manager = FireHydrantSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FireHydrantResumeConfig

    def test_source_for_pipeline_plumbs_api_key_and_schema(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "sentinel"

        import products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.source as source_module

        monkeypatch.setattr(source_module, "firehydrant_source", fake_source)

        manager = MagicMock()
        inputs = MagicMock(schema_name="incidents", logger=MagicMock())
        result: Any = FireHydrantSource().source_for_pipeline(_config(), manager, inputs)

        assert result == "sentinel"
        assert captured["api_key"] == "fhb_test"
        assert captured["endpoint"] == "incidents"
        assert captured["resumable_source_manager"] is manager
        assert captured["region"] == "us"


class TestValidateCredentials:
    def test_delegates_to_transport(self, monkeypatch: Any) -> None:
        import products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.source as source_module

        monkeypatch.setattr(source_module, "validate_firehydrant_credentials", lambda key, region=None: (True, None))
        valid, error = FireHydrantSource().validate_credentials(_config(), team_id=1)
        assert valid is True
        assert error is None
