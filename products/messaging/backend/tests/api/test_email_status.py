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

from products.messaging.backend.facade.email_status import email_recipient_hash

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
            label=f"email status {raw_token[:8]}",
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

    @parameterized.expand([("not_a_uuid", "not-a-uuid"), ("not_a_uuidt", "ffffffff-ffff-4fff-8fff-ffffffffffff")])
    def test_answers_not_found_for_an_id_no_email_can_have(self, _flag, _name, message_id):
        response = self._client(["hog_flow:read"]).get(self._url(message_id))

        assert (response.status_code, response.json()["code"]) == (status.HTTP_404_NOT_FOUND, "not_found")

    @parameterized.expand(["by_id", "by_recipient"])
    def test_needs_the_read_scope(self, _flag, read):
        client = self._client(["message_template:write"])
        if read == "by_id":
            response = client.get(self._url(self._sent_at(datetime.now(UTC))))
        else:
            response = client.get(f"/api/projects/{self.team.id}/messaging/emails/", {"to": "jane@example.com"})

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def _list(self, query: dict[str, Any], scopes: list[str] | None = None) -> Any:
        return self._client(scopes or ["hog_flow:read"]).get(f"/api/projects/{self.team.id}/messaging/emails/", query)

    def test_lists_a_recipients_emails_newest_first_a_page_at_a_time(self, _flag):
        first_at = datetime.now(UTC) - timedelta(hours=3)
        first, second, third = (self._sent_at(first_at + timedelta(hours=hour)) for hour in range(3))
        self._record(first, "queued", first_at, recipient="Lookup@Example.com")
        self._record(first, "sent", first_at + timedelta(seconds=2), recipient="Lookup@Example.com")
        self._record(second, "bounced", first_at + timedelta(hours=1), recipient="lookup@example.com", reason="hard")
        self._record(third, "queued", first_at + timedelta(hours=2), recipient="  lookup@example.com ")
        self._record(self._sent_at(first_at), "sent", first_at, recipient="someone@example.com")
        other_team = Team.objects.create(organization=self.organization)
        self._record(self._sent_at(first_at), "sent", first_at, team_id=other_team.id, recipient="lookup@example.com")
        older_than_kept = datetime.now(UTC) - timedelta(days=31)
        self._record(self._sent_at(older_than_kept), "sent", older_than_kept, recipient="lookup@example.com")

        first_page = self._list({"to": " LOOKUP@example.com", "limit": 2})

        assert first_page.status_code == status.HTTP_200_OK, first_page.json()
        assert [(email["id"], email["status"], email.get("reason")) for email in first_page.json()["results"]] == [
            (str(third), "queued", None),
            (str(second), "bounced", "hard"),
        ]
        assert "lookup" not in first_page.json()["next_cursor"].lower()
        next_page = self._list({"to": "lookup@example.com", "limit": 2, "cursor": first_page.json()["next_cursor"]})
        assert [(email["id"], email["status"]) for email in next_page.json()["results"]] == [(str(first), "sent")]
        assert next_page.json()["next_cursor"] is None

    @parameterized.expand(
        [
            ("no_address", {}, "to"),
            ("not_an_address", {"to": "jane-at-example.com"}, "to"),
            ("page_too_large", {"to": "jane@example.com", "limit": 101}, "limit"),
            ("cursor_from_nowhere", {"to": "jane@example.com", "cursor": "not-a-cursor"}, "cursor"),
            (
                "cursor_no_email_can_have",
                {"to": "jane@example.com", "cursor": "ffffffff-ffff-4fff-8fff-ffffffffffff"},
                "cursor",
            ),
        ]
    )
    def test_refuses_a_lookup_it_cannot_run_without_echoing_the_address(self, _flag, _name, query, attr):
        response = self._list(query)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert (response.json()["code"], response.json()["attr"]) == ("invalid_request", attr)
        assert response.json()["why"] and response.json()["fix"]
        assert "jane" not in response.content.decode()

    def test_lists_a_recipients_emails_recorded_before_a_salt_key_rotation(self, _flag):
        sent_at = datetime.now(UTC) - timedelta(hours=1)
        message_id = self._sent_at(sent_at)
        with override_settings(ENCRYPTION_SALT_KEYS=["00beef0000beef0000beef0000beef00"]):
            self._record(message_id, "sent", sent_at)

        with override_settings(
            ENCRYPTION_SALT_KEYS=["11cafe0011cafe0011cafe0011cafe00", "00beef0000beef0000beef0000beef00"]
        ):
            response = self._list({"to": "jane@example.com"})

        assert [email["id"] for email in response.json()["results"]] == [str(message_id)]

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
                self._list({"to": "jane@example.com"})

        assert observed == [(self.team.id, Product.MESSAGING, Feature.QUERY)]


class TestEmailRecipientHash(SimpleTestCase):
    @override_settings(ENCRYPTION_SALT_KEYS=["00beef0000beef0000beef0000beef00"])
    def test_hashes_a_recipient_as_the_email_pipeline_does(self):
        expected = "e7b76d6c58afac8ef397725c6b81a97de6e27926a51b37ee79b281032c3f2aa7"

        assert email_recipient_hash("  Jane.Doe@Example.COM ") == expected
        assert email_recipient_hash("jane.doe@example.com") == expected
