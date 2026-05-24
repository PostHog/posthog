import io
import csv
import hmac
import json
import hashlib
import datetime
from typing import Any

import unittest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.test_sharing import mock_exporter_template
from posthog.models.sharing_configuration import SharingConfiguration

from products.user_interviews.backend.models import IntervieweeContext, UserInterview, UserInterviewTopic
from products.user_interviews.backend.presentation.views import UserInterviewTopicSerializer
from products.user_interviews.backend.presentation.webhooks import (
    DEFAULT_FIRST_MESSAGE_TEMPLATE,
    EMBEDDING_CONTENT_MAX_BYTES,
    FIRST_MESSAGE_PROMPT_NAME,
    _build_first_message,
    _resolve_first_message_template,
)


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

    def test_generate_links_rejects_topic_with_no_identifiers(self):
        topic = self._create_topic(interviewee_emails=[], interviewee_distinct_ids=[])
        response = self.client.post(self._generate_links_url(str(topic.id)))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def _generate_links_csv_url(self, topic_id: str) -> str:
        return f"/api/environments/{self.team.id}/user_interview_topics/{topic_id}/links_csv/"

    def test_generate_links_csv_returns_csv_with_expected_columns_and_rows(self):
        topic = self._create_topic()

        response = self.client.post(self._generate_links_csv_url(str(topic.id)))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn(".csv", response["Content-Disposition"])

        reader = csv.DictReader(io.StringIO(response.content.decode("utf-8")))
        self.assertEqual(
            reader.fieldnames,
            ["interviewee_identifier", "interviewee_email", "user_name", "interview_url"],
        )
        rows = list(reader)
        # One row per targeted interviewee (3 in the default _create_topic).
        self.assertEqual(len(rows), 3)
        # Email column is empty for distinct-id-only rows; URL column always populated.
        for row in rows:
            self.assertIn("/interview/", row["interview_url"])

    def test_generate_links_csv_rejects_topic_with_no_identifiers(self):
        topic = self._create_topic(interviewee_emails=[], interviewee_distinct_ids=[])
        response = self.client.post(self._generate_links_csv_url(str(topic.id)))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generate_links_csv_sanitizes_formula_injection_without_breaking_emails(self):
        topic = self._create_topic(
            interviewee_emails=["alex@example.com"],
            # Deliberately craft a malicious distinct ID starting with `=` — must be quoted.
            interviewee_distinct_ids=["=cmd|/c calc!A1"],
        )
        response = self.client.post(self._generate_links_csv_url(str(topic.id)))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

        body = response.content.decode("utf-8")
        # Plain email is untouched (first char is a letter, not a formula trigger).
        self.assertIn("alex@example.com", body)
        self.assertNotIn("'alex@example.com", body)
        # Formula-injection identifier is prefixed with a single quote.
        self.assertIn("'=cmd|/c calc!A1", body)

    def test_generate_links_csv_is_idempotent_with_existing_links(self):
        topic = self._create_topic(interviewee_emails=["alex@example.com"], interviewee_distinct_ids=[])
        # Materialize via the JSON endpoint first; the CSV endpoint must return the same access token.
        json_body = self.client.post(self._generate_links_url(str(topic.id))).json()
        expected_url = json_body[0]["interview_url"]

        csv_response = self.client.post(self._generate_links_csv_url(str(topic.id)))
        self.assertEqual(csv_response.status_code, status.HTTP_200_OK)
        self.assertIn(expected_url, csv_response.content.decode("utf-8"))
        self.assertEqual(SharingConfiguration.objects.filter(interviewee_context__topic=topic).count(), 1)


