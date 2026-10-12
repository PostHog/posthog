from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.honeycomb import (
    HoneycombSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb.settings import (
    HONEYCOMB_ENDPOINTS,
    HoneycombScope,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb.source import HoneycombSource


def _source_inputs(schema_name: str = "datasets") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestHoneycombSource:
    def setup_method(self) -> None:
        self.source = HoneycombSource()
        self.team_id = 1

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id, names=["datasets", "slos"])
        assert {s.name for s in schemas} == {"datasets", "slos"}

    @parameterized.expand(
        [
            ("datasets", ["slug"]),
            ("columns", ["id", "dataset_slug"]),
            ("slos", ["id", "dataset_slug"]),
            ("burn_alerts", ["id", "dataset_slug"]),
            ("boards", ["id"]),
            ("recipients", ["id"]),
        ]
    )
    def test_source_for_pipeline_plumbs_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs(endpoint))
        response = self.source.source_for_pipeline(
            HoneycombSourceConfig(api_key="k", region="us"), manager, _source_inputs(endpoint)
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    def test_fan_out_children_carry_dataset_slug_in_primary_key(self) -> None:
        # Fan-out children aggregate rows from every dataset (and multi-dataset SLOs are listed
        # under each dataset they span), so the injected dataset slug must be part of the primary
        # key — otherwise per-dataset-unique ids collide table-wide and every merge multi-matches.
        for config in HONEYCOMB_ENDPOINTS.values():
            if config.scope in (HoneycombScope.PER_DATASET, HoneycombScope.PER_SLO):
                assert "dataset_slug" in config.primary_keys, config.name

    @parameterized.expand(
        [
            (
                "unauthorized_us",
                "401 Client Error: Unauthorized for url: https://api.honeycomb.io/1/columns/prod?x=1",
            ),
            (
                "unauthorized_eu",
                "401 Client Error: Unauthorized for url: https://api.eu1.honeycomb.io/1/datasets",
            ),
            (
                "forbidden_us",
                "403 Client Error: Forbidden for url: https://api.honeycomb.io/1/slos/prod",
            ),
            (
                "forbidden_eu",
                "403 Client Error: Forbidden for url: https://api.eu1.honeycomb.io/1/boards",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.honeycomb.io/1/datasets"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.honeycomb.io/1/boards"),
            ("read_timeout", "HTTPSConnectionPool(host='api.honeycomb.io', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)
