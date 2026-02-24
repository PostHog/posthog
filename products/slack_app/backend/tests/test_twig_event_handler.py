import hmac
import json
import time
import hashlib

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.test.client import RequestFactory

from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackUserRepoPreference


def _sign_request(body: bytes, secret: str) -> tuple[str, str]:
    ts = str(int(time.time()))
    sig_basestring = f"v0:{ts}:{body.decode('utf-8')}"
    signature = "v0=" + hmac.new(secret.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()
    return signature, ts


class TestTwigEventHandler(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signing_secret = "twig-test-secret"

    def _post_event(self, payload: dict, **extra_headers) -> object:
        body = json.dumps(payload).encode()
        signature, ts = _sign_request(body, self.signing_secret)
        return self.client.post(
            "/slack/twig-event-callback/",
            data=body,
            content_type="application/json",
            HTTP_X_SLACK_SIGNATURE=signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
            **extra_headers,
        )

    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_url_verification(self, mock_config):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}
        response = self._post_event({"type": "url_verification", "challenge": "test-challenge-123"})
        assert response.status_code == 200
        assert response.json() == {"challenge": "test-challenge-123"}

    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_invalid_signature(self, mock_config):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": "different-secret"}
        response = self._post_event({"type": "url_verification", "challenge": "test"})
        assert response.status_code == 403

    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_retry_returns_200(self, mock_config):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}
        body = json.dumps({"type": "event_callback", "event": {"type": "app_mention"}}).encode()
        signature, ts = _sign_request(body, self.signing_secret)
        response = self.client.post(
            "/slack/twig-event-callback/",
            data=body,
            content_type="application/json",
            HTTP_X_SLACK_SIGNATURE=signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
            HTTP_X_SLACK_RETRY_NUM="1",
        )
        assert response.status_code == 200

    @patch("products.slack_app.backend.api.route_twig_event_to_relevant_region")
    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_event_callback_routes(self, mock_config, mock_route):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}
        mock_route.return_value = "handled_locally"
        payload = {
            "type": "event_callback",
            "team_id": "T12345",
            "event": {"type": "app_mention", "text": "hello", "channel": "C001", "user": "U123", "ts": "1234.5678"},
        }
        response = self._post_event(payload)
        assert response.status_code == 202
        mock_route.assert_called_once()

    def test_method_not_allowed(self):
        response = self.client.get("/slack/twig-event-callback/")
        assert response.status_code == 405

    @patch("products.slack_app.backend.api.route_twig_event_to_relevant_region")
    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_non_app_mention_event_is_ignored(self, mock_config, mock_route):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}
        payload = {
            "type": "event_callback",
            "team_id": "T12345",
            "event": {"type": "message", "text": "hello", "channel": "C001", "user": "U123", "ts": "1234.5678"},
        }
        response = self._post_event(payload)
        assert response.status_code == 202
        mock_route.assert_not_called()

    @patch("products.slack_app.backend.api.route_twig_event_to_relevant_region")
    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_proxy_failure_returns_502(self, mock_config, mock_route):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}
        mock_route.return_value = "proxy_failed"
        payload = {
            "type": "event_callback",
            "team_id": "T12345",
            "event": {"type": "app_mention", "text": "hello", "channel": "C001", "user": "U123", "ts": "1234.5678"},
        }
        response = self._post_event(payload)
        assert response.status_code == 502

    @patch("products.slack_app.backend.api.route_twig_event_to_relevant_region")
    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_no_integration_still_returns_202(self, mock_config, mock_route):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}
        mock_route.return_value = "no_integration"
        payload = {
            "type": "event_callback",
            "team_id": "T_UNKNOWN",
            "event": {"type": "app_mention", "text": "hello", "channel": "C001", "user": "U123", "ts": "1234.5678"},
        }
        response = self._post_event(payload)
        assert response.status_code == 202


