import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.source import BasetenSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.baseten import (
    BasetenSourceConfig,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.baseten.source"


class TestBasetenCredentials:
    @pytest.mark.parametrize(("valid", "expected_ok"), [(True, True), (False, False)])
    def test_validate_credentials(self, valid: bool, expected_ok: bool) -> None:
        with patch(f"{MODULE}.validate_baseten_credentials", return_value=valid):
            ok, error = BasetenSource().validate_credentials(BasetenSourceConfig(api_key="k"), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok
