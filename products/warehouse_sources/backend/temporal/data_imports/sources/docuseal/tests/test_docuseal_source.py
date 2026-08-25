from typing import cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.docuseal import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.docuseal.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.docuseal.source import DocusealSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.docuseal import (
    DocusealSourceConfig,
)


def _config(api_key: str = "tok", region: str = "us") -> DocusealSourceConfig:
    return DocusealSourceConfig(api_key=api_key, region=region)  # type: ignore[arg-type]


class TestDocusealSourceConfig:
    def test_visible_and_alpha(self) -> None:
        cfg = DocusealSource().get_source_config
        # A finished source ships visible (no unreleasedSource) and labelled alpha.
        assert cfg.unreleasedSource is None
        assert cfg.releaseStatus == ReleaseStatus.ALPHA
        assert cfg.category == DataWarehouseSourceCategory.SALES
        assert cfg.docsUrl == "https://posthog.com/docs/cdp/sources/docuseal"

    def test_region_is_a_connection_host_field(self) -> None:
        # `region` decides which host the stored API key is sent to, so changing it must force the
        # editor to re-enter the secret instead of replaying it against a different host.
        assert DocusealSource().connection_host_fields == ["region"]


class TestDocusealSchemas:
    def test_lists_all_endpoints_as_full_refresh(self) -> None:
        schemas = {s.name: s for s in DocusealSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        for schema in schemas.values():
            # No server-side time filter and mutable records -> full refresh only.
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_names_filter_subsets_schemas(self) -> None:
        schemas = DocusealSource().get_schemas(_config(), team_id=1, names=["submissions"])
        assert [s.name for s in schemas] == ["submissions"]

    def test_lists_tables_without_credentials_for_docs(self) -> None:
        source = DocusealSource()
        assert source.lists_tables_without_credentials is True
        tables = source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        for table in tables:
            assert table["sync_methods"] == ["Full refresh"]


class TestDocusealNonRetryableErrors:
    @parameterized.expand(
        [
            ("us_unauthorized", "401 Client Error: Unauthorized for url: https://api.docuseal.com/templates?limit=100"),
            ("eu_unauthorized", "401 Client Error: Unauthorized for url: https://api.docuseal.eu/submissions"),
            ("us_forbidden", "403 Client Error: Forbidden for url: https://api.docuseal.com/submitters"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = DocusealSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.docuseal.com/templates"),
            ("rate_limit", "429 Client Error: Too Many Requests for url: https://api.docuseal.com/submissions"),
            ("timeout", "HTTPSConnectionPool(host='api.docuseal.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = DocusealSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestDocusealPipelineWiring:
    def test_source_for_pipeline_plumbs_inputs(self) -> None:
        captured: dict[str, object] = {}

        def fake_source(**kwargs: object) -> object:
            captured.update(kwargs)
            return "sentinel"

        inputs = MagicMock()
        inputs.schema_name = "submissions"
        inputs.team_id = 7
        inputs.job_id = "job-123"
        manager = MagicMock()

        with patch.object(source_module, "docuseal_source", side_effect=fake_source) as mock_source:
            result = DocusealSource().source_for_pipeline(_config(region="eu"), manager, inputs)

        assert cast(object, result) == "sentinel"
        mock_source.assert_called_once()
        assert captured["api_key"] == "tok"
        assert captured["region"] == "eu"
        assert captured["endpoint"] == "submissions"
        assert captured["team_id"] == 7
        assert captured["job_id"] == "job-123"
        assert captured["resumable_source_manager"] is manager
