from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HoneybadgerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.honeybadger import (
    HoneybadgerResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.source import HoneybadgerSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "faults",
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


class TestHoneybadgerSource:
    def setup_method(self) -> None:
        self.source = HoneybadgerSource()
        self.team_id = 123
        self.config = HoneybadgerSourceConfig(api_key="test-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.HONEYBADGER

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Honeybadger"
        assert config.label == "Honeybadger"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/honeybadger.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/honeybadger"

        assert len(config.fields) == 1
        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url: https://app.honeybadger.io",
            "403 Client Error: Forbidden for url: https://app.honeybadger.io",
        ],
    )
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_names_and_sync_support(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)

        for endpoint in ("faults", "notices", "deploys"):
            assert schemas[endpoint].supports_incremental is True
            assert schemas[endpoint].supports_append is True
            assert len(schemas[endpoint].incremental_fields) > 0

        for endpoint in ("projects", "sites"):
            assert schemas[endpoint].supports_incremental is False
            assert schemas[endpoint].supports_append is False
            assert schemas[endpoint].incremental_fields == []

    def test_notices_are_opt_in_by_default(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # Notices fan out one request per fault against a 360 req/hour quota, so they must
        # not be part of the default table selection.
        assert schemas["notices"].should_sync_default is False
        assert all(schema.should_sync_default for name, schema in schemas.items() if name != "notices")

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["faults"])
        assert len(schemas) == 1
        assert schemas[0].name == "faults"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_documented_tables_render_without_credentials(self) -> None:
        # The public docs table catalog must build from the static endpoint list with no I/O.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid Honeybadger authentication token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.source.validate_honeybadger_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is HoneybadgerResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.source.honeybadger_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        logger = mock.MagicMock()
        inputs = _make_inputs(
            schema_name="deploys",
            logger=logger,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
            incremental_field="created_at",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="test-token",
            endpoint="deploys",
            logger=logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
            incremental_field="created_at",
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.source.honeybadger_source"
    )
    def test_source_for_pipeline_drops_cursor_when_not_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(
            should_use_incremental_field=False,
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