class TestUserInterviewTopicCreate(_FeatureFlagEnabledMixin):
    def _url(self) -> str:
        return f"/api/environments/{self.team.id}/user_interview_topics/"

    @parameterized.expand(
        [
            ("no_targeting", {}),
            ("empty_lists", {"interviewee_emails": [], "interviewee_distinct_ids": []}),
        ]
    )
    def test_rejects_topic_without_identifiers(self, _name: str, targeting: dict[str, Any]):
        payload = {"topic": "Why people churn", **targeting}
        response = self.client.post(self._url(), data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        body = response.json()
        candidates = body.get("non_field_errors") or [body.get("detail", "")]
        assert UserInterviewTopicSerializer.MISSING_TARGETING_ERROR in candidates, body

    @parameterized.expand(
        [
            ("emails_only", {"interviewee_emails": ["alex@example.com"]}),
            ("distinct_ids_only", {"interviewee_distinct_ids": ["distinct-abc"]}),
            (
                "both",
                {"interviewee_emails": ["alex@example.com"], "interviewee_distinct_ids": ["distinct-abc"]},
            ),
        ]
    )
    def test_accepts_topic_with_identifiers(self, _name: str, targeting: dict[str, Any]):
        payload = {"topic": "Why people churn", **targeting}
        response = self.client.post(self._url(), data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)


class TestUserInterviewTopicEdit(_FeatureFlagEnabledMixin):
    def _topic(self, **overrides) -> UserInterviewTopic:
        defaults: dict = {
            "team": self.team,
            "created_by": self.user,
            "interviewee_emails": ["alex@example.com"],
            "interviewee_distinct_ids": ["distinct-abc"],
            "topic": "Adoption",
            "agent_context": "ctx",
            "questions": ["q1"],
        }
        defaults.update(overrides)
        return UserInterviewTopic.objects.create(**defaults)

    def _detail_url(self, topic_id: str) -> str:
        return f"/api/environments/{self.team.id}/user_interview_topics/{topic_id}/"

    def _add_url(self, topic_id: str) -> str:
        return f"{self._detail_url(topic_id)}add_interviewee/"

    def _remove_url(self, topic_id: str) -> str:
        return f"{self._detail_url(topic_id)}remove_interviewee/"

    @parameterized.expand(
        [
            ("plain_email", "jordan@example.com", "interviewee_emails"),
            ("display_name_email", "Jordan Doe <jordan@example.com>", "interviewee_emails"),
            ("distinct_id", "distinct-xyz", "interviewee_distinct_ids"),
        ]
    )
    def test_add_interviewee_routes_to_correct_array(self, _name: str, identifier: str, expected_field: str):
        topic = self._topic()
        response = self.client.post(self._add_url(str(topic.id)), data={"identifier": identifier}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        topic.refresh_from_db()
        assert identifier in getattr(topic, expected_field), (identifier, expected_field, response.json())

    def test_add_interviewee_is_idempotent(self):
        topic = self._topic(interviewee_emails=[])
        first = self.client.post(self._add_url(str(topic.id)), data={"identifier": "alex@example.com"}, format="json")
        second = self.client.post(self._add_url(str(topic.id)), data={"identifier": "alex@example.com"}, format="json")
        self.assertEqual(first.status_code, status.HTTP_200_OK, first.content)
        self.assertEqual(second.status_code, status.HTTP_200_OK, second.content)
        topic.refresh_from_db()
        assert topic.interviewee_emails == ["alex@example.com"], topic.interviewee_emails

    def test_remove_interviewee_drops_from_both_arrays(self):
        topic = self._topic(
            interviewee_emails=["alex@example.com", "jordan@example.com"],
            interviewee_distinct_ids=["distinct-abc"],
        )
        response = self.client.post(
            self._remove_url(str(topic.id)), data={"identifier": "alex@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        topic.refresh_from_db()
        assert topic.interviewee_emails == ["jordan@example.com"], topic.interviewee_emails
        assert topic.interviewee_distinct_ids == ["distinct-abc"], topic.interviewee_distinct_ids

    def test_remove_interviewee_disables_active_sharing_configurations(self):
        topic = self._topic()
        ic = IntervieweeContext.objects.create(
            team=self.team,
            topic=topic,
            interviewee_identifier="alex@example.com",
            agent_context="",
            created_by=self.user,
        )
        share = SharingConfiguration.objects.create(team=self.team, interviewee_context=ic, enabled=True)
        self.client.post(self._remove_url(str(topic.id)), data={"identifier": "alex@example.com"}, format="json")
        share.refresh_from_db()
        assert share.enabled is False

    def test_remove_interviewee_is_noop_for_unknown_identifier(self):
        topic = self._topic()
        response = self.client.post(
            self._remove_url(str(topic.id)), data={"identifier": "ghost@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        topic.refresh_from_db()
        assert topic.interviewee_emails == ["alex@example.com"], topic.interviewee_emails

    def test_partial_update_changes_topic_text(self):
        topic = self._topic()
        response = self.client.patch(self._detail_url(str(topic.id)), data={"topic": "New angle"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        topic.refresh_from_db()
        assert topic.topic == "New angle"

    def test_partial_update_rejects_clearing_all_targeting(self):
        topic = self._topic()
        response = self.client.patch(
            self._detail_url(str(topic.id)),
            data={"interviewee_emails": [], "interviewee_distinct_ids": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_partial_update_revokes_shares_for_removed_identifiers(self):
        topic = self._topic(interviewee_emails=["alex@example.com", "jordan@example.com"])
        ic = IntervieweeContext.objects.create(
            team=self.team,
            topic=topic,
            interviewee_identifier="alex@example.com",
            agent_context="",
            created_by=self.user,
        )
        share = SharingConfiguration.objects.create(team=self.team, interviewee_context=ic, enabled=True)
        response = self.client.patch(
            self._detail_url(str(topic.id)),
            data={"interviewee_emails": ["jordan@example.com"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        share.refresh_from_db()
        assert share.enabled is False

    def test_remove_interviewee_revokes_shares_even_when_identifier_already_absent(self):
        topic = self._topic(interviewee_emails=["jordan@example.com"])
        ic = IntervieweeContext.objects.create(
            team=self.team,
            topic=topic,
            interviewee_identifier="alex@example.com",
            agent_context="",
            created_by=self.user,
        )
        share = SharingConfiguration.objects.create(team=self.team, interviewee_context=ic, enabled=True)
        response = self.client.post(
            self._remove_url(str(topic.id)), data={"identifier": "alex@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        share.refresh_from_db()
        assert share.enabled is False

    def test_add_interviewee_rejects_overlong_email_identifier(self):
        topic = self._topic()
        long_email = "a" * 250 + "@example.com"
        assert len(long_email) > 254
        response = self.client.post(self._add_url(str(topic.id)), data={"identifier": long_email}, format="json")
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


class TestBuildFirstMessage(unittest.TestCase):
    @parameterized.expand(
        [
            ("simple_name_and_topic", "Paul", "taxonomic filter search", ["Hey Paul!", "taxonomic filter search"]),
            ("dotted_local_part", "Cory S", "session replay adoption", ["Hey Cory S!", "session replay adoption"]),
            (
                "name_with_trailing_topic_whitespace",
                "Kim",
                "  feature flag rollout  ",
                ["Hey Kim!", "feature flag rollout"],
            ),
        ]
    )
    def test_includes_name_and_topic(self, _label: str, user_name: str, topic_text: str, expected_fragments: list[str]):
        message = _build_first_message(DEFAULT_FIRST_MESSAGE_TEMPLATE, user_name=user_name, topic_text=topic_text)
        for fragment in expected_fragments:
            assert fragment in message

    @parameterized.expand([("empty", ""), ("whitespace_only", "   ")])
    def test_falls_back_to_generic_topic_when_topic_empty(self, _label: str, topic_text: str):
        message = _build_first_message(DEFAULT_FIRST_MESSAGE_TEMPLATE, user_name="Sam", topic_text=topic_text)
        assert "Hey Sam!" in message
        assert "your experience" in message

    @parameterized.expand([("empty", ""), ("whitespace_only", "   ")])
    def test_falls_back_to_generic_greeting_when_user_name_empty(self, _label: str, user_name: str):
        message = _build_first_message(
            DEFAULT_FIRST_MESSAGE_TEMPLATE, user_name=user_name, topic_text="checkout funnel"
        )
        assert "Hey there!" in message
        assert "Hey !" not in message

    def test_collapses_internal_whitespace_in_topic(self):
        message = _build_first_message(
            DEFAULT_FIRST_MESSAGE_TEMPLATE, user_name="Sam", topic_text="multi\nline\n\ttopic"
        )
        assert "multi line topic" in message
        assert "\n" not in message

    def test_truncates_very_long_topic(self):
        long_topic = "x" * 500
        message = _build_first_message(DEFAULT_FIRST_MESSAGE_TEMPLATE, user_name="Sam", topic_text=long_topic)
        assert "x" * 200 in message
        assert "x" * 201 not in message

    def test_uses_custom_template_when_provided(self):
        custom = "Hi $user_name, today's topic: $topic_text."
        message = _build_first_message(custom, user_name="Paul", topic_text="onboarding")
        assert message == "Hi Paul, today's topic: onboarding."

    def test_falls_back_to_default_when_custom_template_missing_placeholder(self):
        broken = "Hi $nonsense, today is $missing_field."
        message = _build_first_message(broken, user_name="Paul", topic_text="onboarding")
        assert "Hey Paul!" in message
        assert "onboarding" in message

    def test_format_spec_in_template_is_treated_as_literal_text(self):
        # string.Template has no format-spec syntax, so an attacker cannot use
        # `{user_name:>10000000000}` to allocate gigabytes — `:` is just a character.
        attempted = "Hi $user_name, padded: {user_name:>10000000000}"
        message = _build_first_message(attempted, user_name="Paul", topic_text="onboarding")
        assert "Hi Paul" in message
        assert len(message) <= 1000

    def test_falls_back_to_default_when_rendered_message_exceeds_cap(self):
        huge = "Hi $user_name! " + ("x" * 2000)
        message = _build_first_message(huge, user_name="Paul", topic_text="onboarding")
        assert "Hey Paul!" in message
        assert "onboarding" in message
        assert len(message) <= 1000

    def test_return_value_is_always_bounded_even_with_long_user_name(self):
        message = _build_first_message(DEFAULT_FIRST_MESSAGE_TEMPLATE, user_name="x" * 5000, topic_text="onboarding")
        assert len(message) <= 1000


class TestResolveFirstMessageTemplate(APIBaseTest):
    def test_returns_default_when_no_prompt_configured(self):
        template = _resolve_first_message_template(self.team)
        assert template == DEFAULT_FIRST_MESSAGE_TEMPLATE

    def test_returns_team_override_when_prompt_published(self):
        from posthog.models.llm_prompt import LLMPrompt

        LLMPrompt.objects.create(
            team=self.team,
            name=FIRST_MESSAGE_PROMPT_NAME,
            prompt="Hey $user_name! Quick chat about $topic_text?",
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        template = _resolve_first_message_template(self.team)
        assert template == "Hey $user_name! Quick chat about $topic_text?"

    def test_returns_default_when_published_prompt_is_empty(self):
        from posthog.models.llm_prompt import LLMPrompt

        LLMPrompt.objects.create(
            team=self.team,
            name=FIRST_MESSAGE_PROMPT_NAME,
            prompt="   ",
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        template = _resolve_first_message_template(self.team)
        assert template == DEFAULT_FIRST_MESSAGE_TEMPLATE


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
    def test_returns_scoped_server_messages(self):
        share = self._create_share()
        self.client.logout()
        response = self.client.post(f"/api/user_interviews/share/{share.access_token}/start_call/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        overrides = response.json()["assistant_overrides"]
        # Scoped to the two lifecycle events we act on — keeps Vapi from sending
        # speech-update / conversation-update / etc that we'd just ignore.
        self.assertEqual(overrides["serverMessages"], ["status-update", "end-of-call-report"])

    @override_settings(VAPI_PUBLIC_KEY="pk_test", VAPI_ASSISTANT_ID="asst_test")
    def test_returns_personalised_first_message(self):
        share = self._create_share()
        self.client.logout()
        response = self.client.post(f"/api/user_interviews/share/{share.access_token}/start_call/")
        assert response.status_code == status.HTTP_200_OK, response.content
        first_message = response.json()["assistant_overrides"]["firstMessage"]
        assert "Hey Alex!" in first_message
        assert "Replay adoption" in first_message

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

    def _end_of_call_payload(
        self, access_token: str | None, call_id: str = "call_abc", metadata_path: str = "top"
    ) -> dict:
        # Vapi can surface our `assistant_overrides.metadata` either at `call.metadata`
        # (top-level) or `call.assistantOverrides.metadata` (nested). The handler must
        # find it in either path; parameterised tests cover both.
        if metadata_path == "nested":
            call: dict[str, Any] = {
                "id": call_id,
                "assistantOverrides": {"metadata": {"sharing_access_token": access_token}},
                "duration": 120,
            }
        else:
            call = {
                "id": call_id,
                "metadata": {"sharing_access_token": access_token},
                "duration": 120,
            }
        return {
            "message": {
                "type": "end-of-call-report",
                "call": call,
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

    @parameterized.expand([("top",), ("nested",)])
    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    def test_webhook_creates_user_interview(self, metadata_path: str):
        share = self._create_share()
        self.client.logout()
        response = self._signed_post(
            "topsecret",
            self._end_of_call_payload(share.access_token, metadata_path=metadata_path),
        )
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
            HTTP_X_VAPI_SIGNATURE="a" * 64,  # right shape, wrong value
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @parameterized.expand(
        [
            ("missing", None),
            ("empty", ""),
            ("too_short", "abc"),
            ("non_hex", "z" * 64),
            ("uppercase", "A" * 64),
        ]
    )
    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    def test_webhook_rejects_malformed_signature_pre_hmac(self, _name: str, value: Any):
        share = self._create_share()
        self.client.logout()
        kwargs: dict[str, Any] = {
            "data": self._end_of_call_payload(share.access_token),
            "content_type": "application/json",
        }
        if value is not None:
            kwargs["HTTP_X_VAPI_SIGNATURE"] = value
        response = self.client.post("/api/user_interviews/vapi_webhook/", **kwargs)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    def test_webhook_ignores_unknown_message_types(self):
        self.client.logout()
        response = self._signed_post("topsecret", {"message": {"type": "speech-update"}})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "ignored")

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    @patch("products.user_interviews.backend.presentation.webhooks.posthoganalytics.capture")
    def test_webhook_status_update_in_progress_captures_started_event(self, mock_capture):
        share = self._create_share()
        self.client.logout()
        response = self._signed_post(
            "topsecret",
            {
                "message": {
                    "type": "status-update",
                    "status": "in-progress",
                    "call": {"id": "call_xyz", "metadata": {"sharing_access_token": share.access_token}},
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_capture.assert_called_once()
        kwargs = mock_capture.call_args.kwargs
        self.assertEqual(kwargs["event"], "user_interview_conversation_started")
        # distinct_id is intentionally an opaque interviewee_context UUID — not the
        # email — so these feature-usage events don't create person profiles for the
        # third-party interviewees.
        assert share.interviewee_context is not None
        self.assertEqual(kwargs["distinct_id"], f"user_interview:{share.interviewee_context.id}")
        self.assertNotIn("alex@example.com", kwargs["distinct_id"])
        self.assertEqual(kwargs["properties"]["call_id"], "call_xyz")

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    @patch("products.user_interviews.backend.presentation.webhooks.posthoganalytics.capture")
    def test_webhook_status_update_duplicate_in_progress_emits_same_insert_id(self, mock_capture):
        # Vapi re-fires `status-update / in-progress` on transient drops + warm-transfer flows.
        # We tag every started event with `$insert_id` = "user_interview_conversation_started:<call_id>"
        # so PostHog dedupes the second delivery at ingest. Both captures fire here (we don't
        # de-dup client-side); the contract is that they share an insert_id.
        share = self._create_share()
        self.client.logout()
        payload = {
            "message": {
                "type": "status-update",
                "status": "in-progress",
                "call": {"id": "call_xyz", "metadata": {"sharing_access_token": share.access_token}},
            }
        }
        self._signed_post("topsecret", payload)
        self._signed_post("topsecret", payload)
        self.assertEqual(mock_capture.call_count, 2)
        for call in mock_capture.call_args_list:
            self.assertEqual(call.kwargs["properties"]["$insert_id"], "user_interview_conversation_started:call_xyz")

    @parameterized.expand([("ringing",), ("ended",), ("queued",), ("forwarding",), ("scheduled",)])
    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    @patch("products.user_interviews.backend.presentation.webhooks.posthoganalytics.capture")
    def test_webhook_status_update_other_statuses_do_not_capture(self, call_status: str, mock_capture):
        share = self._create_share()
        self.client.logout()
        response = self._signed_post(
            "topsecret",
            {
                "message": {
                    "type": "status-update",
                    "status": call_status,
                    "call": {"id": "call_xyz", "metadata": {"sharing_access_token": share.access_token}},
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_capture.assert_not_called()

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    @patch("products.user_interviews.backend.presentation.webhooks.posthoganalytics.capture")
    def test_webhook_end_of_call_report_captures_ended_event(self, mock_capture):
        share = self._create_share()
        self.client.logout()
        response = self._signed_post("topsecret", self._end_of_call_payload(share.access_token))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        mock_capture.assert_called_once()
        kwargs = mock_capture.call_args.kwargs
        self.assertEqual(kwargs["event"], "user_interview_conversation_ended")
        assert share.interviewee_context is not None
        self.assertEqual(kwargs["distinct_id"], f"user_interview:{share.interviewee_context.id}")
        self.assertNotIn("alex@example.com", kwargs["distinct_id"])
        self.assertTrue(kwargs["properties"]["had_transcript"])
        self.assertTrue(kwargs["properties"]["had_summary"])

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

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    @patch("products.user_interviews.backend.presentation.webhooks.emit_embedding_request")
    def test_webhook_emits_transcript_and_summary_embeddings(self, mock_emit):
        share = self._create_share()
        self.client.logout()
        with self.captureOnCommitCallbacks(execute=True):
            response = self._signed_post("topsecret", self._end_of_call_payload(share.access_token))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)

        interview = UserInterview.objects.get(team=self.team)
        assert share.interviewee_context is not None
        topic = share.interviewee_context.topic

        emitted = {kwargs["document_type"]: kwargs for _, kwargs in mock_emit.call_args_list}
        self.assertEqual(set(emitted), {"transcript", "summary"})

        for document_type, expected_content in (("transcript", "Hi! ..."), ("summary", "User talked about replay.")):
            kwargs = emitted[document_type]
            self.assertEqual(kwargs["content"], expected_content)
            self.assertEqual(kwargs["team_id"], self.team.id)
            self.assertEqual(kwargs["product"], "user_interviews")
            self.assertEqual(kwargs["rendering"], "plain")
            self.assertEqual(kwargs["document_id"], str(interview.id))
            self.assertEqual(kwargs["models"], ["text-embedding-3-small-1536", "text-embedding-3-large-3072"])
            self.assertEqual(
                kwargs["metadata"],
                {"topic_id": str(topic.id), "interviewee_identifier": "alex@example.com"},
            )

    @parameterized.expand(
        [
            ("transcript_only", "Hi! ...", "", {"transcript"}),
            ("summary_only", "", "User talked about replay.", {"summary"}),
            ("both_empty", "", "", set()),
        ]
    )
    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    @patch("products.user_interviews.backend.presentation.webhooks.emit_embedding_request")
    def test_webhook_skips_empty_content(self, _name, transcript, summary, expected_types, mock_emit):
        share = self._create_share()
        self.client.logout()
        payload = self._end_of_call_payload(share.access_token)
        payload["message"]["transcript"] = transcript
        payload["message"]["summary"] = summary

        with self.captureOnCommitCallbacks(execute=True):
            response = self._signed_post("topsecret", payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)

        emitted_types = {kwargs["document_type"] for _, kwargs in mock_emit.call_args_list}
        self.assertEqual(emitted_types, expected_types)

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    @patch("products.user_interviews.backend.presentation.webhooks.emit_embedding_request")
    def test_webhook_does_not_re_emit_on_duplicate(self, mock_emit):
        share = self._create_share()
        self.client.logout()
        payload = self._end_of_call_payload(share.access_token, call_id="call_dup")

        with self.captureOnCommitCallbacks(execute=True):
            self._signed_post("topsecret", payload)
        first_emitted_types = {kwargs["document_type"] for _, kwargs in mock_emit.call_args_list}
        self.assertEqual(first_emitted_types, {"transcript", "summary"})
        first_call_count = mock_emit.call_count

        with self.captureOnCommitCallbacks(execute=True):
            second = self._signed_post("topsecret", payload)
        self.assertEqual(second.json()["status"], "duplicate")
        self.assertEqual(mock_emit.call_count, first_call_count)

    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    @patch(
        "products.user_interviews.backend.presentation.webhooks.emit_embedding_request",
        side_effect=RuntimeError("kafka down"),
    )
    def test_webhook_succeeds_when_embedding_emit_fails(self, _mock_emit):
        share = self._create_share()
        self.client.logout()
        with self.captureOnCommitCallbacks(execute=True):
            response = self._signed_post("topsecret", self._end_of_call_payload(share.access_token))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertEqual(UserInterview.objects.filter(team=self.team).count(), 1)

    @parameterized.expand(
        [
            ("transcript_only", True, False),
            ("summary_only", False, True),
            ("both", True, True),
        ]
    )
    @override_settings(VAPI_WEBHOOK_SECRET="topsecret")
    @patch("products.user_interviews.backend.presentation.webhooks.emit_embedding_request")
    def test_webhook_truncates_oversized_content_before_emit(
        self, _name, oversize_transcript, oversize_summary, mock_emit
    ):
        share = self._create_share()
        self.client.logout()
        payload = self._end_of_call_payload(share.access_token)
        original_transcript = payload["message"]["transcript"]
        original_summary = payload["message"]["summary"]
        if oversize_transcript:
            payload["message"]["transcript"] = "a" * (EMBEDDING_CONTENT_MAX_BYTES + 1000)
        if oversize_summary:
            payload["message"]["summary"] = "b" * (EMBEDDING_CONTENT_MAX_BYTES + 500)

        with self.captureOnCommitCallbacks(execute=True):
            response = self._signed_post("topsecret", payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)

        emitted = {kwargs["document_type"]: kwargs for _, kwargs in mock_emit.call_args_list}

        for document_type, was_oversized, original in (
            ("transcript", oversize_transcript, original_transcript),
            ("summary", oversize_summary, original_summary),
        ):
            content_bytes = emitted[document_type]["content"].encode("utf-8")
            if was_oversized:
                self.assertEqual(len(content_bytes), EMBEDDING_CONTENT_MAX_BYTES)
            else:
                self.assertEqual(emitted[document_type]["content"], original)


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
            patch("products.user_interviews.backend.presentation.views.EmailMessage") as mock_message_cls,
            patch("products.user_interviews.backend.presentation.views.is_email_available", return_value=True),
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
            patch("products.user_interviews.backend.presentation.views.EmailMessage") as mock_message_cls,
            patch("products.user_interviews.backend.presentation.views.is_email_available", return_value=True),
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
            patch("products.user_interviews.backend.presentation.views.EmailMessage") as mock_message_cls,
            patch("products.user_interviews.backend.presentation.views.is_email_available", return_value=True),
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
        with patch("products.user_interviews.backend.presentation.views.is_email_available", return_value=False):
            response = self.client.post(self._url(str(topic.id)), data={}, format="json")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_send_invites_400_when_topic_has_no_identifiers(self):
        topic = self._create_topic(interviewee_emails=[], interviewee_distinct_ids=[])
        with patch("products.user_interviews.backend.presentation.views.is_email_available", return_value=True):
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
            patch("products.user_interviews.backend.presentation.views.EmailMessage", FlakyEmail),
            patch("products.user_interviews.backend.presentation.views.is_email_available", return_value=True),
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
