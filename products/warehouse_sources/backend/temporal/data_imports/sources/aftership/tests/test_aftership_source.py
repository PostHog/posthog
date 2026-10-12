from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.aftership.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
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

    def test_courier_connection_credentials_are_not_documented_as_a_column(self) -> None:
        # The sync drops the column; documenting it would advertise a table that never exists.
        assert "credentials" not in CANONICAL_DESCRIPTIONS["courier_connections"]["columns"]

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

    @parameterized.expand(
        [
            ("bad_key", "401 Client Error: Unauthorized for url: https://api.aftership.com/tracking/2026-07/trackings"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.aftership.com/tracking/2026-07/couriers"),
        ]
    )
    def test_non_retryable_errors_match_credential_failures(self, _name: str, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.aftership.com/tracking"),
            ("server_error", "503 Server Error: Service Unavailable for url: https://api.aftership.com/tracking"),
        ]
    )
    def test_non_retryable_errors_ignore_transient_failures(self, _name: str, unrelated_error: str) -> None:
        assert not any(key in unrelated_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand([("unpinned", None, "2026-07"), ("pinned", "2026-07", "2026-07")])
    @mock.patch(AFTERSHIP_SOURCE_PATH)
    def test_source_for_pipeline_plumbs_arguments(
        self, _name: str, pin: str | None, expected_version: str, mock_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "trackings"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "updated_at"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00+00:00"
        inputs.api_version = pin
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "as-key"
        assert kwargs["endpoint"] == "trackings"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        # The user's chosen cursor column decides which server-side filter is sent.
        assert kwargs["incremental_field_name"] == "updated_at"
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00+00:00"
        assert kwargs["api_version"] == expected_version

    @mock.patch(AFTERSHIP_SOURCE_PATH)
    def test_source_for_pipeline_drops_the_watermark_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "couriers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00+00:00"
        inputs.api_version = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
