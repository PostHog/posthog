from typing import Optional

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.razorpay import (
    RazorpaySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.razorpay import (
    INCREMENTAL_LOOKBACK_SECONDS,
    MISSING_ACCOUNT_NUMBER_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.source import RazorpaySource


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
        ("should_use_incremental_field", "last_value", "expected_from"),
        [
            (True, 1_750_000_000, str(1_750_000_000 - INCREMENTAL_LOOKBACK_SECONDS)),
            (False, 1_750_000_000, None),
        ],
    )
    def test_source_for_pipeline_plumbing(
        self,
        should_use_incremental_field: bool,
        last_value: Optional[int],
        expected_from: Optional[str],
    ) -> None:
        result = SourceDriver(self.source, self.config).run(
            "Payments",
            [ScriptedResponse(json={"entity": "collection", "count": 0, "items": []})],
            should_use_incremental_field=should_use_incremental_field,
            incremental_field="created_at" if should_use_incremental_field else None,
            db_incremental_field_last_value=last_value,
        )

        assert result.params("from") == [expected_from]
        response = result.response
        assert response is not None
        assert response.name == "Payments"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    @pytest.mark.parametrize(
        ("account_number", "expected"),
        [(None, MISSING_ACCOUNT_NUMBER_ERROR), ("7878780080316316", None)],
    )
    def test_razorpayx_transactions_permission_needs_an_account_number(
        self, account_number: Optional[str], expected: Optional[str]
    ) -> None:
        config = RazorpaySourceConfig(
            key_id="rzp_test_key", key_secret="secret", razorpayx_account_number=account_number
        )

        permissions = self.source.get_endpoint_permissions(config, 1, ["Payments", "RazorpayXTransactions"])

        assert permissions == {"Payments": None, "RazorpayXTransactions": expected}

    def test_canonical_descriptions_cover_only_known_endpoints(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)
