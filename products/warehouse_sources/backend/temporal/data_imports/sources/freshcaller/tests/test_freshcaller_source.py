from typing import Optional

import pytest

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.source import FreshcallerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.freshcaller import (
    FreshcallerSourceConfig,
)


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

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog -> the public docs Supported-tables section can render.
        assert self.source.lists_tables_without_credentials is True

    def test_connection_host_fields(self) -> None:
        # The subdomain is where the stored key is sent; editing it must re-require the secret.
        assert self.source.connection_host_fields == ["subdomain"]

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
        script = always(ConnectionError("nope")) if status is None else [ScriptedResponse(status=status)]

        with scripted_network(script) as network:
            is_valid, _ = self.source.validate_credentials(config, self.team_id, schema_name)

        assert is_valid is expected_valid
        if "!" in subdomain or " " in subdomain:
            assert network.requests_log == []

    def test_source_for_pipeline_full_refresh_endpoint_has_no_partition(self) -> None:
        inputs = _make_inputs("users")
        manager = self.source.get_resumable_source_manager(inputs)

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response.name == "users"
        assert response.partition_mode is None
        assert response.partition_keys is None
        assert response.sort_mode == "asc"
