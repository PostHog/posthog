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

    def _url(self, token: str) -> str:
        return f"/api/user_interviews/share/{token}/start_call/"

    @override_settings(VAPI_PUBLIC_KEY="pk_test", VAPI_ASSISTANT_ID="asst_test")
    def test_carries_respondent_name_and_linkage_into_metadata(self) -> None:
        config = self._shared_config()
        self.client.logout()
        response = self.client.post(
            self._url(config.access_token),
            data={
                "name": "Robin",
                "respondent_key": "resp-123",
                "distinct_id": "person-abc",
                "session_id": "sess-xyz",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        metadata = response.json()["assistant_overrides"]["metadata"]
        assert metadata["shared"] == "true"
        assert metadata["respondent_name"] == "Robin"
        assert metadata["distinct_id"] == "person-abc"
        assert metadata["session_id"] == "sess-xyz"
        assert metadata["sharing_access_token"] == config.access_token
        # The self-reported name greets the respondent.
        assert "Robin" in response.json()["assistant_overrides"]["firstMessage"]

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

    def _payload(self, token: str, *, call_id: str, respondent_key: str, transcript: str, name: str = "Robin") -> dict:
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
                        "distinct_id": "person-abc",
                        "session_id": "sess-xyz",
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
        assert interview.distinct_id == "person-abc"
        assert interview.session_id == "sess-xyz"
        assert interview.interviewee_emails == []

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
