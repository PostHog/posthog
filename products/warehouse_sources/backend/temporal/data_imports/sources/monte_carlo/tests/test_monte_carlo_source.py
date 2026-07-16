from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MonteCarloSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.monte_carlo import (
    MonteCarloResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.source import MonteCarloSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "alerts",
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestMonteCarloSource:
    def setup_method(self) -> None:
        self.source = MonteCarloSource()
        self.config = MonteCarloSourceConfig(api_key_id="key-id", api_key_secret="key-secret")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.MONTECARLO

    def test_source_config_is_released_alpha(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Monte Carlo"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_source_config_fields(self) -> None:
        fields = {f.name: f for f in self.source.get_source_config.fields}
        assert set(fields.keys()) == {"api_key_id", "api_key_secret"}
        api_key_id = fields["api_key_id"]
        api_key_secret = fields["api_key_secret"]
        assert isinstance(api_key_id, SourceFieldInputConfig)
        assert isinstance(api_key_secret, SourceFieldInputConfig)
        assert api_key_id.type == SourceFieldInputConfigType.TEXT
        assert api_key_id.required is True
        assert api_key_secret.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_secret.secret is True

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert [s.name for s in schemas] == list(ENDPOINTS)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["alerts", "monitors"])
        assert {s.name for s in schemas} == {"alerts", "monitors"}

    @parameterized.expand(
        [
            ("alerts", True),
            ("monitors", False),
            ("tables", False),
            ("users", False),
            ("warehouses", False),
        ]
    )
    def test_incremental_support_per_endpoint(self, endpoint: str, supports_incremental: bool) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is supports_incremental
        # Alerts mutate in place (status/severity), so no endpoint offers append mode.
        assert schema.supports_append is False

    def test_alerts_offers_created_and_updated_time_cursors(self) -> None:
        alerts = next(s for s in self.source.get_schemas(self.config, team_id=1) if s.name == "alerts")
        assert [f["field"] for f in alerts.incremental_fields] == ["createdTime", "updatedTime"]

    @parameterized.expand([(True, None), (False, "Invalid Monte Carlo API key ID or secret")])
    def test_validate_credentials(self, is_valid: bool, expected_error: str | None) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.source.validate_monte_carlo_credentials",
            return_value=is_valid,
        ) as mock_validate:
            result, error = self.source.validate_credentials(self.config, team_id=1)

        assert result is is_valid
        assert error == expected_error
        mock_validate.assert_called_once_with("key-id", "key-secret")

    def test_non_retryable_errors_cover_auth_failures(self) -> None:
        errors = self.source.get_non_retryable_errors()
        assert any("401" in key and "api.getmontecarlo.com" in key for key in errors)
        assert any("403" in key and "api.getmontecarlo.com" in key for key in errors)

    def test_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MonteCarloResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = _make_inputs(
            schema_name="alerts",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-01T00:00:00Z",
            incremental_field="createdTime",
        )
        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.source.monte_carlo_source"
        ) as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key_id="key-id",
            api_key_secret="key-secret",
            endpoint="alerts",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-01T00:00:00Z",
            incremental_field="createdTime",
        )

    def test_source_for_pipeline_drops_watermark_for_full_refresh(self) -> None:
        inputs = _make_inputs(
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-06-01T00:00:00Z",
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.source.monte_carlo_source"
        ) as mock_source:
            self.source.source_for_pipeline(self.config, MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
        for entry in descriptions.values():
            assert entry["description"]
            assert entry["columns"]

    def test_documented_tables_render_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
