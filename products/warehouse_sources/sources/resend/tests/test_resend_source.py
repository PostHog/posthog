from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.sources.resend._config import ResendAuthMethodConfig, ResendSourceConfig
from products.warehouse_sources.sources.resend.source import ResendSource
from products.warehouse_sources.sources.sdk import BearerTokenAuth
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, scripted_network


def _api_key_config(api_key: str = "re_test_key") -> ResendSourceConfig:
    return ResendSourceConfig(auth_method=ResendAuthMethodConfig(selection="api_key", api_key=api_key))


def _oauth_config(integration_id: int = 42) -> ResendSourceConfig:
    return ResendSourceConfig(
        auth_method=ResendAuthMethodConfig(selection="oauth", resend_integration_id=integration_id)
    )


class TestResendSource:
    def setup_method(self):
        self.source = ResendSource()
        self.team_id = 123
        self.config = _api_key_config()

    @parameterized.expand(
        [
            ("audiences", "https://api.resend.com/audiences", "Audiences"),
            ("broadcasts", "https://api.resend.com/broadcasts", "Broadcasts"),
            ("domains", "https://api.resend.com/domains", "Domains"),
            # The real List Emails failure carries the paginator's ?limit=100 suffix, so the scoped
            # key must still match it as a prefix.
            ("emails", "https://api.resend.com/emails?limit=100", "Emails"),
        ]
    )
    def test_scoped_bad_request_is_non_retryable(self, _name: str, url: str, expected_word: str):
        errors = self.source.get_non_retryable_errors()
        raised = f"400 Client Error: Bad Request for url: {url}"

        matched = [message for key, message in errors.items() if key in raised]

        assert len(matched) == 1
        assert matched[0] is not None and expected_word in matched[0]

    def test_validate_credentials_api_key_success(self):
        with scripted_network([ScriptedResponse(json={"data": []})]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        assert network.requests_log[0].headers["authorization"] == "Bearer re_test_key"

    @parameterized.expand(
        [
            (
                "restricted_key",
                ScriptedResponse(
                    status=401,
                    json={
                        "statusCode": 401,
                        "name": "restricted_api_key",
                        "message": "This API key is restricted to only send emails",
                    },
                ),
                "can only send emails",
            ),
            (
                "other_401",
                ScriptedResponse(status=401, json={"name": "missing_api_key", "message": "Missing API key"}),
                "rejected the API key",
            ),
            (
                "invalid_key_400",
                ScriptedResponse(status=400, json={"name": "validation_error", "message": "API key is invalid"}),
                "rejected the API key",
            ),
            ("non_json_401", ScriptedResponse(status=401, body=b"<html>nope</html>"), "rejected the API key"),
            ("json_list_401", ScriptedResponse(status=401, json=["restricted_api_key"]), "rejected the API key"),
            ("server_error", ScriptedResponse(status=500, json={"name": "application_error"}), "Couldn't reach Resend"),
            (
                "rate_limited",
                ScriptedResponse(status=429, json={"name": "rate_limit_exceeded"}),
                "Couldn't reach Resend",
            ),
            ("transport_error", ConnectionError("connection reset"), "Couldn't reach Resend"),
        ]
    )
    def test_validate_credentials_api_key_failure_messages(
        self, _name: str, scripted: ScriptedResponse | BaseException, expected_fragment: str
    ):
        with scripted_network([scripted]):
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message is not None and expected_fragment in error_message

    @mock.patch("products.warehouse_sources.sources.resend.source.resolve_resend_oauth_token")
    @mock.patch.object(ResendSource, "get_oauth_integration")
    def test_validate_credentials_oauth_restricted_key_body_keeps_reconnect_message(
        self, _mock_get_integration, mock_resolve
    ):
        mock_resolve.return_value = "oauth_access_token"

        with scripted_network([ScriptedResponse(status=401, json={"name": "restricted_api_key"})]):
            _, error_message = self.source.validate_credentials(_oauth_config(), self.team_id)

        assert error_message is not None and "reconnect" in error_message.lower()

    def test_validate_credentials_api_key_missing(self):
        config = ResendSourceConfig(auth_method=ResendAuthMethodConfig(selection="api_key", api_key=None))

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message is not None and "Missing Resend API key" in error_message

    @mock.patch("products.warehouse_sources.sources.resend.source.resolve_resend_oauth_token")
    @mock.patch.object(ResendSource, "get_oauth_integration")
    def test_validate_credentials_oauth_failure(self, mock_get_integration, mock_resolve):
        mock_resolve.return_value = "oauth_access_token"

        with scripted_network([ScriptedResponse(status=401, json={"message": "unauthorized"})]) as network:
            is_valid, error_message = self.source.validate_credentials(_oauth_config(), self.team_id)

        assert is_valid is False
        assert error_message is not None and "reconnect" in error_message.lower()
        assert network.requests_log[0].headers["authorization"] == "Bearer oauth_access_token"

    @mock.patch.object(ResendSource, "get_oauth_integration", side_effect=ValueError("Integration not found: 42"))
    def test_validate_credentials_oauth_deleted_integration(self, _mock_get_integration):
        is_valid, error_message = self.source.validate_credentials(_oauth_config(), self.team_id)

        assert is_valid is False
        # The raw "Integration not found: <id>" must be mapped to curated wording so the wizard
        # never leaks the internal string or the volatile integration ID.
        assert error_message == "The linked Resend integration no longer exists. Please reconnect your Resend account."
        assert "42" not in (error_message or "")

    def test_validate_credentials_oauth_missing_integration_id(self):
        config = ResendSourceConfig(auth_method=ResendAuthMethodConfig(selection="oauth", resend_integration_id=None))

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message == "Resend integration is not configured. Please reconnect your Resend account."

    def test_source_for_pipeline_api_key_passes_bearer_auth(self):
        result = SourceDriver(self.source, self.config).run(
            "audiences",
            [ScriptedResponse(json={"data": []})],
            team_id=123,
            job_id="job-1",
        )

        assert result.paths == ["/audiences"]
        assert result.requests[0].headers["authorization"] == "Bearer re_test_key"

    @mock.patch("products.warehouse_sources.sources.resend.source.resolve_resend_oauth_token")
    @mock.patch.object(ResendSource, "get_oauth_integration")
    def test_source_for_pipeline_oauth_passes_integration_auth(self, mock_get_integration, mock_resolve):
        mock_resolve.return_value = "oauth_access_token"

        result = SourceDriver(self.source, _oauth_config()).run(
            "emails",
            [ScriptedResponse(json={"data": [], "has_more": False})],
            team_id=123,
            job_id="job-1",
        )

        assert result.requests[0].headers["authorization"] == "Bearer oauth_access_token"
        mock_resolve.assert_called_once_with(42, 123)


class TestResendSourceForwarding:
    def setup_method(self):
        self.source = ResendSource()
        self.config = _api_key_config()

    @mock.patch("products.warehouse_sources.sources.resend.source.resend_source")
    def test_source_for_pipeline_api_key_passes_bearer_auth(self, mock_resend_source):
        mock_resend_source.return_value = mock.MagicMock()

        inputs = mock.MagicMock()
        inputs.schema_name = "audiences"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_resend_source.call_args.kwargs
        assert kwargs["endpoint"] == "audiences"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert isinstance(kwargs["auth"], BearerTokenAuth)
        assert kwargs["auth"].token == "re_test_key"
