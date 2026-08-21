from typing import cast

from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.bigmailer import AUTH_ERROR_MESSAGE
from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.source import BigMailerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bigmailer import (
    BigMailerSourceConfig,
)


def _config(api_key: str = "key") -> BigMailerSourceConfig:
    return cast(BigMailerSourceConfig, BigMailerSource()._config_class(api_key=api_key))


class TestCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials_plumbing(self, _name: str, probe_result: bool, expected_ok: bool) -> None:
        with patch.object(source_module, "validate_bigmailer_credentials", return_value=probe_result):
            ok, error = BigMailerSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_non_retryable_errors_cover_auth_failure(self) -> None:
        errors = BigMailerSource().get_non_retryable_errors()
        assert AUTH_ERROR_MESSAGE in errors
        assert errors[AUTH_ERROR_MESSAGE]  # has a user-facing message
