from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.cloudzero import KEY_REJECTED_MESSAGE
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.source import (
    CloudzeroSource,
    _parse_group_by,
)


def _config(
    api_key: str = "key", granularity: str = "daily", cost_type: str = "real_cost", group_by: str | None = None
) -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.granularity = granularity
    config.cost_type = cost_type
    config.group_by = group_by
    return config


class TestParseGroupBy:
    @parameterized.expand(
        [
            ("none", None, []),
            ("empty_string", "", []),
            ("single", "service", ["service"]),
            ("multiple", "service,account", ["service", "account"]),
            ("whitespace_and_blank_entries", " service , , account ", ["service", "account"]),
        ]
    )
    def test_parse_group_by(self, _name: str, raw: str | None, expected: list[str]) -> None:
        assert _parse_group_by(raw) == expected


class TestSourceConfig:
    def test_api_version_metadata(self) -> None:
        assert CloudzeroSource.supported_versions == ("v2",)
        assert CloudzeroSource.default_version == "v2"
        assert CloudzeroSource.api_docs_url.startswith("https://")


class TestGetSchemas:
    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O) — public docs render the table list.
        assert CloudzeroSource.lists_tables_without_credentials is True
        tables = {t["name"]: t for t in CloudzeroSource().get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert "Incremental" in tables["Costs"]["sync_methods"]
        # Costs is the only endpoint CloudZero lets us filter by time, so every other table
        # can only be synced by full refresh.
        assert [name for name, table in tables.items() if table["sync_methods"] != ["Full refresh"]] == ["Costs"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid", (False, KEY_REJECTED_MESSAGE)),
        ]
    )
    def test_plumbs_transport_result(self, _name: str, transport_result: tuple[bool, str | None]) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.source.validate_cloudzero_credentials",
            return_value=transport_result,
        ) as mocked:
            assert CloudzeroSource().validate_credentials(_config(), team_id=1) == transport_result
        mocked.assert_called_once_with("key")


class TestResumableWiring:
    @parameterized.expand(
        [
            ("incremental", True, "2026-01-01T00:00:00+00:00"),
            # A stale watermark must not leak into a full-refresh run.
            ("full_refresh", False, None),
        ]
    )
    def test_source_for_pipeline_plumbs_arguments(
        self, _name: str, should_use_incremental_field: bool, expected_last_value: Any
    ) -> None:
        inputs = MagicMock()
        inputs.schema_name = "Costs"
        inputs.team_id = 1
        inputs.job_id = "test_job"
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00+00:00"
        manager = MagicMock()
        config = _config(group_by="service, account")

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.source.cloudzero_source"
        ) as mocked:
            mocked.return_value.name = "Costs"
            mocked.return_value.column_hints = None
            response = CloudzeroSource().source_for_pipeline(config, manager, inputs)

        mocked.assert_called_once_with(
            api_key="key",
            endpoint="Costs",
            team_id=1,
            job_id="test_job",
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=expected_last_value,
            granularity="daily",
            cost_type="real_cost",
            group_by=["service", "account"],
        )
        # Composite key must include every group_by dimension, since rows with the same
        # usage_date differ only by their dimension values.
        assert response.primary_keys == ["usage_date", "service", "account"]
        assert response.partition_keys == ["usage_date"]
        assert response.partition_mode == "datetime"

    @parameterized.expand(
        [
            ("Budgets", ["id"]),
            ("Dimensions", ["id"]),
            ("Insights", ["id"]),
            ("RecommendationTypes", ["id"]),
            # CloudZero names the recommendation key `recommendation_id`, not `id`. A wrong key
            # here seeds duplicate rows that every later merge multi-matches.
            ("Recommendations", ["recommendation_id"]),
        ]
    )
    def test_non_cost_endpoints_use_their_own_key_and_no_partitioning(
        self, schema_name: str, expected_primary_keys: list[str]
    ) -> None:
        inputs = MagicMock()
        inputs.schema_name = schema_name
        inputs.team_id = 1
        inputs.job_id = "test_job"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None
        manager = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.source.cloudzero_source"
        ) as mocked:
            mocked.return_value.name = schema_name
            mocked.return_value.column_hints = None
            response = CloudzeroSource().source_for_pipeline(_config(), manager, inputs)

        assert response.primary_keys == expected_primary_keys
        assert response.partition_keys is None
        assert response.partition_mode is None


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.cloudzero.com/v2/billing/costs?start_date=2025-01-01",
            ),
            ("unauthorized", "Unauthorized for url: https://api.cloudzero.com/v2/billing/dimensions"),
            (
                "expired_cache",
                "410 Client Error: Gone for url: https://api.cloudzero.com/v2/billing/costs?cursor=abc",
            ),
        ]
    )
    def test_permanent_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = CloudzeroSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.cloudzero.com/v2/billing/costs"),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.cloudzero.com/v2/billing/costs",
            ),
            ("bad_request", "400 Client Error: Bad Request for url: https://api.cloudzero.com/v2/billing/costs"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = CloudzeroSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestCanonicalDescriptions:
    def test_canonical_descriptions_keys_are_known_endpoints(self) -> None:
        # Every documented table must map to a real endpoint, or its descriptions never apply.
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
