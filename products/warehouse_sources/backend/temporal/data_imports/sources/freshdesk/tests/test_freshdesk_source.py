from typing import Optional

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.source import FreshdeskSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.freshdesk import (
    FreshdeskSourceConfig,
)


class TestFreshdeskSource:
    def setup_method(self) -> None:
        self.source = FreshdeskSource()
        self.team_id = 1
        self.config = FreshdeskSourceConfig(subdomain="acme", api_key="key")

    @pytest.mark.parametrize(
        "subdomain, status, schema_name, expected_valid",
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
        self, subdomain: str, status: Optional[int], schema_name: Optional[str], expected_valid: bool
    ) -> None:
        config = FreshdeskSourceConfig(subdomain=subdomain, api_key="key")
        script = (
            []
            if "!" in subdomain or " " in subdomain
            else ([requests.ConnectionError("nope")] if status is None else [ScriptedResponse(status=status)])
        )
        with scripted_network(script) as network:
            is_valid, _ = self.source.validate_credentials(config, self.team_id, schema_name)

        assert is_valid is expected_valid
        if "!" in subdomain or " " in subdomain:
            assert network.requests_log == []
        else:
            assert {request.path for request in network.requests_log} == {"/api/v2/tickets"}
            assert {request.param("per_page") for request in network.requests_log} == {"1"}

    def test_source_for_pipeline_full_refresh_endpoint_has_no_partition(self) -> None:
        result = SourceDriver(self.source, self.config).run("agents", [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == "agents"
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None
