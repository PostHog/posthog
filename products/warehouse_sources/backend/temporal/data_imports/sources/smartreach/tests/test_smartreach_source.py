import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartreach import (
    SmartreachSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.smartreach import (
    SMARTREACH_API_V1,
    SMARTREACH_API_V3,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.source import SmartreachSource


class TestSmartreachSource:
    def setup_method(self) -> None:
        self.source = SmartreachSource()
        self.team_id = 123
        self.config = SmartreachSourceConfig(api_key="uk_test", team_id="team_abc")

    def test_supported_versions_and_default(self) -> None:
        # v3 is the new default for freshly created sources; v1 stays supported so pinned rows keep working.
        assert self.source.supported_versions == (SMARTREACH_API_V1, SMARTREACH_API_V3)
        assert self.source.default_version == SMARTREACH_API_V3

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid SmartReach API key"),
            (403, False, "Invalid SmartReach API key"),
            (500, False, "SmartReach returned HTTP 500"),
            (0, False, "Could not connect to SmartReach: boom"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.source.check_access")
    def test_validate_credentials(
        self,
        mock_check: mock.MagicMock,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        message = (
            "SmartReach returned HTTP 500"
            if status == 500
            else ("Could not connect to SmartReach: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.source.check_access")
    def test_validate_credentials_probes_the_user_key(self, mock_check: mock.MagicMock) -> None:
        # The user key is account-wide, so validation probes the key, not a per-schema scope. The
        # resolved version (v3 by default) and the SmartReach team id ride along to the probe.
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="campaigns")
        mock_check.assert_called_once_with("uk_test", SMARTREACH_API_V3, "team_abc")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.source.check_access")
    def test_validate_credentials_v3_requires_team_id(self, mock_check: mock.MagicMock) -> None:
        # v3 list endpoints reject requests without team_id, so fail fast (before probing) when it's
        # missing on a v3-resolved source rather than letting every table 400 mid-sync.
        config = SmartreachSourceConfig(api_key="uk_test")
        is_valid, message = self.source.validate_credentials(config, self.team_id, api_version=SMARTREACH_API_V3)
        assert is_valid is False
        assert message == "Enter your SmartReach team ID. The current SmartReach API needs it to return your data."
        mock_check.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.source.check_access")
    def test_validate_credentials_v1_does_not_require_team_id(self, mock_check: mock.MagicMock) -> None:
        # A source pinned to v1 (no team_id in its stored config) still validates — v1 never sends one.
        mock_check.return_value = (200, None)
        config = SmartreachSourceConfig(api_key="uk_test")
        is_valid, _ = self.source.validate_credentials(config, self.team_id, api_version=SMARTREACH_API_V1)
        assert is_valid is True
        mock_check.assert_called_once_with("uk_test", SMARTREACH_API_V1, None)

    @pytest.mark.parametrize(
        "pinned_version, expected_version",
        [
            (None, SMARTREACH_API_V3),  # unpinned resolves to the new default
            (SMARTREACH_API_V1, SMARTREACH_API_V1),  # a legacy pin keeps syncing under v1
            (SMARTREACH_API_V3, SMARTREACH_API_V3),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.source.smartreach_source")
    def test_source_for_pipeline_plumbs_arguments(
        self, mock_smartreach_source: mock.MagicMock, pinned_version: str | None, expected_version: str
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "prospects"
        inputs.api_version = pinned_version
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_smartreach_source.assert_called_once()
        kwargs = mock_smartreach_source.call_args.kwargs
        assert kwargs["api_key"] == "uk_test"
        assert kwargs["endpoint"] == "prospects"
        assert kwargs["resumable_source_manager"] is manager
        # The resolved pin and the SmartReach team id reach the request layer.
        assert kwargs["api_version"] == expected_version
        assert kwargs["smartreach_team_id"] == "team_abc"

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown SmartReach schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
