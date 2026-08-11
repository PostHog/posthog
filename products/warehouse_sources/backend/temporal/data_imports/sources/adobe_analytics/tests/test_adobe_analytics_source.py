import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.adobe_analytics import (
    AdobeAnalyticsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.source import AdobeAnalyticsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adobeanalytics import (
    AdobeAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.source"


class TestAdobeAnalyticsSource:
    def setup_method(self) -> None:
        self.source = AdobeAnalyticsSource()
        self.team_id = 123
        self.config = AdobeAnalyticsSourceConfig(
            client_id="cid",
            client_secret="sec",
            report_suite_id="rs1",
            global_company_id="gcid",
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ADOBEANALYTICS

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "AdobeAnalytics"
        assert config.label == "Adobe Analytics"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/adobe_analytics.png"

        assert [f.name for f in config.fields] == [
            "client_id",
            "client_secret",
            "report_suite_id",
            "global_company_id",
            "report_dimension",
            "report_metrics",
            "start_date",
        ]

    def test_client_secret_is_a_redacted_password_field(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "client_secret")

        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    @pytest.mark.parametrize(
        "field_name",
        ["global_company_id", "report_dimension", "report_metrics", "start_date"],
    )
    def test_derivable_fields_are_optional(self, field_name: str) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == field_name)

        assert field.required is False

    @pytest.mark.parametrize(
        "observed_error",
        [
            "400 Client Error: Bad Request for url: https://ims-na1.adobelogin.com/ims/token/v3",
            "401 Client Error: Unauthorized for url: https://analytics.adobe.io/api/gcid/reports",
            "403 Client Error: Forbidden for url: https://analytics.adobe.io/api/gcid/segments",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://analytics.adobe.io/api/gcid/reports",
            "500 Server Error for url: https://analytics.adobe.io/api/gcid/reports",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_do_not_swallow_transient_or_unrelated_failures(self, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_lists_the_endpoint_catalog(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Only the reporting stream has a server-side date filter to sync incrementally on.
        assert {schema.name for schema in schemas if schema.supports_incremental} == {"report"}

    def test_report_schema_advertises_its_date_cursor(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["report"].incremental_fields == INCREMENTAL_FIELDS["report"]
        assert [f["field"] for f in schemas["report"].incremental_fields] == ["date"]
        assert schemas["segments"].incremental_fields == []
        assert schemas["segments"].supports_append is False

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["report"])

        assert [schema.name for schema in schemas] == ["report"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_without_credentials(self) -> None:
        tables = self.source.get_documented_tables()

        assert {table["name"] for table in tables} == set(ENDPOINTS)
        report = next(table for table in tables if table["name"] == "report")
        assert report["primary_keys"] == ["rsid", "date", "item_id"]
        assert report["description"] is not None

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "transport_result",
        [(True, None), (False, "Adobe Analytics rejected the credentials.")],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_adobe_analytics_credentials")
    def test_validate_credentials_delegates_to_the_transport(
        self, mock_validate: mock.MagicMock, transport_result: tuple[bool, str | None]
    ) -> None:
        mock_validate.return_value = transport_result

        assert self.source.validate_credentials(self.config, self.team_id) == transport_result
        assert mock_validate.call_args.args[:3] == ("cid", "sec", "gcid")

    def test_resumable_manager_is_namespaced_per_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "report"

        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AdobeAnalyticsResumeConfig
        assert manager._namespace == "report"

    @mock.patch(f"{_SOURCE_MODULE}.adobe_analytics_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "report"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-05-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "sec"
        assert kwargs["global_company_id"] == "gcid"
        assert kwargs["report_suite_id"] == "rs1"
        assert kwargs["endpoint"] == "report"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01"

    @mock.patch(f"{_SOURCE_MODULE}.adobe_analytics_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "segments"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-05-01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
