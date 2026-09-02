from typing import Any, Optional

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.servicem8 import (
    Servicem8SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicem8.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicem8.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.servicem8.source import Servicem8Source

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.servicem8.source"


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "Job",
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


class TestServiceM8Source:
    def setup_method(self) -> None:
        self.source = Servicem8Source()
        self.team_id = 123
        self.config = Servicem8SourceConfig(api_key="sm8-key")

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.servicem8.com"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.servicem8.com"),
        ]
    )
    def test_non_retryable_errors(self, _name: str, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_canonical_descriptions_document_the_primary_key(self, endpoint: str) -> None:
        columns = CANONICAL_DESCRIPTIONS[endpoint]["columns"]
        assert "uuid" in columns

    @parameterized.expand(
        [
            ("valid", True, True, None),
            ("invalid", False, False, "Invalid credentials"),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        mock_return: bool,
        expected_valid: bool,
        expected_message: Optional[str],
    ) -> None:
        with mock.patch(f"{SOURCE_MODULE}.validate_servicem8_credentials", return_value=mock_return) as mock_validate:
            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert message == expected_message
        mock_validate.assert_called_once_with("sm8-key")

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = _make_inputs(schema_name="Company")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        with mock.patch(f"{SOURCE_MODULE}.servicem8_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="sm8-key",
            endpoint="Company",
            team_id=123,
            job_id="job-1",
            resumable_source_manager=manager,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    def test_watermark_is_dropped_when_incremental_is_off(self) -> None:
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value="2026-05-01")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        with mock.patch(f"{SOURCE_MODULE}.servicem8_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None

    def test_watermark_is_passed_when_incremental_is_on(self) -> None:
        inputs = _make_inputs(should_use_incremental_field=True, db_incremental_field_last_value="2026-05-01")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        with mock.patch(f"{SOURCE_MODULE}.servicem8_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["db_incremental_field_last_value"] == "2026-05-01"
