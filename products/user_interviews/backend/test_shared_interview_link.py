import hmac
import json
import hashlib
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from rest_framework import status

from posthog.api.test.test_sharing import mock_exporter_template
from posthog.models.sharing_configuration import SharingConfiguration

from products.user_interviews.backend.models import UserInterview, UserInterviewClassification, UserInterviewTopic


class _FeatureFlagEnabledMixin(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestGenerateSharedLink(_FeatureFlagEnabledMixin):
    def _topic(self) -> UserInterviewTopic:
        return UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            interviewee_emails=[],
            interviewee_distinct_ids=[],
            topic="Alternatives and comparisons",
            questions=["What were you comparing us against?"],
        )

    def _url(self, topic_id: str) -> str:
        return f"/api/environments/{self.team.id}/user_interview_topics/{topic_id}/shared_link/"

    def test_creates_topic_level_share_not_tied_to_an_interviewee(self) -> None:
        topic = self._topic()
        response = self.client.post(self._url(str(topic.id)))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

        config = SharingConfiguration.objects.get(team=self.team, user_interview_topic=topic, enabled=True)
        # Topic-level share: not attached to any per-invitee IntervieweeContext.
        assert config.interviewee_context_id is None
        assert config.access_token is not None
        assert config.access_token in response.json()["interview_url"]

    def test_is_idempotent(self) -> None:
        topic = self._topic()
        first = self.client.post(self._url(str(topic.id))).json()
        second = self.client.post(self._url(str(topic.id))).json()
        assert first["interview_url"] == second["interview_url"]
        assert SharingConfiguration.objects.filter(user_interview_topic=topic, enabled=True).count() == 1

    def test_shared_link_works_without_any_targeted_interviewees(self) -> None:
        # Unlike generate_links (which needs emails/distinct_ids), a shared link is for a topic with
        # no pre-seeded targets — this is the whole point for anonymous blog visitors.
        topic = self._topic()
        assert not topic.interviewee_emails and not topic.interviewee_distinct_ids
        response = self.client.post(self._url(str(topic.id)))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)


