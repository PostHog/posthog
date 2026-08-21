from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.aftership.source import AftershipSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aftership import (
    AftershipSourceConfig,
)

CHECK_ACCESS_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.aftership.source.check_access"
AFTERSHIP_SOURCE_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.aftership.source.aftership_source"
)


class TestAftershipSource:
    def setup_method(self) -> None:
        self.source = AftershipSource()
        self.team_id = 123
        self.config = AftershipSourceConfig(api_key="as-key")

    def test_version_pin_matches_the_path_the_code_calls(self) -> None:
        assert self.source.supported_versions == ("2026-07",)
        assert self.source.default_version == "2026-07"

    @parameterized.expand(
        [
            ("ok", True, 200, None, True, None),
            ("bad_key", False, 401, None, False, "Invalid AfterShip API key"),
            ("scoped_key_at_create", False, 403, None, True, None),
            (
                "scoped_key_for_table",
                False,
                403,
                "trackings",
                False,
                "Your AfterShip API key does not have permission to read 'trackings'",
            ),
            ("unreachable", False, None, None, False, "Could not validate your AfterShip API key"),
        ]
    )
    @mock.patch(CHECK_ACCESS_PATH)
    def test_validate_credentials(
        self,
        _name: str,
        probe_valid: bool,
        status: int | None,
        schema_name: str | None,
        expected_valid: bool,
        expected_message: str | None,
        mock_check: mock.MagicMock,
    ) -> None:
        mock_check.return_value = (probe_valid, status)
        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert is_valid is expected_valid
        assert message == expected_message

    @mock.patch(CHECK_ACCESS_PATH)
    def test_validate_credentials_rejects_unknown_table_without_probing(self, mock_check: mock.MagicMock) -> None:
        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name="not_a_table")
        assert is_valid is False
        assert message == "Unknown AfterShip table 'not_a_table'"
        mock_check.assert_not_called()

    @mock.patch(CHECK_ACCESS_PATH)
    def test_validate_credentials_probes_under_the_resolved_version(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = (True, 200)
        self.source.validate_credentials(self.config, self.team_id, schema_name="trackings", api_version=None)
        assert mock_check.call_args.args == ("as-key", "trackings", "2026-07")
