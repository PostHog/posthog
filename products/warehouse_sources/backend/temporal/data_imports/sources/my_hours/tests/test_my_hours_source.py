import pytest
from unittest import mock

import structlog
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.myhours import (
    MyHoursSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.source import MyHoursSource


def _make_inputs(schema_name: str = "clients") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestMyHoursSource:
    def setup_method(self) -> None:
        self.source = MyHoursSource()
        self.team_id = 123
        self.config = MyHoursSourceConfig(api_key="mh-key")

    @parameterized.expand(
        [
            ("reachable", 200, True, None),
            ("unauthorized", 401, False, "Invalid My Hours API key"),
            ("forbidden", 403, False, "Invalid My Hours API key"),
            ("server_error", 500, False, "My Hours returned HTTP 500"),
            ("connection_error", 0, False, "Could not connect to My Hours: boom"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.source.check_access")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_check: mock.MagicMock,
    ) -> None:
        message = (
            "My Hours returned HTTP 500"
            if status == 500
            else ("Could not connect to My Hours: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.source.my_hours_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="clients")

        self.source.source_for_pipeline(self.config, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "mh-key"
        assert kwargs["endpoint"] == "clients"

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = _make_inputs(schema_name="not_a_table")
        with pytest.raises(ValueError, match="Unknown My Hours schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, inputs)
