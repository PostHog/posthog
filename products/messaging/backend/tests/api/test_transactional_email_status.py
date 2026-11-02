from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.clickhouse.client.execute import sync_execute
from posthog.models import ProjectSecretAPIKey, Team
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret
from posthog.uuidt import UUIDT

from products.messaging.backend.models.email_status_sql import EMAIL_STATUS_DATA_TABLE

# The read only compares versions, so these ranks must keep the writer's order but not its values. A status only
# moves forward, and a later status of the same rank wins by its time.
RANK = {"queued": 0, "failed": 2, "sent": 3, "delivered": 5, "bounced": 6, "complained": 7}


@time_machine.travel("2026-06-15T12:00:00Z", tick=False)
@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
class TestTransactionalEmailStatus(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.queued_at = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
        self.message_id = self._message_id(self.queued_at)
        self.client = self._psak_client(["hog_flow:read"])

    def _message_id(self, at: datetime) -> str:
        return str(UUIDT(unix_time_ms=int(at.timestamp() * 1000)))

    def _psak_client(self, scopes: list[str]) -> APIClient:
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label=f"email status {ProjectSecretAPIKey.objects.filter(team=self.team).count()}",
            secure_value=hash_key_value(raw_token),
            scopes=scopes,
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        return client

    def _url(self, message_id: str) -> str:
        return f"/api/projects/{self.team.id}/messaging/emails/{message_id}/"

    def _at(self, seconds: int) -> datetime:
        return self.queued_at + timedelta(seconds=seconds)

    def _status_rows(self, rows: list[tuple[str, int, str]], team: Team | None = None) -> None:
        """Insert (status, seconds after the send, reason) rows, in the given order."""
        for email_status, seconds, reason in rows:
            status_at = self._at(seconds)
            sync_execute(
                f"""
                INSERT INTO {EMAIL_STATUS_DATA_TABLE}
                    (team_id, message_id, status, version, created_at, status_at, reason, _timestamp, _offset, _partition)
                VALUES
                """,
                [
                    {
                        "team_id": (team or self.team).id,
                        "message_id": self.message_id,
                        "status": email_status,
                        "version": RANK[email_status] * 2**48 + int(status_at.timestamp() * 1000),
                        "created_at": self.queued_at,
                        "status_at": status_at,
                        "reason": reason,
                        "_timestamp": status_at,
                        "_offset": 0,
                        "_partition": 0,
                    }
                ],
            )

    @parameterized.expand(
        [
            ("queued", [("queued", 0, "")], "queued", 0, None),
            ("sent", [("queued", 0, ""), ("sent", 2, "")], "sent", 2, None),
            ("failed", [("queued", 0, ""), ("failed", 2, "provider_error")], "failed", 2, "provider_error"),
            ("delivered", [("queued", 0, ""), ("sent", 2, ""), ("delivered", 5, "")], "delivered", 5, None),
            ("bounced", [("queued", 0, ""), ("sent", 2, ""), ("bounced", 5, "hard")], "bounced", 5, "hard"),
            (
                "complained_after_delivery",
                [("sent", 2, ""), ("delivered", 5, ""), ("complained", 60, "abuse")],
                "complained",
                60,
                "abuse",
            ),
            # Kafka does not keep the order of a message's rows, so the highest version wins whatever arrives last.
            ("a_late_queued_row_keeps_sent", [("sent", 2, ""), ("queued", 0, "")], "sent", 2, None),
            # The worker and the SES webhook run on different clocks, so a status never moves back by its time.
            ("a_later_sent_never_replaces_delivered", [("delivered", 5, ""), ("sent", 10, "")], "delivered", 5, None),
            # A rerun keeps the message id, so its send replaces the attempt that failed.
            (
                "a_rerun_sends_after_a_failed_attempt",
                [("failed", 2, "provider_error"), ("sent", 30, "")],
                "sent",
                30,
                None,
            ),
        ]
    )
    def test_reports_the_latest_status_of_the_send(self, _flag, _name, rows, expected_status, status_offset, reason):
        self._status_rows(rows)

        with patch(
            "products.messaging.backend.presentation.views.transactional_email_status.posthoganalytics.capture"
        ) as capture:
            response = self.client.get(self._url(self.message_id))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert capture.call_args.kwargs["properties"] == {
            "team_id": self.team.id,
            "outcome": "found",
            "status": expected_status,
        }
        assert response.json() == {
            "id": self.message_id,
            "status": expected_status,
            "created_at": self.queued_at.isoformat().replace("+00:00", "Z"),
            "status_at": self._at(status_offset).isoformat().replace("+00:00", "Z"),
            "reason": reason,
        }

    @parameterized.expand(
        [
            ("not_written_yet", "message_id", False),
            ("another_projects_send", "message_id", True),
            ("not_a_uuid", "not-a-uuid", False),
            ("an_id_from_the_future", "ffffffff-ffff-4fff-bfff-ffffffffffff", False),
            ("older_than_the_retention", "old", False),
        ]
    )
    def test_answers_404_for_an_email_it_cannot_report(self, _flag, _name, message_id, other_project):
        if other_project:
            self._status_rows([("sent", 2, "")], team=Team.objects.create(organization=self.organization, name="Other"))
        ids = {"message_id": self.message_id, "old": self._message_id(datetime.now(UTC) - timedelta(days=31))}

        with patch(
            "products.messaging.backend.presentation.views.transactional_email_status.posthoganalytics.capture"
        ) as capture:
            response = self.client.get(self._url(ids.get(message_id, message_id)))

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert capture.call_args.kwargs["properties"]["outcome"] == "not_found"

    @parameterized.expand(
        [
            ("read_scope", ["hog_flow:read"], status.HTTP_200_OK),
            ("no_workflow_scope", ["feature_flag:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_project_secret_api_key_needs_the_read_scope(self, _flag, _name, scopes, expected_status):
        self._status_rows([("queued", 0, "")])

        response = self._psak_client(scopes).get(self._url(self.message_id))

        assert response.status_code == expected_status

    def test_a_session_cannot_read_a_status(self, _flag):
        self._status_rows([("queued", 0, "")])
        session = APIClient()
        session.force_login(self.user)

        response = session.get(self._url(self.message_id))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_is_hidden_while_the_flag_is_off(self, flag):
        flag.return_value = False
        self._status_rows([("queued", 0, "")])

        response = self.client.get(self._url(self.message_id))

        assert response.status_code == status.HTTP_404_NOT_FOUND
