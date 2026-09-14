from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gusto import GustoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gusto.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gusto.gusto import (
    GUSTO_API_VERSION_2024_04_01,
    GUSTO_API_VERSION_2026_06_15,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gusto.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gusto.source import GustoSource

INCREMENTAL_ENDPOINTS = {"payrolls", "pay_periods", "contractor_payments"}


class TestGustoSource:
    def setup_method(self) -> None:
        self.source = GustoSource()
        self.team_id = 123
        self.config = GustoSourceConfig(
            client_id="cid",
            client_secret="secret",
            refresh_token="refresh",
            environment="production",
        )

    def test_source_is_visible_to_users(self) -> None:
        # A truthy `unreleasedSource` hides the connector from the wizard entirely.
        assert not self.source.get_source_config.unreleasedSource

    def test_environment_offers_production_and_demo(self) -> None:
        # Gusto partners build against the demo host until their app is approved for production.
        field = next(f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldSelectConfig))
        assert {option.value for option in field.options} == {"production", "demo"}
        assert field.defaultValue == "production"

    def test_api_version_is_pinned_to_what_the_client_sends(self) -> None:
        # Declared oldest→newest; new sources start on the newest version.
        assert self.source.supported_versions == (GUSTO_API_VERSION_2024_04_01, GUSTO_API_VERSION_2026_06_15)
        assert self.source.default_version == GUSTO_API_VERSION_2026_06_15
        assert self.source.api_docs_url.startswith("https://")

    def test_older_version_is_deprecated_without_a_sunset_date(self) -> None:
        # Gusto publishes no end-of-life date for 2024-04-01, so the deprecation is advisory only
        # (sunset_at=None) and the default is never itself deprecated.
        deprecation = self.source.get_version_deprecation(GUSTO_API_VERSION_2024_04_01)
        assert deprecation is not None and deprecation.sunset_at is None
        assert self.source.get_version_deprecation(GUSTO_API_VERSION_2026_06_15) is None

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_only_date_filtered_endpoints_are_incremental(self, endpoint: str) -> None:
        # Gusto only filters server-side on money-movement check dates; everything else would have
        # to re-walk every page anyway, so it stays full refresh.
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is (endpoint in INCREMENTAL_ENDPOINTS)
        # Rows are restated in place (a payroll moves from calculated to processed), so merge only.
        assert schema.supports_append is False

    @parameterized.expand([(endpoint,) for endpoint in INCREMENTAL_ENDPOINTS])
    def test_canonical_descriptions_document_the_cursor_column(self, endpoint: str) -> None:
        cursor = INCREMENTAL_FIELDS[endpoint][0]["field"]
        assert cursor in (CANONICAL_DESCRIPTIONS[endpoint].get("columns") or {})

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.gusto.com/oauth/token"),
            ("bad_request", "400 Client Error: Bad Request for url: https://api.gusto.com/oauth/token"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.gusto.com/v1/companies/c-1/payrolls"),
            # A pin that reaches end of life 406s; retrying can't recover it.
            ("version_end_of_life", "406 Client Error: Not Acceptable for url: https://api.gusto.com/v1/me"),
        ]
    )
    def test_auth_failures_are_non_retryable(self, _name: str, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.gusto.com/v1/me"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.gusto.com/v1/me"),
        ]
    )
    def test_transient_failures_stay_retryable(self, _name: str, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    def _inputs(self, **overrides: Any) -> mock.MagicMock:
        inputs = mock.MagicMock()
        inputs.schema_name = "employees"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None
        inputs.api_version = None
        for key, value in overrides.items():
            setattr(inputs, key, value)
        return inputs

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gusto.source.gusto_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        manager = mock.MagicMock()
        self.source.source_for_pipeline(self.config, manager, self._inputs())

        kwargs = mock_source.call_args.kwargs
        assert kwargs["environment"] == "production"
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "secret"
        assert kwargs["refresh_token"] == "refresh"
        assert kwargs["endpoint"] == "employees"
        assert kwargs["api_version"] == GUSTO_API_VERSION_2026_06_15
        assert kwargs["resumable_source_manager"] is manager

    @parameterized.expand([(GUSTO_API_VERSION_2024_04_01,), (GUSTO_API_VERSION_2026_06_15,)])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gusto.source.gusto_source")
    def test_source_for_pipeline_honors_the_pinned_version(self, pin: str, mock_source: mock.MagicMock) -> None:
        # A source pinned to a still-supported (including deprecated) version syncs under that pin,
        # never silently on the new default.
        self.source.source_for_pipeline(self.config, mock.MagicMock(), self._inputs(api_version=pin))
        assert mock_source.call_args.kwargs["api_version"] == pin

    @parameterized.expand(
        [
            ("incremental_run_passes_the_watermark", True, "2024-05-06"),
            ("full_refresh_ignores_a_stale_watermark", False, None),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gusto.source.gusto_source")
    def test_watermark_is_only_used_on_incremental_runs(
        self,
        _name: str,
        should_use_incremental_field: bool,
        expected: Any,
        mock_source: mock.MagicMock,
    ) -> None:
        inputs = self._inputs(
            schema_name="payrolls",
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value="2024-05-06",
        )
        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] == expected

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        with pytest.raises(ValueError, match="Unknown Gusto schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), self._inputs(schema_name="not_a_table"))
