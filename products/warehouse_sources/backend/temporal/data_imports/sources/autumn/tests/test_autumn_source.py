from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.source import AutumnSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.autumn import AutumnSourceConfig


def _make_inputs(
    schema_name: str = "Customers",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
    api_version: Optional[str] = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field=incremental_field,
        incremental_field_type=None,
        job_id="job-id",
        logger=MagicMock(),
        reset_pipeline=False,
        api_version=api_version,
    )


class TestAutumnSource:
    def setup_method(self) -> None:
        self.source = AutumnSource()
        self.config = AutumnSourceConfig(api_key="am_sk_test")

    @pytest.mark.parametrize(
        ("should_use_incremental_field", "expected_last_value", "pinned_version", "expected_version"),
        [
            (True, 1704067200000, "2.3.0", "2.3.0"),
            # A stale watermark must not leak into a full-refresh run.
            (False, None, "2.3.0", "2.3.0"),
            (True, 1704067200000, "2.4.0", "2.4.0"),
            # An unpinned source follows the default version.
            (True, 1704067200000, None, "2.4.0"),
        ],
    )
    def test_source_for_pipeline_plumbing(
        self,
        should_use_incremental_field: bool,
        expected_last_value: Optional[int],
        pinned_version: Optional[str],
        expected_version: str,
    ) -> None:
        inputs = _make_inputs(
            schema_name="Events",
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=1704067200000,
            incremental_field="timestamp",
            api_version=pinned_version,
        )
        manager = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.autumn.source.autumn_source"
        ) as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="am_sk_test",
            endpoint="Events",
            team_id=123,
            job_id="job-id",
            api_version=expected_version,
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=expected_last_value,
            incremental_field="timestamp",
        )

    @pytest.mark.parametrize(
        ("pinned_version", "expected_version"),
        [
            ("2.3.0", "2.3.0"),
            ("2.4.0", "2.4.0"),
            (None, "2.4.0"),
        ],
    )
    def test_validate_credentials_uses_the_pinned_version(
        self, pinned_version: Optional[str], expected_version: str
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.autumn.source.validate_autumn_credentials",
            return_value=(True, None),
        ) as mock_validate:
            self.source.validate_credentials(self.config, team_id=123, api_version=pinned_version)

        mock_validate.assert_called_once_with("am_sk_test", expected_version)
