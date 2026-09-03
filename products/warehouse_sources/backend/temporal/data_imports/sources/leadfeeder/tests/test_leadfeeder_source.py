from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import VersionDeprecation
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.leadfeeder import (
    LeadfeederSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.settings import (
    ENDPOINTS,
    LEADFEEDER_API_2026_08_07,
    LEADFEEDER_API_LEGACY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.source import LeadfeederSource


class TestLeadfeederSource:
    def setup_method(self) -> None:
        self.source = LeadfeederSource()
        self.team_id = 123
        self.config = LeadfeederSourceConfig(api_token="token", start_date="2024-01-01")

    def test_version_metadata_defaults_to_unified_and_deprecates_legacy(self) -> None:
        # New sources land on the unified Dealfront API; the legacy Token API is advisory-deprecated
        # (no announced sunset), which is why existing pins are not migrated automatically.
        assert self.source.supported_versions == (LEADFEEDER_API_LEGACY, LEADFEEDER_API_2026_08_07)
        assert self.source.default_version == LEADFEEDER_API_2026_08_07
        assert self.source.deprecated_versions == (VersionDeprecation(version=LEADFEEDER_API_LEGACY, sunset_at=None),)

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O, so public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    @parameterized.expand(
        [
            "401 Client Error: Unauthorized for url: https://api.leadfeeder.com/accounts",
            "403 Client Error: Forbidden for url: https://api.leadfeeder.com/accounts/1/leads",
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            "429 Client Error: Too Many Requests for url: https://api.leadfeeder.com/accounts/1/visits",
            "500 Server Error for url: https://api.leadfeeder.com/accounts",
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_get_schemas_marks_only_date_filtered_endpoints_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)
        # Accounts has no server-side date filter -> full refresh only.
        assert schemas["accounts"].supports_incremental is False
        assert schemas["accounts"].supports_append is False
        # Leads and visits filter server-side on start_date/end_date -> incremental.
        for name in ("leads", "visits"):
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["leads"])
        assert [s.name for s in schemas] == ["leads"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @parameterized.expand(
        [
            (True, True, None),
            (
                False,
                False,
                "Unable to verify your Leadfeeder API token. Check that the token is correct and that Leadfeeder is reachable.",
            ),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.source.validate_leadfeeder_credentials"
    )
    def test_validate_credentials(
        self, mock_return: bool, expected_valid: bool, expected_message: str | None, mock_validate: mock.MagicMock
    ) -> None:
        mock_validate.return_value = mock_return
        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert error_message == expected_message
        # No pin at creation time resolves to the default (unified) version.
        mock_validate.assert_called_once_with("token", LEADFEEDER_API_2026_08_07)

    @parameterized.expand([(None, LEADFEEDER_API_2026_08_07), (LEADFEEDER_API_LEGACY, LEADFEEDER_API_LEGACY)])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.source.validate_leadfeeder_credentials"
    )
    def test_validate_credentials_probes_under_the_pinned_version(
        self, pin: str | None, expected_version: str, mock_validate: mock.MagicMock
    ) -> None:
        # A legacy-pinned source must probe the legacy API, not the resolved default — otherwise a
        # valid legacy token would fail validation against the unified endpoint.
        mock_validate.return_value = True
        self.source.validate_credentials(self.config, self.team_id, api_version=pin)
        mock_validate.assert_called_once_with("token", expected_version)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.source.leadfeeder_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "leads"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-06-01"
        inputs.api_version = LEADFEEDER_API_LEGACY
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "leads"
        assert kwargs["start_date_config"] == "2024-01-01"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2024-06-01"
        # The resolved source pin reaches the request layer so it builds the right generation's client.
        assert kwargs["api_version"] == LEADFEEDER_API_LEGACY

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.source.leadfeeder_source")
    def test_source_for_pipeline_drops_watermark_when_not_incremental(self, mock_source: mock.MagicMock) -> None:
        # A stale watermark must not leak into a full-refresh run.
        config = LeadfeederSourceConfig(api_token="token")
        inputs = mock.MagicMock()
        inputs.schema_name = "accounts"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-06-01"

        self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None
        assert kwargs["start_date_config"] == ""

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