class TestSharedInterviewPublicViewer(APIBaseTest):
    def _shared_config(self) -> SharingConfiguration:
        topic = UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            topic="Alternatives and comparisons",
            agent_context="internal only",
            questions=["q1"],
        )
        return SharingConfiguration.objects.create(team=self.team, user_interview_topic=topic, enabled=True)

    @override_settings(VAPI_PUBLIC_KEY="pk_test", VAPI_ASSISTANT_ID="asst_test")
    @mock_exporter_template
    def test_public_viewer_marks_payload_shared_and_not_already_replied(self) -> None:
        config = self._shared_config()
        self.client.logout()
        response = self.client.get(f"/interview/{config.access_token}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.content.decode()
        self.assertIn("interview", body)
        self.assertIn(config.access_token, body)
        self.assertIn("Alternatives and comparisons", body)
        # agent_context and Vapi creds stay off the HTML, same as the personalised viewer.
        self.assertNotIn("internal only", body)
        self.assertNotIn("pk_test", body)


class TestSharedStartCall(APIBaseTest):
    def _shared_config(self) -> SharingConfiguration:
        topic = UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            topic="Alternatives and comparisons",
            agent_context="topic ctx",
            questions=["What were you comparing?"],
        )
        return SharingConfiguration.objects.create(team=self.team, user_interview_topic=topic, enabled=True)

    def _url(self, token: str | None) -> str:
        return f"/api/user_interviews/share/{token}/start_call/"

    _SESSION_ID_V7 = "018f0b7a-0000-7000-8000-000000000000"

    @override_settings(VAPI_PUBLIC_KEY="pk_test", VAPI_ASSISTANT_ID="asst_test")
    def test_carries_respondent_name_and_valid_linkage_into_metadata(self) -> None:
        config = self._shared_config()
        self.client.logout()
        response = self.client.post(
            self._url(config.access_token),
            data={
                "name": "Robin",
                "respondent_key": "resp-123",
                "distinct_id": "person-abc",
                "session_id": self._SESSION_ID_V7,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        metadata = response.json()["assistant_overrides"]["metadata"]
        assert metadata["shared"] == "true"
        assert metadata["respondent_name"] == "Robin"
        # A valid distinct_id folds into the identifier (no separate distinct_id field).
        assert metadata["interviewee_identifier"] == "person-abc"
        assert metadata["session_id"] == self._SESSION_ID_V7
        assert metadata["sharing_access_token"] == config.access_token
        # The self-reported name greets the respondent.
        assert "Robin" in response.json()["assistant_overrides"]["firstMessage"]

    @override_settings(VAPI_PUBLIC_KEY="pk_test", VAPI_ASSISTANT_ID="asst_test")
    def test_drops_invalid_linkage_but_still_starts(self) -> None:
        # Invalid linkage is a reason to ignore the hint, not to reject the interview: a non-UUIDv7
        # session_id and an illegal distinct_id ("anonymous") are dropped, and the call still starts.
        config = self._shared_config()
        self.client.logout()
        response = self.client.post(
            self._url(config.access_token),
            data={"name": "Robin", "distinct_id": "anonymous", "session_id": "not-a-uuid"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        metadata = response.json()["assistant_overrides"]["metadata"]
        assert metadata["session_id"] == ""
        # Illegal distinct_id dropped, so the identifier falls back to the self-reported name.
        assert metadata["interviewee_identifier"] == "Robin"

    @override_settings(VAPI_PUBLIC_KEY="pk_test", VAPI_ASSISTANT_ID="asst_test")
    def test_honeypot_filled_is_rejected(self) -> None:
        config = self._shared_config()
        self.client.logout()
        response = self.client.post(
            self._url(config.access_token),
            data={"name": "Robin", "_hp": "http://spam.example"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestSharedVapiWebhook(APIBaseTest):
    def _shared_config(self) -> SharingConfiguration:
        topic = UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            topic="Alternatives and comparisons",
            questions=[],
        )
        return SharingConfiguration.objects.create(team=self.team, user_interview_topic=topic, enabled=True)

    def _payload(
        self, token: str | None, *, call_id: str, respondent_key: str, transcript: str, name: str = "Robin"
    ) -> dict:
        return {
            "message": {
                "type": "end-of-call-report",
                "call": {
                    "id": call_id,
                    "metadata": {
                        "sharing_access_token": token,
                        "shared": "true",
                        "respondent_name": name,
                        "respondent_key": respondent_key,
                        # start_call folds a valid distinct_id into interviewee_identifier.
                        "interviewee_identifier": "person-abc",
                        "session_id": "018f0b7a-0000-7000-8000-000000000000",
                    },
                },
                "transcript": transcript,
                "summary": "",
            }
        }

    def _signed_post(self, secret: str, payload: dict) -> Any:
        body = json.dumps(payload)
        signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        return self.client.post(
            "/api/user_interviews/vapi_webhook/",
            data=body,
            content_type="application/json",
            HTTP_X_VAPI_SIGNATURE=signature,
        )

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    def test_persists_respondent_and_linkage_for_topic_share(self) -> None:
        config = self._shared_config()
        self.client.logout()
        response = self._signed_post(
            "topsecret",
            self._payload(config.access_token, call_id="call_1", respondent_key="resp-1", transcript="a real answer"),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        interview = UserInterview.objects.get(team=self.team)
        assert interview.topic_id == config.user_interview_topic_id
        assert interview.respondent_name == "Robin"
        # Provided distinct_id is stored in interviewee_identifier, not a dedicated column.
        assert interview.interviewee_identifier == "person-abc"
        assert interview.interviewee_emails == []

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    @patch("products.user_interviews.backend.presentation.webhooks.posthoganalytics.capture")
    def test_session_id_rides_on_the_lifecycle_event(self, mock_capture) -> None:
        # session_id isn't persisted on the model — it's attached to the conversation event as
        # $session_id so the interview associates with the session recording.
        config = self._shared_config()
        self.client.logout()
        response = self._signed_post(
            "topsecret",
            self._payload(config.access_token, call_id="call_s", respondent_key="resp-s", transcript="hi"),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        ended = [c for c in mock_capture.call_args_list if c.kwargs.get("event") == "user_interview_conversation_ended"]
        assert ended, "expected a conversation_ended event"
        assert ended[0].kwargs["properties"]["$session_id"] == "018f0b7a-0000-7000-8000-000000000000"

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    def test_completed_response_supersedes_abandoned_partial_from_a_refresh(self) -> None:
        config = self._shared_config()
        assert config.user_interview_topic is not None
        # Simulate the abandoned partial an accidental refresh leaves behind for this respondent.
        abandoned = UserInterview.objects.create(
            team=self.team,
            created_by=self.user,
            topic=config.user_interview_topic,
            interviewee_identifier="Robin",
            respondent_key="resp-1",
            transcript="",
            classifications=[UserInterviewClassification.ABANDONED],
        )
        self.client.logout()
        response = self._signed_post(
            "topsecret",
            self._payload(config.access_token, call_id="call_2", respondent_key="resp-1", transcript="a full answer"),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        # The abandoned partial is gone; only the completed response remains for this respondent.
        assert not UserInterview.objects.filter(pk=abandoned.pk).exists()
        remaining = UserInterview.objects.filter(team=self.team, respondent_key="resp-1")
        assert remaining.count() == 1
        assert remaining.first().transcript == "a full answer"  # type: ignore[union-attr]
