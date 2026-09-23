from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

import requests
from parameterized import parameterized

from posthog.models import Team, User
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.tasks.backend.logic.services.voice_sessions import VoiceSessionService, VoiceSessionUnavailable
from products.tasks.backend.models import Task


class TestVoiceSessions(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.task = Task.objects.create(team=self.team, created_by=self.user, title="Example task")
        self.url = f"/api/projects/{self.team.id}/tasks/{self.task.id}/voice/"
        self.flag = self.enterContext(
            patch(
                "products.tasks.backend.presentation.views.voice_sessions.posthoganalytics.feature_enabled",
                return_value=True,
            )
        )
        self.provider = self.enterContext(
            patch(
                "products.tasks.backend.facade.api.create_voice_session",
                return_value={"sdp": "answer"},
            )
        )

    @parameterized.expand(
        [
            (False, True, True),
            (True, False, True),
            (True, True, False),
            (True, True, None),
            (True, True, "control"),
        ]
    )
    def test_denied_access_never_creates_a_provider_session(self, staff: bool, consent: bool, flag: object) -> None:
        self.user.is_staff = staff
        self.user.save(update_fields=["is_staff"])
        self.organization.is_ai_data_processing_approved = consent
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.flag.return_value = flag
        assert self.client.post(self.url, {"sdp": "offer"}).status_code == 403
        self.provider.assert_not_called()

    @parameterized.expand([("other_team",), ("private_task",), ("missing",)])
    def test_task_visibility_is_required(self, scenario: str) -> None:
        if scenario == "other_team":
            self.task.team = Team.objects.create(organization=self.organization)
        elif scenario == "private_task":
            self.task.created_by = User.objects.create_user(
                email="other@example.com", first_name="Other", password="test"
            )
            self.task.internal = True
        else:
            self.url = f"/api/projects/{self.team.id}/tasks/{uuid4()}/voice/"
        if scenario != "missing":
            self.task.save()
        assert self.client.post(self.url, {"sdp": "offer"}).status_code == 404
        self.provider.assert_not_called()

    def test_staff_can_connect_without_receiving_a_provider_key(self) -> None:
        response = self.client.post(self.url, {"sdp": "offer", "context": "User: Check the task"})
        assert response.status_code == 201
        assert response.json() == {"sdp": "answer"}
        assert response["Cache-Control"] == "no-store"
        self.provider.assert_called_once_with("offer", "User: Check the task", structured_tools=False)

    def test_sandbox_token_cannot_spend_on_voice_even_for_staff(self) -> None:
        application = OAuthApplication.objects.create(
            name="Example sandbox",
            client_id=ARRAY_APP_CLIENT_ID_DEV,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            user=self.user,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token="pha_example_voice_test",
            expires=timezone.now() + timedelta(hours=1),
            scope="task:read task:write",
            scoped_teams=[self.team.id],
            sandbox_task_id=uuid4(),
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        assert self.client.post(self.url, {"sdp": "offer"}).status_code == 403
        self.provider.assert_not_called()

    def test_rate_limit_stops_excess_sessions(self) -> None:
        for _ in range(3):
            assert self.client.post(self.url, {"sdp": "offer"}).status_code == 201
        assert self.client.post(self.url, {"sdp": "offer"}).status_code == 429
        assert self.provider.call_count == 3

    @parameterized.expand([("flag",), ("provider",)])
    def test_unavailable_services_fail_closed(self, service: str) -> None:
        if service == "flag":
            self.flag.side_effect = RuntimeError("unavailable")
        else:
            self.provider.side_effect = VoiceSessionUnavailable
        response = self.client.post(self.url, {"sdp": "offer"})
        assert response.status_code == (403 if service == "flag" else 503)
        if service == "flag":
            self.provider.assert_not_called()


@override_settings(OPENAI_LIVE_API_KEY="example-not-a-real-key")
class TestVoiceProvider(SimpleTestCase):
    @patch("products.tasks.backend.logic.services.voice_sessions.create_live_session")
    def test_only_returns_sdp_and_disables_recording(self, provider: Mock) -> None:
        provider.return_value.json.return_value = {"transport": {"sdp": "answer"}, "secret": "never-return"}
        assert VoiceSessionService().create("offer", "User: Hello") == {"sdp": "answer"}
        payload = provider.call_args.args[1]
        assert payload["session"]["store"] is False
        assert payload["session"]["delegation"] == {"type": "client"}
        assert payload["transport"] == {"type": "webrtc", "sdp": "offer"}

    @parameterized.expand([("timeout",), ("invalid_response",), ("missing_key",)])
    @patch("products.tasks.backend.logic.services.voice_sessions.create_live_session")
    def test_provider_failure_has_no_sensitive_details(self, failure: str, provider: Mock) -> None:
        if failure == "timeout":
            provider.side_effect = requests.Timeout("secret details")
        elif failure == "invalid_response":
            provider.return_value.json.return_value = {"transport": {"sdp": None}}
        with override_settings(OPENAI_LIVE_API_KEY="" if failure == "missing_key" else "example-key"):
            with self.assertRaises(VoiceSessionUnavailable):
                VoiceSessionService().create("offer", "")
        if failure == "missing_key":
            provider.assert_not_called()
