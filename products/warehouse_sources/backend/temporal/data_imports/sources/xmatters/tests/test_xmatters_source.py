from unittest.mock import MagicMock, patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.source import XmattersSource

XMATTERS_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.xmatters"


class TestXmattersSource:
    def setup_method(self) -> None:
        self.source = XmattersSource()
        self.config = MagicMock(subdomain="acme", username="svc", password="secret")

    def test_source_config_is_visible_and_alpha(self) -> None:
        # A finished source must not carry `unreleasedSource` (which hides it) and marks
        # newness via releaseStatus instead.
        config = self.source.get_source_config
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/xmatters.png"

    def test_source_config_fields(self) -> None:
        fields = self.source.get_source_config.fields
        assert fields is not None
        by_name = {f.name: f for f in fields if isinstance(f, SourceFieldInputConfig)}
        assert set(by_name) == {"subdomain", "username", "password"}
        # Only the password is a secret; the subdomain is the connection host.
        assert by_name["password"].type == SourceFieldInputConfigType.PASSWORD
        assert by_name["password"].secret is True
        assert by_name["subdomain"].secret is not True

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # Retargeting the subdomain must re-require the stored secret.
        assert self.source.connection_host_fields == ["subdomain"]

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
