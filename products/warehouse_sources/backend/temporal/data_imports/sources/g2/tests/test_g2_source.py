from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.g2.source import G2Source
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.g2 import G2SourceConfig

VALIDATE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.g2.source.validate_g2_credentials"


class TestG2Source:
    def setup_method(self) -> None:
        self.source = G2Source()
        self.team_id = 123
        self.config = G2SourceConfig(access_token="token-1", product_id="prod-1")

    @parameterized.expand(
        [
            ("valid", (True, 200), None, True, None),
            ("bad_token", (False, 401), None, False, "Invalid G2 access token"),
            ("unreachable", (False, None), None, False, "Invalid G2 access token"),
            # 403 at connect time is a real token without every scope granted — per-endpoint
            # scoping means the account may only want a subset of tables.
            ("forbidden_at_connect", (False, 403), None, True, None),
            ("forbidden_for_schema", (False, 403), "reviews", False, "Invalid G2 access token"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, probe_result: tuple[bool, int | None], schema_name, expected_valid, expected_message
    ) -> None:
        with mock.patch(VALIDATE_PATCH, return_value=probe_result) as mock_validate:
            is_valid, error_message = self.source.validate_credentials(
                self.config, self.team_id, schema_name=schema_name
            )

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("token-1", "v2")
