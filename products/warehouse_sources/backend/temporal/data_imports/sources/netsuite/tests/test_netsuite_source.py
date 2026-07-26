from datetime import UTC, datetime
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.netsuite import (
    NetSuiteSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.netsuite import NetSuiteResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.settings import (
    ENDPOINTS,
    INCREMENTAL_LOOKBACK_SECONDS,
    NETSUITE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.source import NetSuiteSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_INCREMENTAL_ENDPOINTS = [name for name, cfg in NETSUITE_ENDPOINTS.items() if cfg.incremental_fields]
_FULL_REFRESH_ENDPOINTS = [name for name, cfg in NETSUITE_ENDPOINTS.items() if not cfg.incremental_fields]


def _config() -> NetSuiteSourceConfig:
    return NetSuiteSourceConfig(
        account_id="1234567_SB1",
        consumer_key="ck",
        consumer_secret="cs",
        token_id="ti",
        token_secret="ts",
    )


class TestNetSuiteSourceClass:
    def test_source_type(self) -> None:
        assert NetSuiteSource().source_type == ExternalDataSourceType.NETSUITE

    def test_source_config(self) -> None:
        config = NetSuiteSource().get_source_config
        assert config.label == "NetSuite"
        assert config.category == DataWarehouseSourceCategory.FINANCE___ACCOUNTING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/netsuite"
        assert config.unreleasedSource is None
        assert [f.name for f in config.fields] == [
            "account_id",
            "consumer_key",
            "consumer_secret",
            "token_id",
            "token_secret",
        ]

    def test_every_token_field_is_stored_as_a_secret(self) -> None:
        fields = {f.name: f for f in NetSuiteSource().get_source_config.fields}
        for name in ("consumer_key", "consumer_secret", "token_id", "token_secret"):
            field = fields[name]
            assert isinstance(field, SourceFieldInputConfig)
            assert field.secret is True

    def test_account_id_is_a_connection_host_field(self) -> None:
        # The account ID resolves the host the tokens are sent to, so changing it must re-require them.
        assert NetSuiteSource().connection_host_fields == ["account_id"]

    def test_lists_tables_without_credentials(self) -> None:
        assert NetSuiteSource.lists_tables_without_credentials is True

    def test_documented_tables_render_without_credentials(self) -> None:
        tables = NetSuiteSource().get_documented_tables()
        assert {table["name"] for table in tables} == set(ENDPOINTS)

    def test_non_retryable_errors_match_the_transport_error_text(self) -> None:
        errors = NetSuiteSource().get_non_retryable_errors()
        assert set(errors) == {
            "NetSuite SuiteQL request returned 401",
            "NetSuite SuiteQL request returned 403",
            "NetSuite SuiteQL request returned 404",
        }
        assert all(message for message in errors.values())

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = NetSuiteSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_name_filter(self) -> None:
        schemas = NetSuiteSource().get_schemas(_config(), team_id=1, names=["customers"])
        assert [s.name for s in schemas] == ["customers"]

    @parameterized.expand([(name,) for name in _INCREMENTAL_ENDPOINTS])
    def test_incremental_endpoints(self, endpoint: str) -> None:
        schema = NetSuiteSource().get_schemas(_config(), team_id=1, names=[endpoint])[0]
        assert schema.supports_incremental is True
        assert [f["field"] for f in schema.incremental_fields] == [
            f["field"] for f in NETSUITE_ENDPOINTS[endpoint].incremental_fields
        ]
        # `lastmodifieddate` is written in the account's own time zone, so every incremental table
        # re-reads a trailing window rather than trusting the cursor exactly.
        assert schema.default_incremental_lookback_seconds == INCREMENTAL_LOOKBACK_SECONDS

    @parameterized.expand([(name,) for name in _FULL_REFRESH_ENDPOINTS])
    def test_full_refresh_endpoints(self, endpoint: str) -> None:
        schema = NetSuiteSource().get_schemas(_config(), team_id=1, names=[endpoint])[0]
        assert schema.supports_incremental is False
        assert schema.incremental_fields == []
        assert schema.default_incremental_lookback_seconds is None

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_schema_primary_keys_match_the_endpoint_catalog(self, endpoint: str) -> None:
        schema = NetSuiteSource().get_schemas(_config(), team_id=1, names=[endpoint])[0]
        assert schema.detected_primary_keys == NETSUITE_ENDPOINTS[endpoint].primary_keys

    def test_transaction_lines_are_keyed_table_wide(self) -> None:
        # A transaction line's `id` repeats across transactions; keying on it would seed duplicates
        # that every later merge multi-matches.
        config = NETSUITE_ENDPOINTS["transaction_lines"]
        assert config.primary_keys == ["uniquekey"]
        assert config.keyset_column == "uniquekey"

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_partition_keys_are_creation_time_columns(self, endpoint: str) -> None:
        # A partition key that moves on edit rewrites partitions on every sync.
        partition_key = NETSUITE_ENDPOINTS[endpoint].partition_key
        assert partition_key is None or "modified" not in partition_key

    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid", (False, "NetSuite rejected the token-based authentication signature.")),
        ]
    )
    @patch.object(source_module, "validate_netsuite_credentials")
    def test_validate_credentials_passes_through(
        self, _name: str, expected: tuple[bool, str | None], mock_validate: MagicMock
    ) -> None:
        mock_validate.return_value = expected

        assert NetSuiteSource().validate_credentials(_config(), team_id=1) == expected

        assert mock_validate.call_args.kwargs["account_id"] == "1234567_SB1"
        assert mock_validate.call_args.kwargs["token_secret"] == "ts"

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        manager = NetSuiteSource().get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is NetSuiteResumeConfig

    @patch.object(source_module, "netsuite_source")
    def test_source_for_pipeline_plumbs_inputs(self, mock_source: MagicMock) -> None:
        inputs = MagicMock()
        inputs.schema_name = "transactions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = datetime(2026, 1, 1, tzinfo=UTC)
        inputs.incremental_field = "lastmodifieddate"
        manager = MagicMock()

        NetSuiteSource().source_for_pipeline(_config(), manager, inputs)

        kwargs: dict[str, Any] = dict(mock_source.call_args.kwargs)
        assert kwargs["account_id"] == "1234567_SB1"
        assert kwargs["consumer_key"] == "ck"
        assert kwargs["endpoint"] == "transactions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == datetime(2026, 1, 1, tzinfo=UTC)
        assert kwargs["incremental_field"] == "lastmodifieddate"

    @patch.object(source_module, "netsuite_source")
    def test_source_for_pipeline_drops_cursor_on_full_refresh(self, mock_source: MagicMock) -> None:
        inputs = MagicMock()
        inputs.schema_name = "accounts"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = datetime(2026, 1, 1, tzinfo=UTC)
        inputs.incremental_field = None

        NetSuiteSource().source_for_pipeline(_config(), MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_keys_match_endpoints(self) -> None:
        descriptions = NetSuiteSource().get_canonical_descriptions()
        assert descriptions is CANONICAL_DESCRIPTIONS
        assert set(descriptions).issubset(set(ENDPOINTS))
