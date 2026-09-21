from typing import Optional

import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.source import FreshserviceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.freshservice import (
    FreshserviceSourceConfig,
)

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
