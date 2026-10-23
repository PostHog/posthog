from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags
from posthog.models import PersonalAPIKey, ProjectSecretAPIKey, Team
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal, generate_random_token_secret
from posthog.uuidt import UUIDT

RANK = {"queued": 0, "sent": 3, "delivered": 5, "bounced": 6}
SHARED_SALT_KEY = "00beef0000beef0000beef0000beef00"
# The email pipeline's hash of jane.doe@example.com under SHARED_SALT_KEY, its shared test vector.
JANE_DOE_HASH = "e7b76d6c58afac8ef397725c6b81a97de6e27926a51b37ee79b281032c3f2aa7"
SOMEONE_ELSE_HASH = "a1b2"


@override_settings(ENCRYPTION_SALT_KEYS=[SHARED_SALT_KEY])
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
        recipient_hash: str = JANE_DOE_HASH,
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
                    recipient_hash,
                )
            ],
        )

    def _url(self, message_id: UUID | str) -> str:
        return f"/api/projects/{self.team.id}/messaging/emails/{message_id}/"

    def test_reads_the_latest_status_and_never_a_late_lower_one(self, _flag):
        created_at = (datetime.now(UTC) - timedelta(hours=1)).replace(microsecond=0)
        message_id = self._sent_at(created_at)
        self._record(message_id, "queued", created_at)
        self._record(message_id, "delivered", created_at + timedelta(seconds=3))
        self._record(message_id, "sent", created_at + timedelta(seconds=9))

        response = self._client(["hog_flow:read"]).get(self._url(message_id))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "id": str(message_id),
            "status": "delivered",
            "created_at": created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status_at": (created_at + timedelta(seconds=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def test_reads_why_an_email_bounced(self, _flag):
        created_at = datetime.now(UTC) - timedelta(hours=1)
        message_id = self._sent_at(created_at)
        self._record(message_id, "bounced", created_at + timedelta(seconds=5), reason="hard")

        response = self._client(["hog_flow:read"]).get(self._url(message_id))

        assert (response.json()["status"], response.json()["reason"]) == ("bounced", "hard")

    @parameterized.expand(
        [
            ("another_team", timedelta(hours=1), "other"),
            ("unknown_id", timedelta(hours=1), None),
            ("older_than_kept", timedelta(days=30, hours=1), "own"),
        ]
    )
    def test_answers_not_found_for_an_email_it_cannot_show(self, _flag, _name, age, recorded_by):
        created_at = datetime.now(UTC) - age
        message_id = self._sent_at(created_at)
        if recorded_by == "own":
            self._record(message_id, "sent", created_at)
        elif recorded_by == "other":
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

    @parameterized.expand(
        [
            ("session", "by_id"),
            ("session", "by_recipient"),
            ("personal_api_key", "by_id"),
            ("personal_api_key", "by_recipient"),
        ]
    )
    def test_refuses_any_credential_but_a_project_secret_api_key(self, _flag, credential, read):
        client = APIClient()
        if credential == "session":
            client.force_login(self.user)
        else:
            personal_api_key = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="email status",
                user=self.user,
                secure_value=hash_key_value(personal_api_key),
                scopes=["hog_flow:read"],
            )
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {personal_api_key}")
        if read == "by_id":
            response = client.get(self._url(self._sent_at(datetime.now(UTC))))
        else:
            response = client.get(f"/api/projects/{self.team.id}/messaging/emails/", {"to": "jane@example.com"})
        send_without_a_credential = APIClient().post(
            f"/api/projects/{self.team.id}/messaging/send/email/", {}, format="json"
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED, response.json()
        assert response.json() == send_without_a_credential.json()

    def _list(self, query: dict[str, Any], scopes: list[str] | None = None) -> Any:
        return self._client(scopes or ["hog_flow:read"]).get(f"/api/projects/{self.team.id}/messaging/emails/", query)

    def test_lists_a_recipients_emails_newest_first_a_page_at_a_time(self, _flag):
        first_at = (datetime.now(UTC) - timedelta(hours=3)).replace(microsecond=0)
        first, third = self._sent_at(first_at), self._sent_at(first_at + timedelta(hours=2))
        second_at = first_at + timedelta(hours=1, milliseconds=100)
        second, second_in_the_same_second = (
            self._sent_at(second_at),
            self._sent_at(second_at + timedelta(milliseconds=500)),
        )
        self._record(first, "queued", first_at)
        self._record(first, "sent", first_at + timedelta(seconds=2))
        self._record(second, "bounced", second_at, reason="hard")
        self._record(second_in_the_same_second, "delivered", second_at + timedelta(seconds=1))
        self._record(third, "queued", first_at + timedelta(hours=2))
        self._record(self._sent_at(first_at), "sent", first_at, recipient_hash=SOMEONE_ELSE_HASH)
        other_team = Team.objects.create(organization=self.organization)
        self._record(self._sent_at(first_at), "sent", first_at, team_id=other_team.id)
        older_than_kept = datetime.now(UTC) - timedelta(days=30, hours=1)
        self._record(self._sent_at(older_than_kept), "sent", older_than_kept)

        first_page = self._list({"to": "  Jane.Doe@Example.COM ", "limit": 2})

        assert first_page.status_code == status.HTTP_200_OK, first_page.json()
        assert [(email["id"], email["status"], email.get("reason")) for email in first_page.json()["results"]] == [
            (str(third), "queued", None),
            (str(second_in_the_same_second), "delivered", None),
        ]
        assert "jane" not in first_page.json()["next_cursor"].lower()
        next_page = self._list({"to": "jane.doe@example.com", "limit": 2, "cursor": first_page.json()["next_cursor"]})
        assert [(email["id"], email["status"], email.get("reason")) for email in next_page.json()["results"]] == [
            (str(second), "bounced", "hard"),
            (str(first), "sent", None),
        ]
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
        self._record(message_id, "sent", sent_at)

        with override_settings(ENCRYPTION_SALT_KEYS=["11cafe0011cafe0011cafe0011cafe00", SHARED_SALT_KEY]):
            response = self._list({"to": "jane.doe@example.com"})

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
