"""Integration tests for social_signals DRF views and webhook."""

from unittest.mock import patch
from uuid import uuid4

from rest_framework import status

from posthog.test.base import APIBaseTest

from products.social_signals.backend.facade.enums import SourceKind
from products.social_signals.backend.models import Mention, MentionSource
from products.social_signals.backend.tests.conftest import SocialSignalsTeamScopedTestMixin

PRODUCT_DATABASES = {"default", "social_signals_db_writer", "social_signals_db_reader"}


class TestMentionSourceViewSet(SocialSignalsTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def test_create_is_idempotent(self):
        url = f"/api/projects/{self.team.id}/social_signals/sources/"
        first = self.client.post(url, {"kind": SourceKind.OCTOLENS.value}, format="json")
        second = self.client.post(url, {"kind": SourceKind.OCTOLENS.value}, format="json")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first.json()["id"], second.json()["id"])

    def test_list_returns_sources(self):
        MentionSource.objects.create(team_id=self.team.id, kind=SourceKind.OCTOLENS.value)
        response = self.client.get(f"/api/projects/{self.team.id}/social_signals/sources/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        # paginated or unpaginated — accept both shapes
        results = data["results"] if isinstance(data, dict) and "results" in data else data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["kind"], SourceKind.OCTOLENS.value)
        self.assertIn("ingest_token", results[0])

    def test_rotate_token(self):
        source = MentionSource.objects.create(team_id=self.team.id, kind=SourceKind.OCTOLENS.value)
        old = source.ingest_token

        response = self.client.post(
            f"/api/projects/{self.team.id}/social_signals/sources/{source.id}/rotate_token/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotEqual(response.json()["ingest_token"], old)

    def test_retrieve_not_found(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/social_signals/sources/{uuid4()}/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestMentionViewSet(SocialSignalsTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self):
        super().setUp()
        self.source = MentionSource.objects.create(team_id=self.team.id, kind=SourceKind.OCTOLENS.value)

    def test_list_returns_mentions(self):
        Mention.objects.create(
            team_id=self.team.id,
            source=self.source,
            external_id="m1",
            platform="x",
            mention_type="post",
            content="hello world",
        )
        response = self.client.get(f"/api/projects/{self.team.id}/social_signals/mentions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        results = data["results"] if isinstance(data, dict) and "results" in data else data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "hello world")

    def test_retrieve_not_found(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/social_signals/mentions/{uuid4()}/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestIngestWebhook(SocialSignalsTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self):
        super().setUp()
        self.source = MentionSource.objects.create(team_id=self.team.id, kind=SourceKind.OCTOLENS.value)

    @patch("products.social_signals.backend.tasks.tasks.analyze_mention_task.delay")
    def test_valid_token_ingests_mentions(self, _mock_delay):
        payload = {
            "mentions": [
                {"id": "wh-1", "platform": "x", "content": "Praise post"},
                {"id": "wh-2", "platform": "reddit", "content": "Question post"},
            ]
        }
        response = self.client.post(
            f"/api/social_signals/webhook/{self.source.ingest_token}/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"accepted": 2, "skipped": 0})
        self.assertEqual(Mention.objects.filter(source=self.source).count(), 2)

    @patch("products.social_signals.backend.tasks.tasks.analyze_mention_task.delay")
    def test_replay_dedupes(self, _mock_delay):
        payload = {"mentions": [{"id": "dup-1", "platform": "x", "content": "v1"}]}
        url = f"/api/social_signals/webhook/{self.source.ingest_token}/"

        first = self.client.post(url, payload, format="json")
        second = self.client.post(url, payload, format="json")

        self.assertEqual(first.json(), {"accepted": 1, "skipped": 0})
        self.assertEqual(second.json(), {"accepted": 0, "skipped": 1})

    def test_unknown_token_returns_404(self):
        response = self.client.post(
            "/api/social_signals/webhook/totally-bogus-token/",
            {"mentions": [{"id": "x", "platform": "x"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_disabled_source_returns_404(self):
        self.source.enabled = False
        self.source.save(update_fields=["enabled"])
        response = self.client.post(
            f"/api/social_signals/webhook/{self.source.ingest_token}/",
            {"mentions": [{"id": "x", "platform": "x"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