class TestHandleTwigAppMention(TestCase):
    def setUp(self):
        cache.clear()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)

        self.twig_integration = Integration.objects.create(
            team=self.team,
            kind="slack-twig",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-twig-test"},
        )

        self.github_integration = Integration.objects.create(
            team=self.team,
            kind="github",
            config={"account": {"name": "posthog"}},
            sensitive_config={"access_token": "ghp-test"},
        )

    def _make_event(
        self, text: str = "<@UBOT> fix the bug", thread_ts: str | None = None, ts: str = "1234.5678"
    ) -> dict:
        event: dict = {
            "type": "app_mention",
            "channel": "C001",
            "user": "U123",
            "text": text,
            "ts": ts,
        }
        if thread_ts:
            event["thread_ts"] = thread_ts
        return event

    @patch("products.tasks.backend.models.Task")
    @patch("products.slack_app.backend.api.select_repository")
    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_single_repo_creates_task(
        self, mock_webclient_class, mock_resolve, mock_get_repos, mock_select_repository, mock_task_class
    ):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.auth_test.return_value = {"bot_id": "B001", "user_id": "UBOT"}
        mock_client.conversations_replies.return_value = {
            "messages": [{"user": "U123", "text": "<@UBOT> fix the bug in posthog-js", "ts": "1234.5678"}]
        }

        from products.slack_app.backend.api import SlackUserContext

        mock_resolve.return_value = SlackUserContext(user=self.user, slack_email="dev@example.com")
        mock_get_repos.return_value = ["posthog/posthog-js", "posthog/posthog"]

        from products.slack_app.backend.api import RepoDecision

        mock_select_repository.return_value = RepoDecision(
            mode="auto", repository="posthog/posthog-js", reason="llm_single", llm_called=True
        )

        from products.slack_app.backend.api import handle_twig_app_mention

        handle_twig_app_mention(self._make_event(ts="1.001"), self.twig_integration)

        mock_task_class.create_and_run.assert_called_once()
        call_kwargs = mock_task_class.create_and_run.call_args.kwargs
        assert call_kwargs["repository"] == "posthog/posthog-js"
        assert call_kwargs["origin_product"] == mock_task_class.OriginProduct.SLACK
        assert call_kwargs["slack_thread_context"] is not None

    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.select_repository")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_ambiguous_repo_posts_external_select_picker(
        self, mock_webclient_class, mock_resolve, mock_select_repository, mock_get_repos
    ):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.auth_test.return_value = {"bot_id": "B001", "user_id": "UBOT"}
        mock_client.conversations_replies.return_value = {
            "messages": [{"user": "U123", "text": "fix the bug", "ts": "1234.5678"}]
        }

        from products.slack_app.backend.api import SlackUserContext

        mock_resolve.return_value = SlackUserContext(user=self.user, slack_email="dev@example.com")
        mock_get_repos.return_value = ["posthog/posthog", "posthog/posthog-js"]

        from products.slack_app.backend.api import RepoDecision

        mock_select_repository.return_value = RepoDecision(
            mode="picker", repository=None, reason="llm_no_match", llm_called=True
        )

        from products.slack_app.backend.api import handle_twig_app_mention

        handle_twig_app_mention(self._make_event(ts="2.002"), self.twig_integration)

        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        blocks = call_kwargs["blocks"]
        assert blocks[0]["block_id"].startswith("twig_repo_picker_v2:")
        assert blocks[0]["accessory"]["type"] == "external_select"
        assert blocks[0]["accessory"]["action_id"] == "twig_repo_select"

    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.select_repository")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_no_github_integration_posts_text_fallback(
        self, mock_webclient_class, mock_resolve, mock_select_repository, mock_get_repos
    ):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.auth_test.return_value = {"bot_id": "B001", "user_id": "UBOT"}
        mock_client.conversations_replies.return_value = {
            "messages": [{"user": "U123", "text": "fix the bug", "ts": "1234.5678"}]
        }

        from products.slack_app.backend.api import SlackUserContext

        mock_resolve.return_value = SlackUserContext(user=self.user, slack_email="dev@example.com")
        mock_get_repos.return_value = []

        from products.slack_app.backend.api import RepoDecision

        mock_select_repository.return_value = RepoDecision(
            mode="picker", repository=None, reason="no_repos", llm_called=False
        )

        from products.slack_app.backend.api import handle_twig_app_mention

        handle_twig_app_mention(self._make_event(ts="2.003"), self.twig_integration)

        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert "blocks" not in call_kwargs or call_kwargs.get("blocks") is None
        assert "github" in call_kwargs["text"].lower()

    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.select_repository")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_ambiguous_repo_stores_context_in_cache(
        self, mock_webclient_class, mock_resolve, mock_select_repository, mock_get_repos
    ):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.auth_test.return_value = {"bot_id": "B001", "user_id": "UBOT"}
        mock_client.conversations_replies.return_value = {
            "messages": [{"user": "U123", "text": "fix the bug", "ts": "1234.5678"}]
        }

        from products.slack_app.backend.api import SlackUserContext

        mock_resolve.return_value = SlackUserContext(user=self.user, slack_email="dev@example.com")
        mock_get_repos.return_value = ["posthog/posthog", "posthog/posthog-js"]

        from products.slack_app.backend.api import RepoDecision

        mock_select_repository.return_value = RepoDecision(
            mode="picker", repository=None, reason="llm_ambiguous", llm_called=True
        )

        from products.slack_app.backend.api import handle_twig_app_mention

        handle_twig_app_mention(self._make_event(ts="2.004"), self.twig_integration)

        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        block_id = call_kwargs["blocks"][0]["block_id"]
        from products.slack_app.backend.api import _decode_picker_context, _extract_context_token

        context_token = _extract_context_token({"block_id": block_id})

        ctx = _decode_picker_context(context_token)
        assert ctx is not None
        assert ctx["integration_id"] == self.twig_integration.id
        assert ctx["channel"] == "C001"
        assert ctx["mentioning_slack_user_id"] == "U123"

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_auth_failure_returns_early(self, mock_webclient_class, mock_resolve):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_resolve.return_value = None

        from products.slack_app.backend.api import handle_twig_app_mention

        handle_twig_app_mention(self._make_event(ts="3.003"), self.twig_integration)

        mock_client.auth_test.assert_not_called()

    @patch("products.tasks.backend.models.Task")
    @patch("products.slack_app.backend.api.select_repository")
    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_task_creation_failure_posts_error_to_slack(
        self, mock_webclient_class, mock_resolve, mock_get_repos, mock_select_repository, mock_task_class
    ):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.auth_test.return_value = {"bot_id": "B001", "user_id": "UBOT"}
        mock_client.conversations_replies.return_value = {
            "messages": [{"user": "U123", "text": "<@UBOT> fix the bug", "ts": "1234.5678"}]
        }

        from products.slack_app.backend.api import SlackUserContext

        mock_resolve.return_value = SlackUserContext(user=self.user, slack_email="dev@example.com")
        mock_get_repos.return_value = ["posthog/posthog-js", "posthog/posthog"]

        from products.slack_app.backend.api import RepoDecision

        mock_select_repository.return_value = RepoDecision(
            mode="auto", repository="posthog/posthog-js", reason="llm_single", llm_called=True
        )
        mock_task_class.create_and_run.side_effect = RuntimeError("temporal connection failed")

        from products.slack_app.backend.api import handle_twig_app_mention

        handle_twig_app_mention(self._make_event(ts="4.004"), self.twig_integration)

        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert call_kwargs["thread_ts"] == "4.004"
        assert "internal error" in call_kwargs["text"].lower()

    @patch("products.tasks.backend.models.Task")
    @patch("products.slack_app.backend.api.select_repository")
    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_threaded_mention_carries_user_message_ts(
        self, mock_webclient_class, mock_resolve, mock_get_repos, mock_select_repository, mock_task_class
    ):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.auth_test.return_value = {"bot_id": "B001", "user_id": "UBOT"}
        mock_client.conversations_replies.return_value = {
            "messages": [{"user": "U123", "text": "<@UBOT> fix the bug", "ts": "9999.0001"}]
        }

        from products.slack_app.backend.api import SlackUserContext

        mock_resolve.return_value = SlackUserContext(user=self.user, slack_email="dev@example.com")
        mock_get_repos.return_value = ["posthog/posthog-js", "posthog/posthog"]

        from products.slack_app.backend.api import RepoDecision

        mock_select_repository.return_value = RepoDecision(
            mode="auto", repository="posthog/posthog-js", reason="llm_single", llm_called=True
        )

        from products.slack_app.backend.api import handle_twig_app_mention

        event = self._make_event(ts="9999.0001", thread_ts="8888.0000")
        handle_twig_app_mention(event, self.twig_integration)

        mock_task_class.create_and_run.assert_called_once()
        context = mock_task_class.create_and_run.call_args.kwargs["slack_thread_context"]
        assert context.thread_ts == "8888.0000"
        assert context.user_message_ts == "9999.0001"

    def test_idempotency_guard_prevents_duplicate(self):
        from products.slack_app.backend.api import handle_twig_app_mention

        event = self._make_event(ts="5.005")

        with patch("products.slack_app.backend.api.cache") as mock_cache:
            mock_cache.add.return_value = False

            with patch("products.slack_app.backend.api.resolve_slack_user") as mock_resolve:
                handle_twig_app_mention(event, self.twig_integration)
                mock_resolve.assert_not_called()

    @patch("products.slack_app.backend.api.logger")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_outer_exception_is_caught(self, mock_webclient_class, mock_resolve, mock_logger):
        mock_resolve.side_effect = RuntimeError("unexpected")

        from products.slack_app.backend.api import handle_twig_app_mention

        handle_twig_app_mention(self._make_event(ts="6.006"), self.twig_integration)

        mock_logger.exception.assert_any_call("twig_app_mention_failed", error="unexpected")

    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_default_repo_set_without_repo_posts_search_picker(
        self, mock_webclient_class, mock_resolve, mock_get_repos
    ):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_get_repos.return_value = ["posthog/posthog", "posthog/posthog-js"]

        from products.slack_app.backend.api import SlackUserContext, handle_twig_app_mention

        mock_resolve.return_value = SlackUserContext(user=self.user, slack_email="dev@example.com")
        event = self._make_event(text="<@UBOT> default repo set", ts="7.006")
        handle_twig_app_mention(event, self.twig_integration)

        mock_client.chat_postMessage.assert_called_once()
        blocks = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        assert blocks[0]["accessory"]["action_id"] == "twig_default_repo_select"
        assert "Search GitHub repositories" in blocks[0]["accessory"]["placeholder"]["text"]

    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_default_repo_set_command_saves_preference(self, mock_webclient_class, mock_resolve, mock_get_repos):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_get_repos.return_value = ["posthog/posthog", "posthog/posthog-js"]

        from products.slack_app.backend.api import SlackUserContext, handle_twig_app_mention

        mock_resolve.return_value = SlackUserContext(user=self.user, slack_email="dev@example.com")
        event = self._make_event(text="<@UBOT> default repo set posthog/posthog-js", ts="7.007")
        handle_twig_app_mention(event, self.twig_integration)

        preference = SlackUserRepoPreference.objects.get(team=self.team, user=self.user)
        assert preference.repository == "posthog/posthog-js"
        mock_client.chat_postMessage.assert_called_once()
        assert "Set your default repository" in mock_client.chat_postMessage.call_args.kwargs["text"]

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_default_repo_show_command_posts_current_value(self, mock_webclient_class, mock_resolve):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        SlackUserRepoPreference.objects.create(team=self.team, user=self.user, repository="posthog/posthog")

        from products.slack_app.backend.api import SlackUserContext, handle_twig_app_mention

        mock_resolve.return_value = SlackUserContext(user=self.user, slack_email="dev@example.com")
        event = self._make_event(text="<@UBOT> default repo show", ts="8.008")
        handle_twig_app_mention(event, self.twig_integration)

        mock_client.chat_postMessage.assert_called_once()
        assert "posthog/posthog" in mock_client.chat_postMessage.call_args.kwargs["text"]

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_default_repo_clear_command_deletes_value(self, mock_webclient_class, mock_resolve):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        SlackUserRepoPreference.objects.create(team=self.team, user=self.user, repository="posthog/posthog")

        from products.slack_app.backend.api import SlackUserContext, handle_twig_app_mention

        mock_resolve.return_value = SlackUserContext(user=self.user, slack_email="dev@example.com")
        event = self._make_event(text="<@UBOT> default repo clear", ts="9.009")
        handle_twig_app_mention(event, self.twig_integration)

        assert SlackUserRepoPreference.objects.filter(team=self.team, user=self.user).count() == 0
        mock_client.chat_postMessage.assert_called_once()
        assert "Cleared your default repository" in mock_client.chat_postMessage.call_args.kwargs["text"]


