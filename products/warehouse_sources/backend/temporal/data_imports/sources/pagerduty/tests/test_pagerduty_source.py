import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.pagerduty import PagerDutyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.source import PagerDutySource
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType

PAGERDUTY_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty"


class TestPagerDutySource:
    def setup_method(self) -> None:
        self.source = PagerDutySource()
        self.config = MagicMock(api_token="tok_123")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.PAGERDUTY

    def test_source_config_shape(self) -> None:
        config = self.source.get_source_config

        assert config.label == "PagerDuty"
        assert config.iconPath == "/static/services/pagerduty.svg"
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

        assert config.fields is not None
        assert len(config.fields) == 1
        field = config.fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_token"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True

    def test_get_schemas_lists_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_incidents_supports_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}

        assert schemas["incidents"].supports_incremental is True
        assert schemas["incidents"].incremental_fields[0]["field"] == "created_at"
        assert schemas["incidents"].incremental_fields[0]["field_type"] == IncrementalFieldType.DateTime

        for name in ENDPOINTS:
            if name == "incidents":
                continue
            assert schemas[name].supports_incremental is False, name
            assert schemas[name].incremental_fields == [], name

    def test_no_endpoint_supports_append(self) -> None:
        # PagerDuty incidents mutate after creation, so append-only mode is never offered.
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert all(s.supports_append is False for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["incidents", "services"])
        assert {s.name for s in schemas} == {"incidents", "services"}

    @pytest.mark.parametrize(
        "pattern",
        [
            "401 Client Error: Unauthorized for url: https://api.pagerduty.com",
            "403 Client Error: Forbidden for url: https://api.pagerduty.com",
        ],
    )
    def test_non_retryable_errors_includes_pattern(self, pattern: str) -> None:
        assert pattern in self.source.get_non_retryable_errors()

    def test_validate_credentials_success(self) -> None:
        with patch(f"{PAGERDUTY_MODULE}.source.validate_pagerduty_credentials", return_value=(True, 200, None)):
            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)

    def test_validate_credentials_invalid_token(self) -> None:
        with patch(
            f"{PAGERDUTY_MODULE}.source.validate_pagerduty_credentials",
            return_value=(False, 401, "Invalid PagerDuty API key"),
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1)
            assert ok is False
            assert error == "Invalid PagerDuty API key"

    def test_validate_credentials_accepts_403_at_source_create(self) -> None:
        # A valid token may only be scoped to a subset of resources; don't block connection.
        with patch(
            f"{PAGERDUTY_MODULE}.source.validate_pagerduty_credentials",
            return_value=(False, 403, "Your PagerDuty API key does not have access to this resource"),
        ):
            assert self.source.validate_credentials(self.config, team_id=1, schema_name=None) == (True, None)

    def test_validate_credentials_rejects_403_for_specific_schema(self) -> None:
        with patch(
            f"{PAGERDUTY_MODULE}.source.validate_pagerduty_credentials",
            return_value=(False, 403, "Your PagerDuty API key does not have access to this resource"),
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1, schema_name="incidents")
            assert ok is False
            assert error == "Your PagerDuty API key does not have access to this resource"

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock(team_id=1, job_id="job_1", logger=MagicMock())
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PagerDutyResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        manager = MagicMock()
        inputs = MagicMock(
            schema_name="incidents",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00+00:00",
            logger=MagicMock(),
        )

        with patch(f"{PAGERDUTY_MODULE}.source.pagerduty_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "tok_123"
        assert kwargs["endpoint"] == "incidents"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00+00:00"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        manager = MagicMock()
        inputs = MagicMock(
            schema_name="services",
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00+00:00",
            logger=MagicMock(),
        )

        with patch(f"{PAGERDUTY_MODULE}.source.pagerduty_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
