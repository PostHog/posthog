from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SumoLogicSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.source import SumoLogicSource
from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.sumo_logic import SumoLogicResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "logs",
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


class TestSumoLogicSource:
    def setup_method(self) -> None:
        self.source = SumoLogicSource()
        self.team_id = 123
        self.config = SumoLogicSourceConfig(
            access_id="suAbc", access_key="sk-secret", deployment="eu", search_query="_sourceCategory=prod"
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SUMOLOGIC

    def test_deployment_is_a_connection_host_field(self) -> None:
        # Changing the deployment must force the secrets to be re-entered so they're never
        # sent to a freshly-specified host.
        assert self.source.connection_host_fields == ["deployment"]

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "SumoLogic"
        assert config.label == "Sumo Logic"
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/sumo-logic"

        deployment_field, access_id_field, access_key_field, search_query_field = config.fields

        assert isinstance(deployment_field, SourceFieldSelectConfig)
        assert deployment_field.name == "deployment"
        assert deployment_field.required is True
        assert deployment_field.defaultValue == "us1"
        assert {o.value for o in deployment_field.options} == {
            "us1",
            "us2",
            "au",
            "ca",
            "de",
            "eu",
            "fed",
            "in",
            "jp",
            "kr",
        }

        assert isinstance(access_id_field, SourceFieldInputConfig)
        assert access_id_field.name == "access_id"
        assert access_id_field.required is True
        assert access_id_field.secret is False

        assert isinstance(access_key_field, SourceFieldInputConfig)
        assert access_key_field.name == "access_key"
        assert access_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert access_key_field.required is True
        assert access_key_field.secret is True

        assert isinstance(search_query_field, SourceFieldInputConfig)
        assert search_query_field.name == "search_query"
        assert search_query_field.required is False

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_only_logs_is_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["logs"].supports_incremental is True
        assert schemas["logs"].supports_append is True
        assert schemas["logs"].incremental_fields == [
            {
                "label": "message_time",
                "type": "datetime",
                "field": "message_time",
                "field_type": "datetime",
            }
        ]

        for name in set(ENDPOINTS) - {"logs"}:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["monitors"])
        assert len(schemas) == 1
        assert schemas[0].name == "monitors"

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid"),
        [
            ((True, None), True),
            ((False, "Invalid Sumo Logic access ID or access key."), False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.source.validate_sumo_logic_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, mock_return: tuple[bool, str | None], expected_valid: bool
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == mock_return[1]
        mock_validate.assert_called_once_with("eu", "suAbc", "sk-secret")

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SumoLogicResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.source.sumo_logic_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="monitors")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            deployment="eu",
            access_id="suAbc",
            access_key="sk-secret",
            endpoint="monitors",
            search_query="_sourceCategory=prod",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.source.sumo_logic_source")
    def test_source_for_pipeline_passes_incremental_value_when_enabled(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(
            schema_name="logs",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="message_time",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