class TestRouteTwigEventToRelevantRegion(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.twig_integration = Integration.objects.create(
            team=self.team,
            kind="slack-twig",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-twig-test"},
        )
        self.event = {"type": "app_mention", "channel": "C001", "user": "U123", "ts": "1234.5678"}

    @patch("products.slack_app.backend.tasks.process_twig_mention.delay")
    @override_settings(DEBUG=False)
    def test_local_match_dispatches_celery_task(self, mock_delay):
        request = self.factory.post("/slack/twig-event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_twig_event_to_relevant_region

        result = route_twig_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_delay.assert_called_once_with(self.event, self.twig_integration.id)

    @patch("products.slack_app.backend.api.proxy_slack_event_to_secondary_region")
    @patch("products.slack_app.backend.api.SLACK_PRIMARY_REGION_DOMAIN", "eu.posthog.com")
    @override_settings(DEBUG=False)
    def test_proxies_to_secondary_when_no_integration_in_primary(self, mock_proxy):
        mock_proxy.return_value = True
        request = self.factory.post("/slack/twig-event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_PROXIED, route_twig_event_to_relevant_region

        result = route_twig_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_PROXIED
        mock_proxy.assert_called_once_with(request)

    @patch("products.slack_app.backend.api.proxy_slack_event_to_secondary_region")
    @patch("products.slack_app.backend.api.SLACK_PRIMARY_REGION_DOMAIN", "eu.posthog.com")
    @override_settings(DEBUG=False)
    def test_proxy_failure_returns_proxy_failed(self, mock_proxy):
        mock_proxy.return_value = False
        request = self.factory.post("/slack/twig-event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_PROXY_FAILED, route_twig_event_to_relevant_region

        result = route_twig_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_PROXY_FAILED

    @patch("products.slack_app.backend.tasks.process_twig_mention.delay")
    @patch("products.slack_app.backend.api.proxy_slack_event_to_secondary_region")
    @override_settings(DEBUG=False)
    def test_no_integration_in_secondary_returns_no_integration(self, mock_proxy, mock_delay):
        request = self.factory.post("/slack/twig-event-callback/", HTTP_HOST="us.posthog.com")

        from products.slack_app.backend.api import ROUTE_NO_INTEGRATION, route_twig_event_to_relevant_region

        result = route_twig_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_NO_INTEGRATION
        mock_delay.assert_not_called()
        mock_proxy.assert_not_called()
