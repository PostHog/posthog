from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.user_interviews.backend.models import IntervieweeContext, UserInterviewTopic
from products.user_interviews.backend.presentation.views import BULK_INTERVIEWEE_CONTEXT_MAX_ITEMS


class _FeatureFlagEnabledMixin(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestIntervieweeContextBulkCreate(_FeatureFlagEnabledMixin):
    def _create_topic(self, **overrides: Any) -> UserInterviewTopic:
        defaults: dict = {
            "team": self.team,
            "created_by": self.user,
            "interviewee_emails": [],
            "interviewee_distinct_ids": [],
            "topic": "MCP-only insight creators",
        }
        defaults.update(overrides)
        return UserInterviewTopic.objects.create(**defaults)

    def _bulk_url(self, topic_id: str) -> str:
        return f"/api/environments/{self.team.id}/user_interview_topics/{topic_id}/interviewees/bulk/"

    def _item(self, identifier: str, context: str = "ctx") -> dict[str, str]:
        return {"interviewee_identifier": identifier, "agent_context": context}

    def test_bulk_create_inserts_all_new_rows(self):
        topic = self._create_topic()
        items = [self._item(f"user{i}@example.com", f"context {i}") for i in range(3)]

        response = self.client.post(self._bulk_url(str(topic.id)), {"items": items}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {
            "inserted_count": 3,
            "skipped_count": 0,
            "skipped_identifiers": [],
        }
        assert IntervieweeContext.objects.filter(topic=topic).count() == 3

    def test_bulk_create_skips_existing_rows(self):
        topic = self._create_topic()
        IntervieweeContext.objects.create(
            team=self.team,
            topic=topic,
            interviewee_identifier="existing@example.com",
            agent_context="existing context",
            created_by=self.user,
        )
        items = [
            self._item("existing@example.com", "would-be-overwritten"),
            self._item("new@example.com", "new context"),
        ]

        response = self.client.post(self._bulk_url(str(topic.id)), {"items": items}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {
            "inserted_count": 1,
            "skipped_count": 1,
            "skipped_identifiers": ["existing@example.com"],
        }
        existing = IntervieweeContext.objects.get(topic=topic, interviewee_identifier="existing@example.com")
        assert existing.agent_context == "existing context"
        assert IntervieweeContext.objects.filter(topic=topic).count() == 2

    def test_bulk_create_rejects_unknown_topic(self):
        response = self.client.post(self._bulk_url(str(uuid4())), {"items": [self._item("a@b.com")]}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content

    def test_bulk_create_rejects_topic_belonging_to_another_team(self):
        other_team = self.organization.teams.create(name="other-team")
        other_topic = UserInterviewTopic.objects.create(
            team=other_team,
            created_by=self.user,
            topic="other team topic",
        )

        response = self.client.post(
            self._bulk_url(str(other_topic.id)),
            {"items": [self._item("a@b.com")]},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
        assert IntervieweeContext.objects.filter(topic=other_topic).count() == 0

    @parameterized.expand(
        [
            ("empty_items", {"items": []}),
            ("missing_items", {}),
            ("missing_identifier", {"items": [{"agent_context": "x"}]}),
            ("missing_context", {"items": [{"interviewee_identifier": "a@b.com"}]}),
            (
                "duplicate_identifiers_in_batch",
                {"items": [{"interviewee_identifier": "a@b.com", "agent_context": "x"}] * 2},
            ),
            (
                "identifier_too_long",
                {"items": [{"interviewee_identifier": "a" * 401, "agent_context": "x"}]},
            ),
            (
                "context_too_long",
                {"items": [{"interviewee_identifier": "a@b.com", "agent_context": "x" * 10_001}]},
            ),
        ]
    )
    def test_bulk_create_validation_errors(self, _name: str, body: dict[str, Any]):
        topic = self._create_topic()

        response = self.client.post(self._bulk_url(str(topic.id)), body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert IntervieweeContext.objects.filter(topic=topic).count() == 0

    def test_bulk_create_rejects_oversized_batch(self):
        topic = self._create_topic()
        items = [self._item(f"u{i}@example.com") for i in range(BULK_INTERVIEWEE_CONTEXT_MAX_ITEMS + 1)]

        response = self.client.post(self._bulk_url(str(topic.id)), {"items": items}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert IntervieweeContext.objects.filter(topic=topic).count() == 0

    def test_bulk_create_accepts_max_size_batch(self):
        topic = self._create_topic()
        items = [self._item(f"u{i}@example.com") for i in range(BULK_INTERVIEWEE_CONTEXT_MAX_ITEMS)]

        response = self.client.post(self._bulk_url(str(topic.id)), {"items": items}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["inserted_count"] == BULK_INTERVIEWEE_CONTEXT_MAX_ITEMS
        assert body["skipped_count"] == 0
        assert IntervieweeContext.objects.filter(topic=topic).count() == BULK_INTERVIEWEE_CONTEXT_MAX_ITEMS
