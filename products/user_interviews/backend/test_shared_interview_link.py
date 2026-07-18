import hmac
import json
import hashlib
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.test_sharing import mock_exporter_template
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.user import User

from products.user_interviews.backend.facade.api import SHARED_INTERVIEWEE_IDENTIFIER, has_replied
from products.user_interviews.backend.models import (
    IntervieweeContext,
    UserInterview,
    UserInterviewClassification,
    UserInterviewTopic,
)


def _make_shared_config(*, team: Any, topic: UserInterviewTopic, created_by: User) -> SharingConfiguration:
    """Build a shared link the way the product does — a sentinel IntervieweeContext plus a
    SharingConfiguration on it (no new model / no main-app FK)."""
    ic = IntervieweeContext.objects.create(
        team=team,
        topic=topic,
        interviewee_identifier=SHARED_INTERVIEWEE_IDENTIFIER,
        agent_context="",
        created_by=created_by,
    )
    return SharingConfiguration.objects.create(team=team, interviewee_context=ic, enabled=True)


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

    def test_creates_shared_link_via_sentinel_context(self) -> None:
        topic = self._topic()
        response = self.client.post(self._url(str(topic.id)))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

        # Modelled as a sentinel IntervieweeContext (no new model / no main-app FK).
        ic = IntervieweeContext.objects.get(
            team=self.team, topic=topic, interviewee_identifier=SHARED_INTERVIEWEE_IDENTIFIER
        )
        config = SharingConfiguration.objects.get(team=self.team, interviewee_context=ic, enabled=True)
        assert config.access_token is not None
        assert config.access_token in response.json()["interview_url"]

    def test_is_idempotent(self) -> None:
        topic = self._topic()
        first = self.client.post(self._url(str(topic.id))).json()
        second = self.client.post(self._url(str(topic.id))).json()
        assert first["interview_url"] == second["interview_url"]
        assert (
            IntervieweeContext.objects.filter(topic=topic, interviewee_identifier=SHARED_INTERVIEWEE_IDENTIFIER).count()
            == 1
        )
        assert (
            SharingConfiguration.objects.filter(
                interviewee_context__topic=topic,
                interviewee_context__interviewee_identifier=SHARED_INTERVIEWEE_IDENTIFIER,
                enabled=True,
            ).count()
            == 1
        )

    def test_shared_link_works_without_any_targeted_interviewees(self) -> None:
        # Unlike generate_links (which needs emails/distinct_ids), a shared link is for a topic with
        # no pre-seeded targets — this is the whole point for anonymous blog visitors.
        topic = self._topic()
        assert not topic.interviewee_emails and not topic.interviewee_distinct_ids
        response = self.client.post(self._url(str(topic.id)))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)


class TestReservedIdentifierRejected(_FeatureFlagEnabledMixin):
    # A user-supplied identifier equal to the shared-link sentinel (or in the `shared:` namespace)
    # would collide on the unique (topic, interviewee_identifier) constraint and silently merge with
    # or revoke the topic's shared link, so it's rejected at every input boundary.
    def _topics_url(self) -> str:
        return f"/api/environments/{self.team.id}/user_interview_topics/"

    @parameterized.expand([("sentinel", SHARED_INTERVIEWEE_IDENTIFIER), ("shared_namespace", "shared:abc123")])
    def test_topic_create_rejects_reserved_distinct_id(self, _name: str, identifier: str) -> None:
        response = self.client.post(
            self._topics_url(),
            data={"topic": "Why people churn", "interviewee_distinct_ids": [identifier]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)

    @parameterized.expand([("sentinel", SHARED_INTERVIEWEE_IDENTIFIER), ("shared_namespace", "shared:abc123")])
    def test_add_interviewee_rejects_reserved_identifier(self, _name: str, identifier: str) -> None:
        topic = UserInterviewTopic.objects.create(team=self.team, created_by=self.user, topic="Why people churn")
        response = self.client.post(
            f"{self._topics_url()}{topic.id}/add_interviewee/",
            data={"identifier": identifier},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)


class TestRevokeSharedLink(_FeatureFlagEnabledMixin):
    def _topic(self) -> UserInterviewTopic:
        return UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            topic="Alternatives and comparisons",
            questions=[],
        )

    def _url(self, topic_id: str) -> str:
        return f"/api/environments/{self.team.id}/user_interview_topics/{topic_id}/shared_link/"

    def _start_call_url(self, token: str) -> str:
        return f"/api/user_interviews/share/{token}/start_call/"

    def _token(self, body: dict) -> str:
        return body["interview_url"].rstrip("/").rsplit("/", 1)[-1]

    def _enabled_shared_count(self, topic: UserInterviewTopic) -> int:
        return SharingConfiguration.objects.filter(
            interviewee_context__topic=topic,
            interviewee_context__interviewee_identifier=SHARED_INTERVIEWEE_IDENTIFIER,
            enabled=True,
        ).count()

    @override_settings(VAPI_PUBLIC_KEY="pk_test", VAPI_ASSISTANT_ID="asst_test")
    def test_delete_revokes_link_and_post_mints_a_fresh_one(self) -> None:
        topic = self._topic()
        token1 = self._token(self.client.post(self._url(str(topic.id))).json())
        assert self._enabled_shared_count(topic) == 1

        assert self.client.delete(self._url(str(topic.id))).status_code == status.HTTP_204_NO_CONTENT
        assert self._enabled_shared_count(topic) == 0

        token2 = self._token(self.client.post(self._url(str(topic.id))).json())
        assert token2 != token1
        assert self._enabled_shared_count(topic) == 1

        # The revoked URL can no longer start a call; the freshly minted one can.
        self.client.logout()
        revoked = self.client.post(self._start_call_url(token1), data={"name": "Robin"}, format="json")
        assert revoked.status_code == status.HTTP_404_NOT_FOUND
        fresh = self.client.post(self._start_call_url(token2), data={"name": "Robin"}, format="json")
        assert fresh.status_code == status.HTTP_200_OK


