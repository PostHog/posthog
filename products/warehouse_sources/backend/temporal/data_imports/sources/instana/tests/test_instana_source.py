from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InstanaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.instana.instana import (
    InstanaHostNotAllowedError,
    InstanaResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instana.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.instana.source import InstanaSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "events",
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


class TestInstanaSource:
    def setup_method(self) -> None:
        self.source = InstanaSource()
        self.team_id = 123
        self.config = InstanaSourceConfig(base_url="https://unit-tenant.instana.io", api_token="secret-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.INSTANA

    def test_base_url_is_a_connection_host_field(self) -> None:
        # Changing the base URL must force the token to be re-entered so it's never
        # sent to a freshly-specified host.
        assert self.source.connection_host_fields == ["base_url"]

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Instana"
        assert config.label == "IBM Instana Observability"
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

        base_url_field, api_token_field = config.fields

        assert isinstance(base_url_field, SourceFieldInputConfig)
        assert base_url_field.name == "base_url"
        assert base_url_field.type == SourceFieldInputConfigType.TEXT
        assert base_url_field.required is True
        assert base_url_field.secret is False

        assert isinstance(api_token_field, SourceFieldInputConfig)
        assert api_token_field.name == "api_token"
        assert api_token_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_token_field.required is True
        assert api_token_field.secret is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert any(expected_key in key for key in self.source.get_non_retryable_errors())

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)

        assert schemas["events"].supports_incremental is True
        # Events mutate while open (state/end change), so append mode is never offered.
        assert schemas["events"].supports_append is False
        assert schemas["events"].incremental_fields == [
            {
                "label": "start",
                "type": "integer",
                "field": "start",
                "field_type": "integer",
            }
        ]
        assert schemas["events"].description is not None

        for name in set(ENDPOINTS) - {"events"}:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["applications"])
        assert [s.name for s in schemas] == ["applications"]

    @pytest.mark.parametrize(
        ("probe_result", "expected_valid"),
        [
            ((True, 200), True),
            # 403 = genuine token missing the probe's scope; must not block source-create.
            ((False, 403), True),
            ((False, 401), False),
            ((False, 500), False),
            ((False, None), False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.instana.source.validate_instana_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        probe_result: tuple[bool, int | None],
        expected_valid: bool,
    ) -> None:
        mock_validate.return_value = probe_result

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with("https://unit-tenant.instana.io", "secret-token", self.team_id)

    @pytest.mark.parametrize("exception", [ValueError("bad url"), InstanaHostNotAllowedError("blocked")])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.instana.source.validate_instana_credentials"
    )
    def test_validate_credentials_surfaces_url_errors(
        self, mock_validate: mock.MagicMock, exception: Exception
    ) -> None:
        mock_validate.side_effect = exception

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == str(exception)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is InstanaResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.instana.source.instana_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="applications", team_id=99)
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            base_url="https://unit-tenant.instana.io",
            api_token="secret-token",
            endpoint="applications",
            team_id=99,
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.instana.source.instana_source")
    def test_source_for_pipeline_drops_watermark_when_incremental_disabled(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value=1767225600000)
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.instana.source.instana_source")
    def test_source_for_pipeline_passes_watermark_when_incremental_enabled(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(should_use_incremental_field=True, db_incremental_field_last_value=1767225600000)
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1767225600000
