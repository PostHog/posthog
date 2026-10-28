from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lessannoyingcrm import (
    LessAnnoyingCRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.source import (
    LessAnnoyingCRMSource,
)


class TestLessAnnoyingCRMSource:
    def setup_method(self) -> None:
        self.source = LessAnnoyingCRMSource()
        self.team_id = 123
        self.config = LessAnnoyingCRMSourceConfig(api_key="test-key")

    def test_validate_credentials_success(self) -> None:
        with scripted_network([ScriptedResponse(json={"UserId": "1"})]) as network:
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

        assert network.requests_log[0].json() == {"Function": "GetUser", "Parameters": {}}

    def test_validate_credentials_failure(self) -> None:
        with scripted_network([ScriptedResponse(status=400, json={"ErrorCode": "x"})]):
            ok, error = self.source.validate_credentials(self.config, self.team_id)

        assert ok is False
        assert error is not None
