from typing import Optional

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.applovin import (
    AUTH_ERROR_PREFIX,
    BAD_REQUEST_ERROR_PREFIX,
    TRANSIENT_ERROR_PREFIX,
    AppLovinResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.settings import (
    APPLOVIN_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.source import AppLovinSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.applovin import (
    AppLovinSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.applovin.source"


class TestAppLovinSource:
    def setup_method(self) -> None:
        self.source = AppLovinSource()
        self.team_id = 123
        self.config = AppLovinSourceConfig(api_key="report-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.APPLOVIN

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "AppLovin"
        assert config.label == "AppLovin"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/applovin.png"
        assert [field.name for field in config.fields] == ["api_key"]

    def test_report_key_field_is_a_secret_password(self) -> None:
        field = next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldInputConfig) and f.name == "api_key"
        )

        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_lists_tables_without_credentials(self) -> None:
        # `get_schemas` is a static catalog, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")

    def test_get_schemas(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name, schema in schemas.items():
            # Every endpoint filters server-side on `day` via start/end.
            assert schema.supports_incremental is True
            assert schema.incremental_fields == INCREMENTAL_FIELDS[name]
            # Aggregate rows restate for a few days, so append would duplicate them.
            assert schema.supports_append is False
            assert schema.detected_primary_keys == APPLOVIN_ENDPOINTS[name].primary_keys

    @pytest.mark.parametrize(
        "names, expected",
        [
            (["max_ad_revenue"], ["max_ad_revenue"]),
            (["max_cohort_sessions", "publisher_report"], ["publisher_report", "max_cohort_sessions"]),
            (["nope"], []),
        ],
    )
    def test_get_schemas_filtered_by_names(self, names: list[str], expected: list[str]) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=names)

        assert sorted(schema.name for schema in schemas) == sorted(expected)

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid AppLovin Report Key"),
        ],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_applovin_credentials")
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        probe_result: bool,
        expected_valid: bool,
        expected_message: Optional[str],
    ) -> None:
        mock_validate.return_value = probe_result

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("report-key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            f"{AUTH_ERROR_PREFIX}: status=403, endpoint=/maxReport",
            f"{BAD_REQUEST_ERROR_PREFIX}: status=400, endpoint=/report, body=Invalid column",
            f"{AUTH_ERROR_PREFIX}: body code=401, endpoint=/maxCohort",
        ],
    )
    def test_non_retryable_errors_match_the_raised_messages(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "AppLovin request failed: HTTPSConnectionPool(host='r.applovin.com', port=443): timed out",
            f"{TRANSIENT_ERROR_PREFIX}: status=503, endpoint=/maxReport",
            f"{TRANSIENT_ERROR_PREFIX}: status=429, endpoint=/report",
            "500 Server Error for url: https://r.applovin.com/maxReport",
        ],
    )
    def test_transient_errors_stay_retryable(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AppLovinResumeConfig

    @mock.patch(f"{_SOURCE_MODULE}.applovin_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_applovin_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "max_ad_revenue"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-07-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_applovin_source.call_args.kwargs
        assert kwargs["api_key"] == "report-key"
        assert kwargs["endpoint"] == "max_ad_revenue"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-07-01"

    @mock.patch(f"{_SOURCE_MODULE}.applovin_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_applovin_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "publisher_report"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-07-01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_applovin_source.call_args.kwargs["db_incremental_field_last_value"] is None


class TestAppLovinCanonicalDescriptions:
    def setup_method(self) -> None:
        self.source = AppLovinSource()

    def test_every_endpoint_is_documented(self) -> None:
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_documented_columns_are_columns_the_source_requests(self, endpoint: str) -> None:
        # A typo here would ship a description for a column that never lands in the table.
        documented = set(CANONICAL_DESCRIPTIONS[endpoint].get("columns", {}))
        assert documented <= set(APPLOVIN_ENDPOINTS[endpoint].columns)
        assert documented == set(APPLOVIN_ENDPOINTS[endpoint].columns)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_each_entry_has_a_description_and_docs_url(self, endpoint: str) -> None:
        entry = CANONICAL_DESCRIPTIONS[endpoint]

        assert entry["description"]
        assert str(entry["docs_url"]).startswith("https://")
