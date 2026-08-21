from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.source import ChartHopSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.charthop import (
    ChartHopSourceConfig,
)

CHECK_ACCESS_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.charthop.source.check_access"


class TestChartHopSource:
    def setup_method(self) -> None:
        self.source = ChartHopSource()
        self.team_id = 123
        self.config = ChartHopSourceConfig(api_key="charthop-token")

    def test_version_declaration_defaults_to_v2(self) -> None:
        # New sources are stamped with default_version; v1 stays supported for existing pins.
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.default_version == "v2"

    def test_get_schemas_only_changes_is_incremental(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

        by_name = {s.name: s for s in schemas}
        assert by_name["changes"].supports_incremental is True
        assert [f["field"] for f in by_name["changes"].incremental_fields] == ["date"]
        for name, schema in by_name.items():
            if name != "changes":
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []

    @parameterized.expand(
        [
            ("ok", 200, None, True, None),
            ("bad_token", 401, None, False, "Invalid ChartHop API token"),
            (
                "schema_forbidden",
                403,
                "persons",
                False,
                "Your ChartHop API token does not have permission to read 'persons'",
            ),
            ("org_forbidden", 403, None, False, "boom"),
            ("network_error", 0, None, False, "boom"),
        ]
    )
    @mock.patch(CHECK_ACCESS_PATH)
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        schema_name: str | None,
        expected_valid: bool,
        expected_message: str | None,
        mock_check: mock.MagicMock,
    ) -> None:
        mock_check.return_value = (status, "boom")
        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert is_valid is expected_valid
        assert message == expected_message

    @mock.patch(CHECK_ACCESS_PATH)
    def test_validate_credentials_org_not_found(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = (404, None)
        config = ChartHopSourceConfig(api_key="charthop-token", org_id="typo-org")
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message == "ChartHop organization 'typo-org' was not found"

    @mock.patch(CHECK_ACCESS_PATH)
    def test_validate_credentials_rejects_unknown_schema_without_probing(self, mock_check: mock.MagicMock) -> None:
        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name="not_a_table")
        assert is_valid is False
        assert message == "Unknown ChartHop schema 'not_a_table'"
        mock_check.assert_not_called()

    @parameterized.expand([("unpinned", None, "v2"), ("legacy", "v1", "v1")])
    @mock.patch(CHECK_ACCESS_PATH)
    def test_validate_credentials_probes_under_resolved_version(
        self, _name: str, pin: str | None, expected_version: str, mock_check: mock.MagicMock
    ) -> None:
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="changes", api_version=pin)
        assert mock_check.call_args.args == ("charthop-token", None, "changes", expected_version)
