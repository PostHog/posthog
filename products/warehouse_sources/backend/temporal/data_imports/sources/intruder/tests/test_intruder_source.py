from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig, SourceFieldInputConfigType
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.intruder import (
    IntruderSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder.source import IntruderSource


class TestSourceConfig:
    def test_single_secret_access_token_field(self) -> None:
        # A single required, secret bearer-token field is the whole auth surface — a non-secret or
        # non-required regression would leak or break the token input.
        fields = IntruderSource().get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "access_token"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True


class TestValidateCredentials:
    @parameterized.expand([("valid", True), ("invalid", False)])
    def test_delegates_to_transport(self, _name: str, transport_result: bool) -> None:
        with patch.object(source_module, "validate_intruder_credentials", return_value=transport_result) as mock:
            ok, error = IntruderSource().validate_credentials(IntruderSourceConfig(access_token="tok"), team_id=1)
        mock.assert_called_once_with("tok")
        assert ok is transport_result
        assert (error is None) is transport_result
