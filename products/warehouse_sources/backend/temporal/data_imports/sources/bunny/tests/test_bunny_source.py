import pytest
from unittest import mock

from products.warehouse_sources.backend.facade.source_config import ReleaseStatus, SourceFieldInputConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.source import BunnySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bunny import BunnySourceConfig


class TestBunnySource:
    def setup_method(self) -> None:
        self.source = BunnySource()
        self.team_id = 123
        self.config = BunnySourceConfig(access_key="bunny-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Bunny"
        assert config.label == "Bunny.net"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/bunny"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["access_key"]

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret `access_key` itself; the base URL is hardcoded and the account
        # is implicit in the key. There is no non-secret field that retargets where the key is sent,
        # so an editor cannot reuse a preserved key against a different account without re-entering it.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_marks_only_the_date_filtered_tables_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)
        # The list endpoints have no server-side timestamp filter, so they stay full refresh.
        assert {name for name, s in schemas.items() if s.supports_incremental} == set(INCREMENTAL_FIELDS)
        # Appending would re-add a row per run for every interval the request window still covers.
        assert all(s.supports_append is False for s in schemas.values())
        assert all(
            [f["field"] for f in schema.incremental_fields] == [f["field"] for f in INCREMENTAL_FIELDS.get(name, [])]
            for name, schema in schemas.items()
        )

    def test_documented_tables_render_for_public_docs(self) -> None:
        # Exercises the credential-free catalog path used by the posthog.com docs.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.bunny.net/pullzone?page=1&perPage=1000",
            "403 Client Error: Forbidden for url: https://api.bunny.net/dnszone?page=2&perPage=1000",
            "401 Client Error: Unauthorized for url: https://video.bunnycdn.com/library/7/videos?page=1",
            "403 Client Error: Forbidden for url: https://video.bunnycdn.com/library/7/statistics",
            "401 Client Error: Unauthorized for url: https://logging.bunnycdn.com/v2/pullzones/3/logs?offset=0",
            "403 Client Error: Forbidden for url: https://logging.bunnycdn.com/v2/pullzones/3/logs?offset=0",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "500 Server Error: Internal Server Error for url: https://api.bunny.net/pullzone",
            "HTTPSConnectionPool(host='api.bunny.net', port=443): Read timed out.",
            "429 Client Error: Too Many Requests for url: https://api.bunny.net/storagezone",
            # Logging is simply off for that pull zone, so the sync skips it rather than failing.
            "404 Client Error: Not Found for url: https://logging.bunnycdn.com/v2/pullzones/3/logs",
        ],
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid bunny.net account API key"),
            ((False, 403), False, "Invalid bunny.net account API key"),
            ((False, 500), False, "bunny.net returned HTTP 500"),
            ((False, None), False, "Could not connect to bunny.net"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bunny.source.check_access")
    def test_validate_credentials(
        self,
        mock_check: mock.MagicMock,
        probe_result: tuple[bool, int | None],
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_check.return_value = probe_result
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bunny.source.check_access")
    def test_validate_credentials_probes_the_account_key(self, mock_check: mock.MagicMock) -> None:
        # The account API key is account-wide, so validation probes the key, not a per-schema scope.
        mock_check.return_value = (True, 200)
        self.source.validate_credentials(self.config, self.team_id, schema_name="dns_zones")
        mock_check.assert_called_once_with("bunny-key")

    @pytest.mark.parametrize("should_use_incremental_field, expected_last_value", [(True, "2024-05-02"), (False, None)])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bunny.source.bunny_source")
    def test_source_for_pipeline_plumbs_arguments(
        self, mock_bunny_source: mock.MagicMock, should_use_incremental_field: bool, expected_last_value: str | None
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "pull_zones"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = "2024-05-02"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_bunny_source.assert_called_once()
        kwargs = mock_bunny_source.call_args.kwargs
        assert kwargs["access_key"] == "bunny-key"
        assert kwargs["endpoint"] == "pull_zones"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        # A full refresh must go out with no watermark, whatever the schema last recorded.
        assert kwargs["db_incremental_field_last_value"] == expected_last_value

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown bunny.net schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