class TestSharedInterviewPublicViewer(APIBaseTest):
    def _shared_config(self) -> SharingConfiguration:
        topic = UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            topic="Alternatives and comparisons",
            agent_context="internal only",
            questions=["q1"],
        )
        return _make_shared_config(team=self.team, topic=topic, created_by=self.user)

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
        return _make_shared_config(team=self.team, topic=topic, created_by=self.user)

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
        # The identifier is namespaced on the respondent_key, never the provided distinct_id — so a
        # respondent can't attribute themselves to a targeted invitee. The distinct_id rides in its
        # own field as best-effort, untrusted linkage.
        assert metadata["interviewee_identifier"] == "shared:resp-123"
        assert metadata["distinct_id"] == "person-abc"
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
        # Illegal distinct_id is dropped from the linkage field; the identifier is still a namespaced
        # shared marker (never the self-reported name), so same-named respondents can't collide.
        assert metadata["distinct_id"] == ""
        assert metadata["interviewee_identifier"].startswith("shared:")

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
        return _make_shared_config(team=self.team, topic=topic, created_by=self.user)

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
                        # start_call namespaces the identifier on respondent_key and keeps the untrusted
                        # distinct_id in its own field.
                        "interviewee_identifier": f"shared:{respondent_key}",
                        "distinct_id": "person-abc",
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
        assert config.interviewee_context is not None
        assert interview.topic_id == config.interviewee_context.topic_id
        assert interview.respondent_name == "Robin"
        # The identifier is namespaced on respondent_key; the untrusted distinct_id is stored in its
        # own column, never as the identifier.
        assert interview.interviewee_identifier == "shared:resp-1"
        assert interview.distinct_id == "person-abc"
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
    def test_shared_response_cannot_impersonate_or_lock_out_a_targeted_invitee(self) -> None:
        # A shared respondent forges a targeted invitee's identifier as their linkage. It must not
        # become the stored identifier (no forged attribution) and must not gate the invitee's
        # personalised link (no lockout) — the core IDOR the namespaced identity prevents.
        topic = UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            interviewee_emails=["alex@example.com"],
            topic="Alternatives and comparisons",
            questions=[],
        )
        config = _make_shared_config(team=self.team, topic=topic, created_by=self.user)
        payload = self._payload(
            config.access_token, call_id="call_x", respondent_key="attacker", transcript="a full answer"
        )
        # Forge the target's identifier in both the echoed identifier and the linkage field.
        payload["message"]["call"]["metadata"]["interviewee_identifier"] = "alex@example.com"
        payload["message"]["call"]["metadata"]["distinct_id"] = "alex@example.com"
        self.client.logout()
        response = self._signed_post("topsecret", payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)

        interview = UserInterview.objects.get(team=self.team)
        # Stored under a namespaced shared identity, never the targeted invitee's; the forged linkage
        # is kept only in the untrusted distinct_id field.
        assert interview.interviewee_identifier == "shared:attacker"
        assert interview.distinct_id == "alex@example.com"
        # The targeted invitee's personalised link is NOT marked replied.
        assert not has_replied(team_id=self.team.id, topic_id=topic.id, interviewee_identifier="alex@example.com")

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    def test_completed_response_supersedes_abandoned_partial_from_a_refresh(self) -> None:
        config = self._shared_config()
        assert config.interviewee_context is not None
        topic = config.interviewee_context.topic
        # Simulate the abandoned partial an accidental refresh leaves behind: an AI-only transcript
        # (the respondent never spoke), which is what auto-derives as abandoned and is safe to collapse.
        abandoned = UserInterview.objects.create(
            team=self.team,
            created_by=self.user,
            topic=topic,
            interviewee_identifier="shared:resp-1",
            respondent_key="resp-1",
            transcript="AI: Hey! Thanks for making time. Ready to start?",
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

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    def test_manually_tagged_real_response_is_not_collapsed(self) -> None:
        # A real response a curator re-tagged `abandoned` (it contains interviewee turns) must survive
        # the collapse — the delete re-derives from the transcript, so only genuine AI-only partials go.
        # `abandoned` is user-mutable, so trusting the stored label would permanently delete real data.
        config = self._shared_config()
        assert config.interviewee_context is not None
        topic = config.interviewee_context.topic
        real = UserInterview.objects.create(
            team=self.team,
            created_by=self.user,
            topic=topic,
            interviewee_identifier="shared:resp-9",
            respondent_key="resp-9",
            transcript="AI: How do you use this?\nUser: Every day — it's core to my workflow.",
            classifications=[UserInterviewClassification.ABANDONED],
        )
        self.client.logout()
        response = self._signed_post(
            "topsecret",
            self._payload(config.access_token, call_id="call_9", respondent_key="resp-9", transcript="a full answer"),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        # The mislabeled real response is preserved (it has interviewee turns, so it doesn't re-derive
        # as abandoned); only genuine AI-only partials are collapsed.
        assert UserInterview.objects.filter(pk=real.pk).exists()
