import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.source import OpsgenieSource

OPSGENIE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie"


class TestOpsgenieSource:
    def setup_method(self) -> None:
        self.source = OpsgenieSource()
        self.config = MagicMock(api_key="key_123", region="us")

    def test_validate_credentials_success(self) -> None:
        with patch(f"{OPSGENIE_MODULE}.source.validate_opsgenie_credentials", return_value=(True, 200, None)):
            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)

    @pytest.mark.parametrize(
        "status,error",
        [
            (401, "Invalid Opsgenie API key"),
            (422, "Your Opsgenie API key format is not valid"),
        ],
    )
    def test_validate_credentials_invalid_key(self, status: int, error: str) -> None:
        with patch(
            f"{OPSGENIE_MODULE}.source.validate_opsgenie_credentials",
            return_value=(False, status, error),
        ):
            ok, returned_error = self.source.validate_credentials(self.config, team_id=1)
            assert ok is False
            assert returned_error == error

    def test_validate_credentials_accepts_403_at_source_create(self) -> None:
        # A valid key may only have access to a subset of resources (e.g. no Configuration
        # access for integrations); don't block connection.
        with patch(
            f"{OPSGENIE_MODULE}.source.validate_opsgenie_credentials",
            return_value=(False, 403, "Your Opsgenie API key does not have access to this resource"),
        ):
            assert self.source.validate_credentials(self.config, team_id=1, schema_name=None) == (True, None)

    def test_validate_credentials_rejects_403_for_specific_schema(self) -> None:
        with patch(
            f"{OPSGENIE_MODULE}.source.validate_opsgenie_credentials",
            return_value=(False, 403, "Your Opsgenie API key does not have access to this resource"),
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1, schema_name="integrations")
            assert ok is False
            assert error == "Your Opsgenie API key does not have access to this resource"
