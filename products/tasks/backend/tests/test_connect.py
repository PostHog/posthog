import time

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.models.integration import Integration

from products.tasks.backend.logic.connect import (
    REMOTE_REPORT_MAX_CHARS,
    PosthogConnectIntegrationError,
    PosthogConnectRequestError,
    dispatch_remote_task,
    get_remote_task,
    scrub_remote_report,
)

CONNECT_SETTINGS = {
    "POSTHOG_CONNECT_BASE_URL_EU": "https://eu.posthog.com",
    "POSTHOG_CONNECT_OAUTH_CLIENT_ID_EU": "eu-client-id",
    "POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_EU": "eu-secret",
}


@override_settings(**CONNECT_SETTINGS)
class TestPosthogConnectTasks(BaseTest):
    def _integration(self, kind: str = "posthog") -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind=kind,
            integration_id="EU:user-uuid",
            config={"region": "EU", "refreshed_at": int(time.time()), "expires_in": 3600},
            sensitive_config={"refresh_token": "RT", "access_token": "AT"},
        )

    @patch("products.tasks.backend.logic.connect.requests.request")
    def test_dispatch_posts_to_target_region_with_bearer_token(self, mock_request):
        mock_request.return_value = MagicMock(status_code=201)
        mock_request.return_value.json.return_value = {
            "id": "task-1",
            "task_number": 7,
            "title": "Do the thing",
            "latest_run": {"status": "queued"},
        }
        integration = self._integration()

        handle = dispatch_remote_task(
            integration, target_team_id=99, description="query the EU-only DB", title="Do the thing"
        )

        method, url = mock_request.call_args[0][0], mock_request.call_args[0][1]
        assert method == "POST"
        assert url == "https://eu.posthog.com/api/projects/99/tasks/"
        assert mock_request.call_args[1]["headers"]["Authorization"] == "Bearer AT"
        assert mock_request.call_args[1]["json"]["description"] == "query the EU-only DB"
        assert handle == {
            "region": "EU",
            "target_team_id": 99,
            "task_id": "task-1",
            "task_number": 7,
            "title": "Do the thing",
            "status": "queued",
        }

    @patch("products.tasks.backend.logic.connect.requests.request")
    def test_get_remote_task_returns_status_and_scrubbed_report(self, mock_request):
        mock_request.return_value = MagicMock(status_code=200)
        mock_request.return_value.json.return_value = {
            "id": "task-1",
            "latest_run": {"status": "completed", "output": "the answer is 42", "error_message": None},
        }
        integration = self._integration()

        result = get_remote_task(integration, target_team_id=99, task_id="task-1")

        assert mock_request.call_args[0][1] == "https://eu.posthog.com/api/projects/99/tasks/task-1/"
        assert result["status"] == "completed"
        assert result["report"] == "the answer is 42"

    @patch("products.tasks.backend.logic.connect.requests.request")
    def test_wrong_integration_kind_raises(self, mock_request):
        integration = self._integration(kind="github")
        with pytest.raises(PosthogConnectIntegrationError):
            dispatch_remote_task(integration, target_team_id=99, description="x")
        mock_request.assert_not_called()

    @patch("products.tasks.backend.logic.connect.requests.request")
    def test_missing_access_token_raises(self, mock_request):
        integration = self._integration()
        integration.sensitive_config = {"refresh_token": "RT"}  # no access_token, not expired -> no refresh
        integration.save()
        with pytest.raises(PosthogConnectIntegrationError):
            dispatch_remote_task(integration, target_team_id=99, description="x")
        mock_request.assert_not_called()

    @parameterized.expand([(401,), (403,), (500,)])
    def test_non_2xx_raises_request_error(self, code):
        with patch("products.tasks.backend.logic.connect.requests.request") as mock_request:
            mock_request.return_value = MagicMock(status_code=code, text="nope")
            integration = self._integration()
            with pytest.raises(PosthogConnectRequestError) as exc:
                dispatch_remote_task(integration, target_team_id=99, description="x")
            assert exc.value.status_code == code

    @patch("products.tasks.backend.logic.connect.OauthIntegration.refresh_access_token")
    @patch("products.tasks.backend.logic.connect.OauthIntegration.access_token_expired", return_value=True)
    @patch("products.tasks.backend.logic.connect.requests.request")
    def test_expired_token_is_refreshed_before_use(self, mock_request, _mock_expired, mock_refresh):
        mock_request.return_value = MagicMock(status_code=200)
        mock_request.return_value.json.return_value = {"id": "t", "latest_run": {"status": "queued"}}
        integration = self._integration()

        get_remote_task(integration, target_team_id=99, task_id="t")

        mock_refresh.assert_called_once()


class TestScrubRemoteReport:
    def test_none_passthrough(self):
        assert scrub_remote_report(None) is None

    def test_short_report_unchanged(self):
        assert scrub_remote_report("short") == "short"

    def test_long_report_is_bounded(self):
        report = "x" * (REMOTE_REPORT_MAX_CHARS + 100)
        scrubbed = scrub_remote_report(report)
        assert scrubbed is not None
        assert scrubbed.startswith("x" * REMOTE_REPORT_MAX_CHARS)
        assert "truncated" in scrubbed
