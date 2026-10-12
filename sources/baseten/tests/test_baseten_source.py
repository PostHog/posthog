import pytest
from unittest.mock import patch

from sources.baseten._config import BasetenSourceConfig
from sources.baseten.source import BasetenSource

MODULE = "sources.baseten.source"


class TestBasetenCredentials:
    @pytest.mark.parametrize(("valid", "expected_ok"), [(True, True), (False, False)])
    def test_validate_credentials(self, valid: bool, expected_ok: bool) -> None:
        with patch(f"{MODULE}.validate_baseten_credentials", return_value=valid):
            ok, error = BasetenSource().validate_credentials(BasetenSourceConfig(api_key="k"), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok
