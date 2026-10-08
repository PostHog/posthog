from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import SourceFieldSelectConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.source import FireHydrantSource


def _config() -> Any:
    return MagicMock(api_key="fhb_test", region="us")


class TestFireHydrantSourceConfig:
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
    def test_names_filter(self) -> None:
        schemas = FireHydrantSource().get_schemas(_config(), team_id=1, names=["incidents", "services"])
        assert {s.name for s in schemas} == {"incidents", "services"}


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
