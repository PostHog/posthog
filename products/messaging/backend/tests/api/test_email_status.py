from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags
from posthog.models import ProjectSecretAPIKey, Team
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret
from posthog.uuidt import UUIDT

from products.messaging.backend.facade.email_status import (
    EmailStatus,
    EmailStatusCursor,
    email_recipient_hash,
    list_email_statuses_by_recipient,
)

RANK = {"queued": 0, "sent": 4, "delivered": 5, "bounced": 6}


@patch(
    "products.messaging.backend.presentation.views.transactional_email_api.posthoganalytics.feature_enabled",
    return_value=True,
)
class TestEmailStatus(ClickhouseTestMixin, APIBaseTest):
    def _client(self, scopes: list[str]) -> APIClient:
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="email status",
            secure_value=hash_key_value(raw_token),
            scopes=scopes,
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        return client

    def _sent_at(self, created_at: datetime) -> UUID:
        return UUID(str(UUIDT(unix_time_ms=int(created_at.timestamp() * 1000))))

    def _record(
        self,
        message_id: UUID,
        status_name: str,
        at: datetime,
        *,
        team_id: int | None = None,
        recipient: str = "jane@example.com",
        reason: str = "",
    ) -> None:
        created_at = datetime.fromtimestamp(int(message_id.hex[:12], 16) / 1000, UTC)
        sync_execute(
            "INSERT INTO email_status_data (team_id, message_id, status, version, created_at, status_at, reason, "
            "recipient_hash) VALUES",
            [
                (
                    team_id or self.team.id,
                    message_id,
                    status_name,
                    RANK[status_name] * 2**48 + int(at.timestamp() * 1000),
                    created_at,
                    at,
                    reason,
                    email_recipient_hash(recipient),
                )
            ],
        )

    def _url(self, message_id: UUID | str) -> str:
        return f"/api/projects/{self.team.id}/messaging/emails/{message_id}/"

    def test_reads_the_latest_status_and_never_a_late_lower_one(self, _flag):
        created_at = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
        message_id = self._sent_at(created_at)
        self._record(message_id, "queued", created_at)
        self._record(message_id, "delivered", created_at + timedelta(seconds=3))
        self._record(message_id, "sent", created_at + timedelta(seconds=9))

        response = self._client(["hog_flow:read"]).get(self._url(message_id))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "id": str(message_id),
            "status": "delivered",
            "created_at": "2026-10-22T09:00:00Z",
            "status_at": "2026-10-22T09:00:03Z",
        }

    def test_reads_why_an_email_bounced(self, _flag):
        created_at = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
        message_id = self._sent_at(created_at)
        self._record(message_id, "bounced", created_at + timedelta(seconds=5), reason="hard")

        response = self._client(["hog_flow:read"]).get(self._url(message_id))

        assert (response.json()["status"], response.json()["reason"]) == ("bounced", "hard")

    @parameterized.expand(
        [
            ("another_team", True),
            ("unknown_id", False),
        ]
    )
    def test_answers_not_found_for_an_email_it_cannot_show(self, _flag, _name, other_team):
        created_at = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
        message_id = self._sent_at(created_at)
        if other_team:
            self._record(message_id, "sent", created_at, team_id=Team.objects.create(organization=self.organization).id)

        response = self._client(["hog_flow:read"]).get(self._url(message_id))

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()
        assert response.json()["code"] == "not_found"
        assert response.json()["why"] and response.json()["fix"]

    def test_answers_not_found_for_an_id_that_is_not_a_uuid(self, _flag):
        response = self._client(["hog_flow:read"]).get(self._url("not-a-uuid"))

        assert (response.status_code, response.json()["code"]) == (status.HTTP_404_NOT_FOUND, "not_found")

    def test_needs_the_read_scope(self, _flag):
        response = self._client(["message_template:write"]).get(self._url(self._sent_at(datetime.now(UTC))))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_lists_a_recipients_emails_newest_first_for_the_normalized_address(self, _flag):
        first_at = datetime.now(UTC) - timedelta(hours=2)
        first, second = self._sent_at(first_at), self._sent_at(first_at + timedelta(hours=1))
        self._record(first, "queued", first_at, recipient="Lookup@Example.com")
        self._record(first, "sent", first_at + timedelta(seconds=2), recipient="Lookup@Example.com")
        self._record(second, "queued", first_at + timedelta(hours=1), recipient="  lookup@example.com ")
        other_team = Team.objects.create(organization=self.organization)
        self._record(self._sent_at(first_at), "sent", first_at, team_id=other_team.id, recipient="lookup@example.com")

        records = list_email_statuses_by_recipient(
            self.team.id, " LOOKUP@example.com", since=first_at - timedelta(minutes=1), limit=10
        )

        assert [(record.message_id, record.status) for record in records] == [
            (second, EmailStatus.QUEUED),
            (first, EmailStatus.SENT),
        ]
        next_page = list_email_statuses_by_recipient(
            self.team.id,
            "lookup@example.com",
            since=first_at - timedelta(minutes=1),
            limit=10,
            cursor=EmailStatusCursor(created_at=records[0].created_at, message_id=records[0].message_id),
        )
        assert [record.message_id for record in next_page] == [first]

    @parameterized.expand(["by_id", "by_recipient"])
    def test_tags_its_clickhouse_reads(self, _flag, read):
        observed: list[tuple[object, object, object]] = []

        def tagged_sync_execute(*args: Any, **kwargs: Any) -> Any:
            tags = get_query_tags()
            observed.append((tags.team_id, tags.product, tags.feature))
            return sync_execute(*args, **kwargs)

        with patch("products.messaging.backend.services.email_status.sync_execute", tagged_sync_execute):
            if read == "by_id":
                self._client(["hog_flow:read"]).get(self._url(self._sent_at(datetime.now(UTC))))
            else:
                list_email_statuses_by_recipient(
                    self.team.id, "jane@example.com", since=datetime.now(UTC) - timedelta(days=1), limit=10
                )

        assert observed == [(self.team.id, Product.MESSAGING, Feature.QUERY)]


class TestEmailRecipientHash(SimpleTestCase):
    @override_settings(ENCRYPTION_SALT_KEYS=["00beef0000beef0000beef0000beef00"])
    def test_hashes_a_recipient_as_the_email_pipeline_does(self):
        expected = "e7b76d6c58afac8ef397725c6b81a97de6e27926a51b37ee79b281032c3f2aa7"

        assert email_recipient_hash("  Jane.Doe@Example.COM ") == expected
        assert email_recipient_hash("jane.doe@example.com") == expected
