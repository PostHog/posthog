import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.braintree.braintree import (
    BRAINTREE_VERSION_2019_01_01,
    BRAINTREE_VERSION_2026_07_14,
    BRAINTREE_VERSION_2026_08_04,
    BRAINTREE_VERSION_2026_08_13,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braintree.source import BraintreeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.braintree import (
    BraintreeSourceConfig,
)


class TestBraintreeSource:
    def setup_method(self):
        self.source = BraintreeSource()
        self.team_id = 123
        self.config = BraintreeSourceConfig(environment="production", public_key="pub", private_key="priv")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Braintree API keys"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.braintree.source.validate_braintree_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("production", "pub", "priv", "2026-08-13")

    def test_supported_versions_and_default(self):
        assert self.source.supported_versions == ("2019-01-01", "2026-07-14", "2026-08-04", "2026-08-13")
        # New sources start on the latest version; the default must stay in supported.
        assert self.source.default_version == "2026-08-13"
        assert self.source.default_version in self.source.supported_versions

    @pytest.mark.parametrize(
        "pinned, expected",
        [
            ("2019-01-01", "2019-01-01"),
            ("2026-07-14", "2026-07-14"),
            ("2026-08-04", "2026-08-04"),
            ("2026-08-13", "2026-08-13"),
            (None, "2026-08-13"),
            ("", "2026-08-13"),
        ],
    )
    def test_resolve_api_version(self, pinned, expected):
        assert self.source.resolve_api_version(pinned) == expected


class TestValidateCredentialsResolvedPin:
    @pytest.mark.parametrize(
        "pin, expected",
        [
            # The no-pin (None -> default) case is already covered by test_validate_credentials.
            (BRAINTREE_VERSION_2019_01_01, BRAINTREE_VERSION_2019_01_01),
            (BRAINTREE_VERSION_2026_07_14, BRAINTREE_VERSION_2026_07_14),
            (BRAINTREE_VERSION_2026_08_04, BRAINTREE_VERSION_2026_08_04),
            (BRAINTREE_VERSION_2026_08_13, BRAINTREE_VERSION_2026_08_13),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.braintree.source.validate_braintree_credentials"
    )
    def test_probe_receives_resolved_pin(self, mock_validate, pin, expected):
        # A pinned source must revalidate under its own version, not always the default.
        mock_validate.return_value = True
        config = BraintreeSourceConfig(environment="production", public_key="pub", private_key="priv")

        BraintreeSource().validate_credentials(config, 1, api_version=pin)

        assert mock_validate.call_args.args[-1] == expected
