import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.customerly.settings import (
    CUSTOMERLY_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.customerly.source import CustomerlySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.customerly import (
    CustomerlySourceConfig,
)


class TestCustomerlySource:
    def setup_method(self) -> None:
        self.source = CustomerlySource()
        self.team_id = 123
        self.config = CustomerlySourceConfig(access_token="token")

    @pytest.mark.parametrize("is_valid", [True, False])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.customerly.source.validate_customerly_credentials"
    )
    def test_validate_credentials(self, mock_validate: mock.MagicMock, is_valid: bool) -> None:
        mock_validate.return_value = is_valid

        result, error = self.source.validate_credentials(self.config, self.team_id)

        assert result is is_valid
        assert (error is None) is is_valid
        mock_validate.assert_called_once_with("token")

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_for_pipeline_plumbs_schema_name(self, endpoint: str) -> None:
        result = SourceDriver(self.source, self.config).run(endpoint, [ScriptedResponse(json={"data": []})])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == [CUSTOMERLY_ENDPOINTS[endpoint].primary_key]
