from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.source import XmattersSource

XMATTERS_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.xmatters"


class TestXmattersSource:
    def setup_method(self) -> None:
        self.source = XmattersSource()
        self.config = MagicMock(subdomain="acme", username="svc", password="secret")

    def test_validate_credentials_rejects_hostile_subdomain_without_probing(self) -> None:
        # SSRF guard: an invalid subdomain must be rejected before any request is sent.
        self.config.subdomain = "attacker.example/"
        with patch(f"{XMATTERS_MODULE}.source.validate_xmatters_credentials") as mock_validate:
            ok, error = self.source.validate_credentials(self.config, team_id=1)
        assert ok is False
        assert error == "xMatters subdomain is invalid"
        mock_validate.assert_not_called()

    def test_validate_credentials_success(self) -> None:
        with patch(f"{XMATTERS_MODULE}.source.validate_xmatters_credentials", return_value=(True, 200, None)):
            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)

    def test_validate_credentials_invalid(self) -> None:
        with patch(
            f"{XMATTERS_MODULE}.source.validate_xmatters_credentials",
            return_value=(False, 401, "Invalid xMatters credentials"),
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1)
            assert ok is False
            assert error == "Invalid xMatters credentials"

    def test_validate_credentials_accepts_403_at_source_create(self) -> None:
        # A valid account may only be scoped to a subset of resources; don't block connection.
        with patch(
            f"{XMATTERS_MODULE}.source.validate_xmatters_credentials",
            return_value=(False, 403, "no access"),
        ):
            assert self.source.validate_credentials(self.config, team_id=1, schema_name=None) == (True, None)

    def test_validate_credentials_rejects_403_for_specific_schema(self) -> None:
        with patch(
            f"{XMATTERS_MODULE}.source.validate_xmatters_credentials",
            return_value=(False, 403, "no access"),
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1, schema_name="events")
            assert ok is False
            assert error == "no access"
