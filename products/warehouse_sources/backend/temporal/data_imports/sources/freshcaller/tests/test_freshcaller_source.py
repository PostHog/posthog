from typing import Optional

import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.freshcaller import (
    FreshcallerResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.source import FreshcallerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FreshcallerSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

PATCH_VALIDATE = "products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.source.validate_freshcaller_credentials"


def _make_inputs(schema_name: str = "calls") -> SourceInputs:
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
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestFreshcallerSource:
    def setup_method(self) -> None:
        self.source = FreshcallerSource()
        self.team_id = 1
        self.config = FreshcallerSourceConfig(subdomain="acme", api_key="key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.FRESHCALLER

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Freshcaller"
        assert config.label == "Freshcaller"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # First cut ships hidden until validated end-to-end against a live account.
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/freshcaller"

        fields = config.fields
        assert len(fields) == 2
        subdomain_field, api_key_field = fields
        assert isinstance(subdomain_field, SourceFieldInputConfig)
        assert subdomain_field.name == "subdomain"
        assert subdomain_field.type == SourceFieldInputConfigType.TEXT
        assert subdomain_field.secret is False
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog -> the public docs Supported-tables section can render.
        assert self.source.lists_tables_without_credentials is True

    def test_connection_host_fields(self) -> None:
        # The subdomain is where the stored key is sent; editing it must re-require the secret.
        assert self.source.connection_host_fields == ["subdomain"]

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error: Forbidden for url"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "name, supports_incremental",
        [
            ("calls", True),
            ("call_metrics", True),
            ("users", False),
            ("teams", False),
        ],
    )
    def test_schema_incremental_support(self, name: str, supports_incremental: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        schema = schemas[name]
        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_incremental
        if supports_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["created_time"]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["calls"])
        assert len(schemas) == 1
        assert schemas[0].name == "calls"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "subdomain, status, schema_name, expected_valid",
        [
            ("acme", 200, None, True),
            ("acme", 403, None, True),  # missing scope at source-create is accepted
            ("acme", 403, "calls", False),  # missing scope for a specific schema fails
            ("acme", 401, None, False),
            ("acme", None, None, False),  # connection error
            ("invalid domain!", 200, None, False),  # account-name regex rejects before probing
        ],
    )
    def test_validate_credentials(
        self, subdomain: str, status: Optional[int], schema_name: Optional[str], expected_valid: bool
    ) -> None:
        config = FreshcallerSourceConfig(subdomain=subdomain, api_key="key")
        with mock.patch(PATCH_VALIDATE, return_value=status) as mock_validate:
            is_valid, _ = self.source.validate_credentials(config, self.team_id, schema_name)

        assert is_valid is expected_valid
        if "!" in subdomain or " " in subdomain:
            mock_validate.assert_not_called()

    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FreshcallerResumeConfig

    def test_source_for_pipeline_incremental_endpoint_partitions_and_sorts_desc(self) -> None:
        inputs = _make_inputs("calls")
        manager = self.source.get_resumable_source_manager(inputs)

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response.name == "calls"
        assert response.primary_keys == ["id"]
        # Calls partition on the stable created_time field.
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_time"]
        # Full-window-per-sync + unknown API order -> defer the watermark commit via desc.
        assert response.sort_mode == "desc"

    def test_source_for_pipeline_full_refresh_endpoint_has_no_partition(self) -> None:
        inputs = _make_inputs("users")
        manager = self.source.get_resumable_source_manager(inputs)

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response.name == "users"
        assert response.partition_mode is None
        assert response.partition_keys is None
        assert response.sort_mode == "asc"
