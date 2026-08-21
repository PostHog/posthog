from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.okendo import OkendoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.okendo.source import OkendoSource

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.okendo.source.validate_okendo_credentials"
)


class TestOkendoSource:
    def setup_method(self):
        self.source = OkendoSource()
        self.team_id = 123
        self.config = OkendoSourceConfig(user_id="user-1", api_key="key-1")

    @parameterized.expand(
        [
            ("valid", (True, 200), None, True, None),
            ("bad_key", (False, 401), None, False, "Invalid Okendo user ID or API key"),
            ("unreachable", (False, None), None, False, "Invalid Okendo user ID or API key"),
            # 403 at connect time is a real key without review access — the user may only want the
            # loyalty tables, so blocking source creation on it would lock them out.
            ("forbidden_at_connect", (False, 403), None, True, None),
            ("forbidden_for_schema", (False, 403), "reviews", False, "Your Okendo API key does not have access"),
        ]
    )
    def test_validate_credentials(self, _name, probe_result, schema_name, expected_valid, expected_message):
        with mock.patch(VALIDATE_PATCH, return_value=probe_result) as mock_validate:
            is_valid, error_message = self.source.validate_credentials(
                self.config, self.team_id, schema_name=schema_name
            )

        assert is_valid is expected_valid
        if expected_message is None:
            assert error_message is None
        else:
            assert error_message is not None and expected_message in error_message
        mock_validate.assert_called_once_with("user-1", "key-1", "2025-02-01")
