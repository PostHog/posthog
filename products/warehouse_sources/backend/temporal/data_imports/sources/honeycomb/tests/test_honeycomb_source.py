from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HoneycombSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb.honeycomb import HoneycombResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb.settings import (
    ENDPOINTS,
    HONEYCOMB_ENDPOINTS,
    HoneycombScope,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb.source import HoneycombSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


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

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.HONEYCOMB

    def test_source_config_basics(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Honeycomb"
        assert config.unreleasedSource is None
        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key", "region"]
        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.required is True
        assert api_key_field.secret is True
        region_field = config.fields[1]
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert {option.value for option in region_field.options} == {"us", "eu"}

    def test_generated_config_parses_fields(self) -> None:
        # Guards the generated_configs.py wiring: the form fields must map to `api_key` and
        # `region`, with the region defaulting to US for configs saved before the field existed.
        config = HoneycombSourceConfig.from_dict({"api_key": "hcaik_123"})
        assert config.api_key == "hcaik_123"
        assert config.region == "us"
        assert HoneycombSourceConfig.from_dict({"api_key": "k", "region": "eu"}).region == "eu"

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_schemas_are_full_refresh(self) -> None:
        # Honeycomb's v1 config endpoints have no server-side timestamp filter, so advertising
        # incremental would silently re-walk history every run while claiming a delta sync.
        for schema in self.source.get_schemas(MagicMock(), team_id=self.team_id):
            assert schema.supports_incremental is False, schema.name
            assert schema.supports_append is False, schema.name

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id, names=["datasets", "slos"])
        assert {s.name for s in schemas} == {"datasets", "slos"}

    def test_publishes_table_catalog_for_public_docs(self) -> None:
        # `lists_tables_without_credentials` gates whether the static endpoint catalog reaches
        # the posthog.com "Supported tables" section. Dropping the flag (or making get_schemas
        # require credentials) would silently empty that section.
        tables = self.source.get_documented_tables()
        names = {t["name"] for t in tables}
        assert set(ENDPOINTS).issubset(names)
        datasets = next(t for t in tables if t["name"] == "datasets")
        assert "Full refresh" in datasets["sync_methods"]
        assert datasets["description"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb.source.validate_honeycomb_credentials"
    )
    def test_validate_credentials_passes_region(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = (True, None)
        ok, error = self.source.validate_credentials(HoneycombSourceConfig(api_key="k", region="eu"), self.team_id)
        assert ok is True
        assert error is None
        mock_validate.assert_called_once_with("k", "eu")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb.source.validate_honeycomb_credentials"
    )
    def test_validate_credentials_failure(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = (False, "Invalid Honeycomb API key")
        ok, error = self.source.validate_credentials(HoneycombSourceConfig(api_key="bad"), self.team_id)
        assert ok is False
        assert error == "Invalid Honeycomb API key"

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is HoneycombResumeConfig

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

    def test_canonical_description_keys_are_real_endpoints(self) -> None:
        # Canonical descriptions are keyed by schema name; a typo'd key would silently never apply.
        descriptions: dict[str, Any] = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)
        for endpoint, entry in descriptions.items():
            assert entry["description"], endpoint
