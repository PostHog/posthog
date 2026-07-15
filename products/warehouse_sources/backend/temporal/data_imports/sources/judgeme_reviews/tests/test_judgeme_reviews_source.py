import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    JudgeMeReviewsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.judgeme_reviews import (
    JudgeMeReviewsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.source import JudgeMeReviewsSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestJudgeMeReviewsSource:
    def setup_method(self) -> None:
        self.source = JudgeMeReviewsSource()
        self.team_id = 123
        self.config = JudgeMeReviewsSourceConfig(shop_domain="example.myshopify.com", api_token="jm-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.JUDGEMEREVIEWS

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Judge.me Reviews"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/judgeme-reviews"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["shop_domain", "api_token"]

    def test_api_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_shop_domain_field_is_plain_text(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "shop_domain")
        assert field.type == SourceFieldInputConfigType.TEXT
        assert field.secret is False
        assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # shop_domain selects which shop's data the fixed judge.me host returns; the token is never
        # sent to a user-controlled host, so retargeting it cannot exfiltrate the credential.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["products"])
        assert len(schemas) == 1
        assert schemas[0].name == "products"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://judge.me/api/v1/reviews?shop_domain=example.myshopify.com&page=1",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://judge.me/api/v1/products?shop_domain=example.myshopify.com&page=1",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://judge.me/api/v1/reviews"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://judge.me/api/v1/products"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid_credentials", (False, "Invalid Judge.me shop domain or API token")),
            ("connect_error", (False, "Could not connect to Judge.me: boom")),
        ]
    )
    def test_validate_credentials_delegates_to_probe(self, _name: str, underlying: tuple[bool, str | None]) -> None:
        # The status → message mapping is covered by the judgeme_reviews.validate_credentials unit
        # test; here we only guard that the source passes both credentials and returns the probe
        # result unchanged.
        with mock.patch.object(source_module, "validate_credentials", return_value=underlying) as mock_validate:
            result = self.source.validate_credentials(self.config, self.team_id)
        assert result == underlying
        mock_validate.assert_called_once_with("jm-token", "example.myshopify.com")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is JudgeMeReviewsResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.source.judgeme_reviews_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "reviews"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "jm-token"
        assert kwargs["shop_domain"] == "example.myshopify.com"
        assert kwargs["endpoint"] == "reviews"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Judge.me schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
