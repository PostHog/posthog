from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lessannoyingcrm import (
    LessAnnoyingCRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.source import (
    LessAnnoyingCRMSource,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.source"


class TestLessAnnoyingCRMSource:
    def setup_method(self) -> None:
        self.source = LessAnnoyingCRMSource()
        self.team_id = 123
        self.config = LessAnnoyingCRMSourceConfig(api_key="test-key")

    def test_validate_credentials_success(self) -> None:
        with mock.patch(f"{MODULE}.validate_less_annoying_crm_credentials", return_value=True):
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        with mock.patch(f"{MODULE}.validate_less_annoying_crm_credentials", return_value=False):
            ok, error = self.source.validate_credentials(self.config, self.team_id)
        assert ok is False
        assert error is not None
