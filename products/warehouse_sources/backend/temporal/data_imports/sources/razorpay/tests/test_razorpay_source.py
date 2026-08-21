import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.razorpay import (
    RazorpaySourceConfig,
)
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
