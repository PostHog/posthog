from typing import Optional

import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.freshservice import (
    FreshserviceResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.source import FreshserviceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FreshserviceSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

PATCH_VALIDATE = "products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.source.validate_freshservice_credentials"


def _make_inputs(schema_name: str = "tickets") -> SourceInputs:
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


class TestFreshserviceSource:
    def setup_method(self) -> None:
        self.source = FreshserviceSource()
        self.team_id = 1
        self.config = FreshserviceSourceConfig(domain="acme", api_key="key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.FRESHSERVICE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Freshservice"
        assert config.label == "Freshservice"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/freshservice.png"

        fields = config.fields
        assert len(fields) == 2
        domain_field, api_key_field = fields
        assert isinstance(domain_field, SourceFieldInputConfig)
        assert domain_field.name == "domain"
        assert domain_field.type == SourceFieldInputConfigType.TEXT
        assert domain_field.secret is False
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error: Forbidden for url"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "name, supports_incremental",
        [
            ("tickets", True),
            ("problems", False),
            ("changes", False),
            ("agents", False),
            ("assets", False),
            ("software", False),
        ],
    )
    def test_schema_incremental_support(self, name: str, supports_incremental: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        schema = schemas[name]
        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_incremental
        if supports_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["updated_at"]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["tickets"])
        assert len(schemas) == 1
        assert schemas[0].name == "tickets"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "domain, status, schema_name, expected_valid",
        [
            ("acme", 200, None, True),
            ("acme", 403, None, True),  # missing scope at source-create is accepted
            ("acme", 403, "tickets", False),  # missing scope for a specific schema fails
            ("acme", 401, None, False),
            ("acme", None, None, False),  # connection error
            ("invalid domain!", 200, None, False),  # domain regex rejects before probing
        ],
    )
    def test_validate_credentials(
        self, domain: str, status: Optional[int], schema_name: Optional[str], expected_valid: bool
    ) -> None:
        config = FreshserviceSourceConfig(domain=domain, api_key="key")
        with mock.patch(PATCH_VALIDATE, return_value=status) as mock_validate:
            is_valid, _ = self.source.validate_credentials(config, self.team_id, schema_name)

        assert is_valid is expected_valid
        if "!" in domain or " " in domain:
            mock_validate.assert_not_called()

    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FreshserviceResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = _make_inputs("tickets")
        manager = self.source.get_resumable_source_manager(inputs)

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response.name == "tickets"
        assert response.primary_keys == ["id"]
        # tickets partitions on its stable created_at field.
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    def test_source_for_pipeline_full_refresh_endpoint_has_no_partition(self) -> None:
        inputs = _make_inputs("agents")
        manager = self.source.get_resumable_source_manager(inputs)

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response.name == "agents"
        assert response.partition_mode is None
        assert response.partition_keys is None
