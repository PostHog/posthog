from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign import (
    ActiveCampaignResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.source import ActiveCampaignSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    ActiveCampaignSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "contacts",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestActiveCampaignSource:
    def setup_method(self) -> None:
        self.source = ActiveCampaignSource()
        self.team_id = 123
        self.config = ActiveCampaignSourceConfig(api_url="https://acme.api-us1.com", api_key="test-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ACTIVECAMPAIGN

    def test_api_url_is_a_connection_host_field(self) -> None:
        # Changing api_url must force the api_key to be re-entered, so the stored
        # key is never sent to a freshly-specified host.
        assert self.source.connection_host_fields == ["api_url"]

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "ActiveCampaign"
        assert config.label == "ActiveCampaign"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/activecampaign.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_url", "api_key"]

        api_url_field, api_key_field = config.fields
        assert isinstance(api_url_field, SourceFieldInputConfig)
        assert api_url_field.type == SourceFieldInputConfigType.TEXT
        assert api_url_field.required is True

        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error", "Unauthorized for url"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No endpoint advertises a curl-verified server-side filter yet, so every
        # schema is full refresh only.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["contacts"])
        assert len(schemas) == 1
        assert schemas[0].name == "contacts"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            ((True, None), True, None),
            ((False, "Invalid ActiveCampaign API URL or key"), False, "Invalid ActiveCampaign API URL or key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.source.validate_active_campaign_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, str | None],
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_url, self.config.api_key)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ActiveCampaignResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.source.active_campaign_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="deals", team_id=99, job_id="job-xyz")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_url="https://acme.api-us1.com",
            api_key="test-key",
            endpoint="deals",
            team_id=99,
            job_id="job-xyz",
            resumable_source_manager=manager,
        )
