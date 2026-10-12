from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opuswatch import (
    OPUSWatchSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opuswatch.source import OPUSWatchSource


def _make_inputs(
    schema_name: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="updatedTimestamp" if should_use_incremental_field else None,
        incremental_field_type=None,
        job_id="job-id",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestOPUSWatchSource:
    def setup_method(self):
        self.source = OPUSWatchSource()

    @pytest.mark.parametrize(
        ("start_date", "expected_error_fragment"),
        [
            ("2025-01-01", "YYYYMMDD"),
            ("2025011", "YYYYMMDD"),
            ("20251301", "not a valid date"),
            ("20250230", "not a valid date"),
        ],
    )
    def test_validate_credentials_rejects_bad_start_date_without_calling_api(
        self, start_date: str, expected_error_fragment: str
    ):
        config = OPUSWatchSourceConfig(api_key="k", start_date=start_date)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.opuswatch.source.validate_opuswatch_credentials"
        ) as mock_validate:
            valid, error = self.source.validate_credentials(config, team_id=1)

        assert valid is False
        assert error is not None and expected_error_fragment in error
        mock_validate.assert_not_called()

    @pytest.mark.parametrize(
        ("start_date", "api_result", "expected_valid"),
        [
            ("20250101", True, True),
            (None, True, True),
            ("  ", True, True),
            ("20250101", False, False),
        ],
    )
    def test_validate_credentials_probes_api(self, start_date: Optional[str], api_result: bool, expected_valid: bool):
        config = OPUSWatchSourceConfig(api_key="the-key", start_date=start_date)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.opuswatch.source.validate_opuswatch_credentials",
            return_value=api_result,
        ) as mock_validate:
            valid, error = self.source.validate_credentials(config, team_id=1)

        assert valid is expected_valid
        assert (error is None) is expected_valid
        mock_validate.assert_called_once_with("the-key")

    @pytest.mark.parametrize(
        ("should_use_incremental_field", "expected_last_value"),
        [
            (True, "2025-01-05T00:00:00Z"),
            (False, None),
        ],
    )
    def test_source_for_pipeline_forwards_watermark_only_for_incremental_syncs(
        self, should_use_incremental_field: bool, expected_last_value: Optional[str]
    ):
        config = OPUSWatchSourceConfig(api_key="k")
        inputs = _make_inputs(
            "registrations",
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value="2025-01-05T00:00:00Z",
        )
        manager = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.opuswatch.source.opuswatch_source"
        ) as mock_source:
            mock_source.return_value.name = "registrations"
            self.source.source_for_pipeline(config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is should_use_incremental_field
        assert kwargs["db_incremental_field_last_value"] == expected_last_value
        assert kwargs["resumable_source_manager"] is manager
