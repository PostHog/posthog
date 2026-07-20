from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.asknicely import AskNicelyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.source import AsknicelySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AsknicelySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "responses",
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


class TestAsknicelySource:
    def setup_method(self) -> None:
        self.source = AsknicelySource()
        self.team_id = 123
        self.config = AsknicelySourceConfig(subdomain="acme", api_key="test-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ASKNICELY

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # Changing the subdomain retargets which AskNicely tenant the stored key is
        # sent to, so it must force the API key to be re-entered.
        assert self.source.connection_host_fields == ["subdomain"]

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Asknicely"
        assert config.label == "AskNicely"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA

        subdomain_field, api_key_field = config.fields
        assert isinstance(subdomain_field, SourceFieldInputConfig)
        assert subdomain_field.name == "subdomain"
        assert subdomain_field.type == SourceFieldInputConfigType.TEXT
        assert subdomain_field.required is True

        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error", "Unauthorized for url"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert [s.name for s in schemas] == ["responses"]
        responses = schemas[0]
        assert responses.supports_incremental is True
        assert responses.supports_append is True
        assert [f["field"] for f in responses.incremental_fields] == ["responded"]

    def test_get_schemas_filtered_by_names(self) -> None:
        assert [s.name for s in self.source.get_schemas(self.config, self.team_id, names=["responses"])] == [
            "responses"
        ]
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize("subdomain", ["not a subdomain", "acme.asknice.ly", "evil/../path", ""])
    def test_validate_credentials_rejects_bad_subdomain_without_a_request(self, subdomain: str) -> None:
        config = AsknicelySourceConfig(subdomain=subdomain, api_key="test-key")

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.source.validate_asknicely_credentials"
        ) as mock_validate:
            is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message is not None and "subdomain" in error_message
        mock_validate.assert_not_called()

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid"),
        [
            ((True, None), True),
            ((False, "Invalid AskNicely API key"), False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.source.validate_asknicely_credentials"
    )
    def test_validate_credentials_delegates_to_transport(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, str | None],
        expected_valid: bool,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == mock_return[1]
        mock_validate.assert_called_once_with("acme", "test-key")

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AskNicelyResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.source.asknicely_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
            incremental_field="responded",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            subdomain="acme",
            api_key="test-key",
            endpoint="responses",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.source.asknicely_source")
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        # A stale watermark left over from a previous incremental run must not leak into a
        # full-refresh sync, or the refresh would silently skip older responses.
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value=1700000000)

        self.source.source_for_pipeline(self.config, mock.MagicMock(spec=ResumableSourceManager), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
