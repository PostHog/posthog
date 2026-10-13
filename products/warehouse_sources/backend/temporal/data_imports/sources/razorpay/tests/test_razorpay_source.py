from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.razorpay import (
    RazorpaySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.source import RazorpaySource


def _source_inputs(
    schema_name: str = "Payments",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema_id",
        source_id="source_id",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="created_at" if should_use_incremental_field else None,
        incremental_field_type=None,
        job_id="job_id",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestRazorpaySource:
    def setup_method(self) -> None:
        self.source = RazorpaySource()
        self.config = RazorpaySourceConfig(key_id="rzp_test_key", key_secret="secret")

    @pytest.mark.parametrize(
        ("is_valid", "expected_ok"),
        [(True, True), (False, False)],
    )
    def test_validate_credentials(self, is_valid: bool, expected_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.source.validate_razorpay_credentials",
            return_value=is_valid,
        ) as mock_validate:
            ok, message = self.source.validate_credentials(self.config, team_id=1)

        mock_validate.assert_called_once_with("rzp_test_key", "secret")
        assert ok is expected_ok
        assert (message is None) is expected_ok

    @pytest.mark.parametrize(
        ("should_use_incremental_field", "last_value", "expected_last_value"),
        [
            (True, 1_750_000_000, 1_750_000_000),
            (False, 1_750_000_000, None),
        ],
    )
    def test_source_for_pipeline_plumbing(
        self,
        should_use_incremental_field: bool,
        last_value: Optional[int],
        expected_last_value: Optional[int],
    ) -> None:
        inputs = _source_inputs(
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )
        manager = MagicMock(spec=ResumableSourceManager)
        mock_resource = MagicMock()
        mock_resource.name = "Payments"
        mock_resource.column_hints = None

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.source.razorpay_source",
            return_value=mock_resource,
        ) as mock_source:
            response = self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            key_id="rzp_test_key",
            key_secret="secret",
            endpoint="Payments",
            team_id=1,
            job_id="job_id",
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=expected_last_value,
        )
        assert response.name == "Payments"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    def test_canonical_descriptions_cover_only_known_endpoints(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)
