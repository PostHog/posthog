from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.squadcast.source import SquadcastSource

SQUADCAST_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.squadcast"


class TestSquadcastSource:
    def setup_method(self) -> None:
        self.source = SquadcastSource()
        self.config = MagicMock(refresh_token="refresh_tok", region="us")

    def test_validate_credentials_success(self) -> None:
        with patch(f"{SQUADCAST_MODULE}.source.validate_squadcast_credentials", return_value=(True, 200, None)):
            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)

    def test_validate_credentials_invalid_token(self) -> None:
        with patch(
            f"{SQUADCAST_MODULE}.source.validate_squadcast_credentials",
            return_value=(False, 401, "Invalid Squadcast refresh token"),
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1)
            assert ok is False
            assert error == "Invalid Squadcast refresh token"

    def test_validate_credentials_accepts_403_at_source_create(self) -> None:
        # A valid token may only have access to a subset of resources; don't block connection.
        with patch(
            f"{SQUADCAST_MODULE}.source.validate_squadcast_credentials",
            return_value=(False, 403, "Your Squadcast account does not have access to this resource"),
        ):
            assert self.source.validate_credentials(self.config, team_id=1, schema_name=None) == (True, None)

    def test_validate_credentials_rejects_403_for_specific_schema(self) -> None:
        with patch(
            f"{SQUADCAST_MODULE}.source.validate_squadcast_credentials",
            return_value=(False, 403, "Your Squadcast account does not have access to this resource"),
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1, schema_name="incidents")
            assert ok is False
            assert error == "Your Squadcast account does not have access to this resource"
