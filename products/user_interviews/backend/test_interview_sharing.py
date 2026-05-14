import hmac
import json
import hashlib
import datetime
from typing import Any

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from rest_framework import status

from posthog.api.test.test_sharing import mock_exporter_template
from posthog.models.sharing_configuration import SharingConfiguration

from products.user_interviews.backend.models import IntervieweeContext, UserInterview, UserInterviewTopic


class _FeatureFlagEnabledMixin(APIBaseTest):
    """Auto-mock `posthoganalytics.feature_enabled` so flag-gated viewsets accept calls in tests."""

    def setUp(self) -> None:
        super().setUp()
        patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestGenerateInterviewLinks(_FeatureFlagEnabledMixin):
    def _create_topic(self, **overrides) -> UserInterviewTopic:
        defaults: dict = {
            "team": self.team,
            "created_by": self.user,
            "interviewee_emails": ["Alex <alex@example.com>", "jordan@example.com"],
            "interviewee_distinct_ids": ["distinct-abc"],
            "topic": "Session replay adoption",
            "agent_context": "Researching adoption of session replay",
            "questions": ["What blocks adoption?"],
        }
        defaults.update(overrides)
        return UserInterviewTopic.objects.create(**defaults)

    def _generate_links_url(self, topic_id: str) -> str:
        return f"/api/environments/{self.team.id}/user_interview_topics/{topic_id}/generate_links/"

    def test_generate_links_materializes_contexts_and_sharing_configs(self):
        topic = self._create_topic()

        response = self.client.post(self._generate_links_url(str(topic.id)))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        identifiers = sorted(link["interviewee_identifier"] for link in body)
        self.assertEqual(
            identifiers,
            sorted(["Alex <alex@example.com>", "jordan@example.com", "distinct-abc"]),
        )

        for link in body:
            self.assertTrue(link["interview_url"].endswith(link["interview_url"].rsplit("/", 1)[-1]))
            self.assertIn("/interview/", link["interview_url"])

        self.assertEqual(IntervieweeContext.objects.filter(topic=topic).count(), 3)
        self.assertEqual(
            SharingConfiguration.objects.filter(team=self.team, interviewee_context__topic=topic, enabled=True).count(),
            3,
        )

    def test_generate_links_is_idempotent(self):
        topic = self._create_topic(interviewee_emails=["alex@example.com"], interviewee_distinct_ids=[])
        first = self.client.post(self._generate_links_url(str(topic.id))).json()
        second = self.client.post(self._generate_links_url(str(topic.id))).json()
        self.assertEqual(first[0]["interview_url"], second[0]["interview_url"])
        self.assertEqual(IntervieweeContext.objects.filter(topic=topic).count(), 1)
        self.assertEqual(SharingConfiguration.objects.filter(interviewee_context__topic=topic).count(), 1)

    def test_generate_links_preserves_existing_personal_context(self):
        topic = self._create_topic(interviewee_emails=["alex@example.com"], interviewee_distinct_ids=[])
        IntervieweeContext.objects.create(
            team=self.team,
            topic=topic,
            interviewee_identifier="alex@example.com",
            agent_context="heavy user, churned last quarter",
            created_by=self.user,
        )
        response = self.client.post(self._generate_links_url(str(topic.id)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        link = response.json()[0]
        self.assertIn("heavy user, churned last quarter", link["agent_context"])
        self.assertIn("Researching adoption of session replay", link["agent_context"])

    def test_generate_links_rejects_topic_with_only_cohort(self):
        topic = self._create_topic(
            interviewee_emails=[],
            interviewee_distinct_ids=[],
            interviewee_cohort=123,
        )
        response = self.client.post(self._generate_links_url(str(topic.id)))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestInterviewPublicViewer(APIBaseTest):
    def _create_share(self) -> SharingConfiguration:
        topic = UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            interviewee_emails=["alex@example.com"],
            topic="Session replay adoption",
            agent_context="adoption research",
            questions=["q1"],
        )
        ic = IntervieweeContext.objects.create(
            team=self.team,
            topic=topic,
            interviewee_identifier="alex@example.com",
            agent_context="heavy user",
            created_by=self.user,
        )
        return SharingConfiguration.objects.create(team=self.team, interviewee_context=ic, enabled=True)

    @override_settings(VAPI_PUBLIC_KEY="pk_test", VAPI_ASSISTANT_ID="asst_test")
    @mock_exporter_template
    def test_public_viewer_renders_interview_payload_without_agent_context(self):
        share = self._create_share()
        self.client.logout()
        response = self.client.get(f"/interview/{share.access_token}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.content.decode()
        # The exporter payload is JSON-encoded inside a JSON script tag, so escaped keys appear.
        # We render: type=interview, topic name, access token. We do NOT render the agent
        # context, the questions, or the Vapi credentials — those live behind /start_call/.
        self.assertIn("interview", body)
        self.assertIn(share.access_token, body)
        self.assertIn("Session replay adoption", body)
        self.assertNotIn("heavy user", body)
        self.assertNotIn("adoption research", body)
        self.assertNotIn("pk_test", body)
        self.assertNotIn("asst_test", body)

    def test_public_viewer_rejects_disabled_share(self):
        share = self._create_share()
        share.enabled = False
        share.save()
        self.client.logout()
        response = self.client.get(f"/interview/{share.access_token}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestInterviewStartCall(APIBaseTest):
    def _create_share(self) -> SharingConfiguration:
        topic = UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            interviewee_emails=["alex@example.com"],
            topic="Replay adoption",
            agent_context="adoption research",
            questions=["What blocks you?"],
        )
        ic = IntervieweeContext.objects.create(
            team=self.team,
            topic=topic,
            interviewee_identifier="alex@example.com",
            agent_context="heavy user, churned last quarter",
            created_by=self.user,
        )
        return SharingConfiguration.objects.create(team=self.team, interviewee_context=ic, enabled=True)

    @override_settings(VAPI_PUBLIC_KEY="pk_test", VAPI_ASSISTANT_ID="asst_test")
    def test_returns_merged_assistant_overrides(self):
        share = self._create_share()
        self.client.logout()
        response = self.client.post(f"/api/user_interviews/share/{share.access_token}/start_call/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertEqual(body["public_key"], "pk_test")
        self.assertEqual(body["assistant_id"], "asst_test")
        overrides = body["assistant_overrides"]
        # Merged agent_context combines topic-level and per-person notes.
        self.assertIn("adoption research", overrides["variableValues"]["agent_context"])
        self.assertIn("heavy user, churned last quarter", overrides["variableValues"]["agent_context"])
        self.assertEqual(overrides["metadata"]["sharing_access_token"], share.access_token)
        self.assertEqual(overrides["metadata"]["interviewee_identifier"], "alex@example.com")

    @override_settings(VAPI_PUBLIC_KEY="pk_test", VAPI_ASSISTANT_ID="asst_test")
    def test_rejects_disabled_share(self):
        share = self._create_share()
        share.enabled = False
        share.save()
        self.client.logout()
        response = self.client.post(f"/api/user_interviews/share/{share.access_token}/start_call/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(VAPI_PUBLIC_KEY="", VAPI_ASSISTANT_ID="")
    def test_503_when_vapi_unconfigured(self):
        share = self._create_share()
        self.client.logout()
        response = self.client.post(f"/api/user_interviews/share/{share.access_token}/start_call/")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    @override_settings(VAPI_PUBLIC_KEY="pk_test", VAPI_ASSISTANT_ID="asst_test")
    def test_returns_questions_as_json_not_python_repr(self):
        share = self._create_share()
        self.client.logout()
        response = self.client.post(f"/api/user_interviews/share/{share.access_token}/start_call/")
        questions_raw = response.json()["assistant_overrides"]["variableValues"]["questions"]
        # The Vapi assistant prompt receives this string verbatim; it must parse as JSON,
        # not Python repr (which would be `['What blocks you?']` with single quotes).
        self.assertEqual(json.loads(questions_raw), ["What blocks you?"])

    @override_settings(VAPI_PUBLIC_KEY="pk_test", VAPI_ASSISTANT_ID="asst_test")
    def test_rejects_when_org_disables_public_sharing(self):
        share = self._create_share()
        org = share.team.organization
        # Pretend the org has the enterprise security feature and has disabled public shares.
        org.available_product_features = [{"key": "organization_security_settings", "name": "Org security"}]
        org.allow_publicly_shared_resources = False
        org.save()
        self.client.logout()
        response = self.client.post(f"/api/user_interviews/share/{share.access_token}/start_call/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @freeze_time("2026-05-14 12:00:00")
    @override_settings(VAPI_PUBLIC_KEY="pk_test", VAPI_ASSISTANT_ID="asst_test")
    def test_rejects_expired_rotated_token(self):
        # Simulate the post-grace-period state of a rotated SharingConfiguration:
        # `expires_at` in the past, still `enabled=True`. The public viewer 404s on these,
        # and start_call must do the same — otherwise the rotated token is still valid here.
        share = self._create_share()
        share.expires_at = timezone.now() - datetime.timedelta(minutes=1)
        share.save()
        self.client.logout()
        response = self.client.post(f"/api/user_interviews/share/{share.access_token}/start_call/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestVapiWebhook(APIBaseTest):
    def _create_share(self) -> SharingConfiguration:
        topic = UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            interviewee_emails=["alex@example.com"],
            topic="Replay adoption",
            agent_context="ctx",
            questions=[],
        )
        ic = IntervieweeContext.objects.create(
            team=self.team,
            topic=topic,
            interviewee_identifier="alex@example.com",
            agent_context="",
            created_by=self.user,
        )
        return SharingConfiguration.objects.create(team=self.team, interviewee_context=ic, enabled=True)

    def _end_of_call_payload(self, access_token: str | None, call_id: str = "call_abc") -> dict:
        return {
            "message": {
                "type": "end-of-call-report",
                "call": {
                    "id": call_id,
                    "metadata": {"sharing_access_token": access_token},
                    "duration": 120,
                },
                "transcript": "Hi! ...",
                "summary": "User talked about replay.",
                "recording": {"url": "https://vapi.example/recording.mp3"},
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
    def test_webhook_creates_user_interview(self):
        share = self._create_share()
        self.client.logout()
        response = self._signed_post("topsecret", self._end_of_call_payload(share.access_token))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        interview = UserInterview.objects.get(team=self.team)
        assert share.interviewee_context is not None
        self.assertEqual(interview.topic, share.interviewee_context.topic)
        self.assertEqual(interview.interviewee_identifier, "alex@example.com")
        self.assertEqual(interview.recording_url, "https://vapi.example/recording.mp3")
        self.assertEqual(interview.transcript, "Hi! ...")

    @override_settings(VAPI_WEBHOOK_SECRET="")
    def test_webhook_fails_closed_when_secret_unset(self):
        share = self._create_share()
        self.client.logout()
        response = self.client.post(
            "/api/user_interviews/vapi_webhook/",
            data=self._end_of_call_payload(share.access_token),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(UserInterview.objects.count(), 0)

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    def test_webhook_rejects_unknown_token(self):
        self.client.logout()
        response = self._signed_post("topsecret", self._end_of_call_payload("does-not-exist"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    def test_webhook_requires_valid_signature(self):
        share = self._create_share()
        self.client.logout()
        response = self.client.post(
            "/api/user_interviews/vapi_webhook/",
            data=self._end_of_call_payload(share.access_token),
            content_type="application/json",
            HTTP_X_VAPI_SIGNATURE="wrong",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    def test_webhook_ignores_non_end_of_call_events(self):
        self.client.logout()
        response = self._signed_post("topsecret", {"message": {"type": "status-update"}})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "ignored")

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    def test_webhook_is_idempotent_on_call_id(self):
        share = self._create_share()
        self.client.logout()
        payload = self._end_of_call_payload(share.access_token, call_id="call_xyz")
        first = self._signed_post("topsecret", payload)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self._signed_post("topsecret", payload)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.json()["status"], "duplicate")
        self.assertEqual(first.json()["interview_id"], second.json()["interview_id"])
        self.assertEqual(UserInterview.objects.filter(team=self.team).count(), 1)


class TestSendInterviewInvites(_FeatureFlagEnabledMixin):
    def _create_topic(self, **overrides) -> UserInterviewTopic:
        defaults: dict = {
            "team": self.team,
            "created_by": self.user,
            "interviewee_emails": ["Alex <alex@example.com>", "jordan@example.com"],
            "interviewee_distinct_ids": ["distinct-no-email"],
            "topic": "Session replay adoption",
            "agent_context": "ctx",
            "questions": ["q1"],
        }
        defaults.update(overrides)
        return UserInterviewTopic.objects.create(**defaults)

    def _url(self, topic_id: str) -> str:
        return f"/api/environments/{self.team.id}/user_interview_topics/{topic_id}/send_invites/"

    def test_send_invites_emails_only_email_identifiers(self):
        topic = self._create_topic()

        with (
            patch("products.user_interviews.backend.api.EmailMessage") as mock_message_cls,
            patch("products.user_interviews.backend.api.is_email_available", return_value=True),
        ):
            mock_message = mock_message_cls.return_value
            response = self.client.post(self._url(str(topic.id)), data={"send_async": False}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        results = response.json()
        sent = sorted(r["interviewee_identifier"] for r in results if r["sent"])
        skipped = [r for r in results if not r["sent"]]
        self.assertEqual(sent, sorted(["Alex <alex@example.com>", "jordan@example.com"]))
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["interviewee_identifier"], "distinct-no-email")
        self.assertEqual(skipped[0]["reason"], "not_an_email")

        # Two EmailMessage instances built, each with one recipient, sent synchronously.
        self.assertEqual(mock_message_cls.call_count, 2)
        self.assertEqual(mock_message.add_recipient.call_count, 2)
        mock_message.send.assert_called_with(send_async=False)

    def test_send_invites_defaults_subject_and_reply_to(self):
        topic = self._create_topic(interviewee_emails=["alex@example.com"], interviewee_distinct_ids=[])

        with (
            patch("products.user_interviews.backend.api.EmailMessage") as mock_message_cls,
            patch("products.user_interviews.backend.api.is_email_available", return_value=True),
        ):
            self.client.post(self._url(str(topic.id)), data={}, format="json")

        kwargs = mock_message_cls.call_args.kwargs
        self.assertIn("Session replay adoption", kwargs["subject"])
        self.assertEqual(kwargs["reply_to"], self.user.email)
        self.assertEqual(kwargs["template_name"], "interview_invite")
        self.assertEqual(kwargs["template_context"]["user_name"], "Alex")
        self.assertIn("/interview/", kwargs["template_context"]["interview_url"])

    def test_send_invites_uses_explicit_subject_and_reply_to(self):
        topic = self._create_topic(interviewee_emails=["alex@example.com"], interviewee_distinct_ids=[])

        with (
            patch("products.user_interviews.backend.api.EmailMessage") as mock_message_cls,
            patch("products.user_interviews.backend.api.is_email_available", return_value=True),
        ):
            self.client.post(
                self._url(str(topic.id)),
                data={"subject": "Hey, can we chat?", "reply_to": "research@posthog.com"},
                format="json",
            )

        kwargs = mock_message_cls.call_args.kwargs
        self.assertEqual(kwargs["subject"], "Hey, can we chat?")
        self.assertEqual(kwargs["reply_to"], "research@posthog.com")

    def test_send_invites_503_when_email_disabled(self):
        topic = self._create_topic()
        with patch("products.user_interviews.backend.api.is_email_available", return_value=False):
            response = self.client.post(self._url(str(topic.id)), data={}, format="json")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_send_invites_400_when_topic_only_has_cohort(self):
        topic = self._create_topic(interviewee_emails=[], interviewee_distinct_ids=[], interviewee_cohort=123)
        with patch("products.user_interviews.backend.api.is_email_available", return_value=True):
            response = self.client.post(self._url(str(topic.id)), data={}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_send_invites_marks_per_recipient_failures(self):
        topic = self._create_topic(
            interviewee_emails=["alex@example.com", "jordan@example.com"], interviewee_distinct_ids=[]
        )

        class FlakyEmail:
            """Stand-in for EmailMessage that raises on send for one specific recipient."""

            def __init__(self, **_kwargs):
                self.recipient_email = None

            def add_recipient(self, email, name=None, distinct_id=None):
                self.recipient_email = email

            def send(self, send_async=True):
                if self.recipient_email == "jordan@example.com":
                    raise RuntimeError("smtp down")

        with (
            patch("products.user_interviews.backend.api.EmailMessage", FlakyEmail),
            patch("products.user_interviews.backend.api.is_email_available", return_value=True),
        ):
            response = self.client.post(self._url(str(topic.id)), data={"send_async": False}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_id = {r["interviewee_identifier"]: r for r in response.json()}
        self.assertTrue(by_id["alex@example.com"]["sent"])
        self.assertFalse(by_id["jordan@example.com"]["sent"])
        self.assertTrue(by_id["jordan@example.com"]["reason"].startswith("error:"))


class TestSharingConfigurationCanAccess(APIBaseTest):
    def test_can_access_interviewee_context(self):
        topic = UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            interviewee_emails=["alex@example.com"],
            topic="t",
        )
        ic = IntervieweeContext.objects.create(
            team=self.team,
            topic=topic,
            interviewee_identifier="alex@example.com",
            agent_context="",
            created_by=self.user,
        )
        share = SharingConfiguration.objects.create(team=self.team, interviewee_context=ic, enabled=True)
        self.assertTrue(share.can_access_object(ic))
