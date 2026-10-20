import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pagerduty import (
    PagerDutySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.source import PagerDutySource


class TestPagerDutySource:
    def setup_method(self) -> None:
        self.source = PagerDutySource()
        self.config = PagerDutySourceConfig(api_token="tok_123")

    def test_validate_credentials_success(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)
        assert network.requests_log[0].path == "/users"

    def test_validate_credentials_accepts_403_at_source_create(self) -> None:
        # A valid token may only be scoped to a subset of resources; don't block connection.
        with scripted_network([ScriptedResponse(status=403)]) as network:
            assert self.source.validate_credentials(self.config, team_id=1, schema_name=None) == (True, None)
        assert network.requests_log[0].path == "/users"

    def test_validate_credentials_rejects_403_for_specific_schema(self) -> None:
        with scripted_network([ScriptedResponse(status=403)]) as network:
            ok, error = self.source.validate_credentials(self.config, team_id=1, schema_name="incidents")
            assert ok is False
            assert error == "Your PagerDuty API key does not have access to this resource"
        assert network.requests_log[0].path == "/incidents"

    @pytest.mark.parametrize(
        "schema_name,status_code,expected_ok",
        [
            # A plan-gated table answers 402 (teams) or 404 (priorities) for every account whose
            # plan lacks the feature. The sync skips those tables, so their settings must stay
            # reachable instead of returning an error.
            ("teams", 402, True),
            ("priorities", 404, True),
            # The same statuses on a table no plan gates are real failures.
            ("incidents", 402, False),
            ("users", 404, False),
            # Each gated table has one specific gated status; the other status on that same table
            # is a genuine failure, not "plan lacks it".
            ("teams", 404, False),
            ("priorities", 402, False),
        ],
    )
    def test_validate_credentials_accepts_plan_gated_statuses(
        self, schema_name: str, status_code: int, expected_ok: bool
    ) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            ok, _error = self.source.validate_credentials(self.config, team_id=1, schema_name=schema_name)
        assert ok is expected_ok
        assert network.requests_log[0].path == f"/{schema_name}"
