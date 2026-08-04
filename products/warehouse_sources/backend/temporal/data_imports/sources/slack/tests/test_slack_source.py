from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import WebhookSource
from products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack import (
    validate_credentials as validate_slack_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.slack.source import SlackSource

SOURCE_VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.slack.source.validate_slack_credentials"
)
SLACK_GET_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._slack_get"


class TestSlackValidateCredentialsProbe:
    @mock.patch(SLACK_GET_PATCH)
    def test_returns_slack_error_code_on_rejection(self, mock_get):
        response = MagicMock()
        response.json.return_value = {"ok": False, "error": "missing_scope"}
        mock_get.return_value = response
        assert validate_slack_credentials("token") == (False, "missing_scope")

    @mock.patch(SLACK_GET_PATCH)
    def test_ok_true_is_valid(self, mock_get):
        response = MagicMock()
        response.json.return_value = {"ok": True}
        mock_get.return_value = response
        assert validate_slack_credentials("token") == (True, None)

    @mock.patch(SLACK_GET_PATCH)
    def test_unreachable_returns_none_code(self, mock_get):
        # An exhausted retry or network error must not look like a definitive rejection.
        mock_get.side_effect = Exception("boom")
        assert validate_slack_credentials("token") == (False, None)


class TestSlackSourceValidateCredentials:
    def _validate(self, mock_result):
        source = SlackSource()
        with (
            mock.patch(SOURCE_VALIDATE_PATCH, return_value=mock_result) as mock_validate,
            mock.patch.object(source, "_resolve_access_token", return_value=("token", None, "cache")),
        ):
            result = source.validate_credentials(MagicMock(), team_id=1)
        mock_validate.assert_called_once_with("token")
        return result

    @parameterized.expand(
        [
            # A valid token that only lacks scopes must guide a re-auth, not read as "invalid".
            ("missing_scope", "missing_scope", "missing required scopes"),
            ("invalid_auth", "invalid_auth", "token is invalid"),
            ("token_revoked", "token_revoked", "revoked"),
            # An unmapped Slack error still surfaces the specific code rather than a generic string.
            ("unknown_code", "some_new_error", "some_new_error"),
        ]
    )
    def test_rejection_maps_error_code_to_specific_message(self, _name, error_code, expected_substring):
        is_valid, message = self._validate((False, error_code))
        assert is_valid is False
        assert message is not None
        assert expected_substring in message

    def test_unreachable_is_not_reported_as_invalid(self):
        is_valid, message = self._validate((False, None))
        assert is_valid is False
        assert message == "Couldn't reach Slack to verify your credentials. Please try again in a moment."

    def test_valid_credentials(self):
        is_valid, message = self._validate((True, None))
        assert is_valid is True
        assert message is None


class TestSlackSourceWebhookEventSync:
    def test_does_not_override_reconcile_hooks(self):
        # Slack configures webhooks manually — inheriting the base no-ops keeps reconcile away from it.
        assert SlackSource.sync_webhook_events is WebhookSource.sync_webhook_events
        assert SlackSource.get_desired_webhook_events is WebhookSource.get_desired_webhook_events

    def test_get_desired_webhook_events_is_none(self):
        assert SlackSource().get_desired_webhook_events(MagicMock(), ["messages"]) is None

    def test_sync_webhook_events_is_noop_success(self):
        result = SlackSource().sync_webhook_events(
            MagicMock(), "https://example.com/h", team_id=1, eligible_schema_names=["messages"]
        )
        assert result.success is True
        assert result.error is None
