import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.appfigures import (
    AppfiguresResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source import AppfiguresSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AppfiguresSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestAppfiguresSource:
    def setup_method(self):
        self.source = AppfiguresSource()
        self.team_id = 123
        self.config = AppfiguresSourceConfig(personal_access_token="pat_test")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.APPFIGURES

    def test_get_source_config(self):
        config = self.source.get_source_config
        assert config.name.value == "Appfigures"
        assert config.label == "Appfigures"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/appfigures.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/appfigures"

    def test_token_field_is_secret_password(self):
        config = self.source.get_source_config
        field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "personal_access_token"
        )
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_products_is_full_refresh_reports_and_reviews_incremental(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["products"].supports_incremental is False
        assert schemas["products"].incremental_fields == []
        for name in ("reviews", "sales_report", "revenue_report"):
            assert schemas[name].supports_incremental is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["date"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["reviews"])
        assert len(schemas) == 1
        assert schemas[0].name == "reviews"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "status,schema_name,expected_ok",
        [
            (200, None, True),
            (200, "reviews", True),
            (401, None, False),
            (401, "reviews", False),
            # 403 at source-create is a valid token missing an unrelated scope — accept it.
            (403, None, True),
            # 403 for a specific schema means the token can't sync that table — reject.
            (403, "reviews", False),
            (500, None, False),
            (None, None, False),
        ],
    )
    def test_validate_credentials(self, status, schema_name, expected_ok):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source.check_credentials",
            return_value=status,
        ):
            ok, _ = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
            assert ok is expected_ok

    def test_validate_credentials_probes_schema_specific_path(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source.check_credentials",
            return_value=200,
        ) as probe:
            self.source.validate_credentials(self.config, self.team_id, schema_name="reviews")
            probe.assert_called_once_with("pat_test", "/reviews")

    def test_validate_credentials_defaults_to_products_path(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source.check_credentials",
            return_value=200,
        ) as probe:
            self.source.validate_credentials(self.config, self.team_id)
            probe.assert_called_once_with("pat_test", "/products/mine")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.appfigures.com/v2/reviews?count=1",
            "403 Client Error: Forbidden for url: https://api.appfigures.com/v2/reports/sales",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.appfigures.com/v2/reviews",
        ],
    )
    def test_non_retryable_errors_ignore_unrelated(self, unrelated_error):
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AppfiguresResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "reviews"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01"
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source.appfigures_source"
        ) as appfigures_source:
            self.source.source_for_pipeline(self.config, manager, inputs)
            appfigures_source.assert_called_once()
            kwargs = appfigures_source.call_args.kwargs
            assert kwargs["token"] == "pat_test"
            assert kwargs["endpoint"] == "reviews"
            assert kwargs["resumable_source_manager"] is manager
            assert kwargs["should_use_incremental_field"] is True
            assert kwargs["db_incremental_field_last_value"] == "2024-01-01"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "products"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01"
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source.appfigures_source"
        ) as appfigures_source:
            self.source.source_for_pipeline(self.config, manager, inputs)
            assert appfigures_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_keyed_by_endpoint_names(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) <= set(ENDPOINTS)
        # The four shipped endpoints are all documented.
        assert set(descriptions.keys()) == set(ENDPOINTS)
