import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.sources.oura._config import OuraSourceConfig
from products.warehouse_sources.sources.oura.source import OuraSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, scripted_network


class TestValidateCredentials:
    @pytest.fixture(autouse=True)
    def _oauth_token(self):
        with mock.patch.object(OuraSource, "_get_access_token", return_value="tok"):
            yield

    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_create_is_accepted", 403, None, True),
            ("forbidden_for_specific_schema_is_rejected", 403, "daily_sleep", False),
            ("transport_failure", -1, None, False),
        ]
    )
    def test_validation(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        script: list[ScriptedResponse | BaseException] = (
            [ConnectionError("connection failed")] if status == -1 else [ScriptedResponse(status=status)]
        )
        with scripted_network(script) as network:
            ok, error = OuraSource().validate_credentials(
                OuraSourceConfig(oura_integration_id=1), team_id=1, schema_name=schema_name
            )
        assert ok is expected_ok
        assert network.requests_log[0].path == (
            "/v2/usercollection/daily_sleep" if schema_name else "/v2/usercollection/personal_info"
        )
        if expected_ok:
            assert error is None
        else:
            assert error is not None


class TestAccessToken:
    @parameterized.expand(
        [
            # A pointer to another provider's integration, or to the `token` row of a source created
            # before OAuth, must never have its token sent to Oura.
            ("other_provider", "pinterest-ads", False, None),
            ("legacy_token_row", "oura", False, None),
            ("valid_token", "oura-ring", False, "live-token"),
            ("expired_token_is_refreshed", "oura-ring", True, "fresh-token"),
        ]
    )
    @mock.patch("products.warehouse_sources.sources.oura.source.OauthIntegration")
    @mock.patch("products.warehouse_sources.sources.oura.source.OuraSource.get_oauth_integration")
    def test_access_token(
        self,
        _name: str,
        kind: str,
        expired: bool,
        expected: str | None,
        mock_get_integration: mock.MagicMock,
        mock_oauth: mock.MagicMock,
    ) -> None:
        mock_get_integration.return_value = mock.Mock(kind=kind, access_token="live-token")
        mock_oauth.return_value.access_token_expired.return_value = expired
        mock_oauth.return_value.refresh_access_token.return_value = mock.Mock(access_token="fresh-token")

        if expected is None:
            with pytest.raises(ValueError, match="Integration not found"):
                OuraSource()._get_access_token(OuraSourceConfig(oura_integration_id=7), team_id=1)
            mock_oauth.return_value.refresh_access_token.assert_not_called()
        else:
            assert OuraSource()._get_access_token(OuraSourceConfig(oura_integration_id=7), team_id=1) == expected
