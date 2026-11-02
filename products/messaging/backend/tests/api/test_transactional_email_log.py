from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client.execute import sync_execute
from posthog.models import Team
from posthog.test.persons import create_person
from posthog.uuidt import UUIDT

from products.messaging.backend.models.email_status_sql import EMAIL_STATUS_EVENTS_DATA_TABLE
from products.messaging.backend.models.message_template import MessageTemplate

# `run_failed` is the failure the whole run writes, which ranks below the email step's own failure.
RANK = {
    "queued": 0,
    "run_failed": 1,
    "failed": 2,
    "sent": 3,
    "delivered": 5,
    "bounced": 6,
    "complained": 7,
    "opened": 8,
    "clicked": 9,
}
NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


@time_machine.travel(NOW, tick=False)
@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
class TestTransactionalEmailLog(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.workflow_id = str(UUIDT())
        self.template = MessageTemplate.objects.create(
            team=self.team, name="Password reset", transactional_hog_flow_id=self.workflow_id
        )

    def _send(
        self,
        minutes_ago: int,
        recipient: str,
        statuses: list[tuple[str, int, str]],
        *,
        team: Team | None = None,
        workflow_id: str | None = None,
        domain: str = "mail.example.com",
    ) -> str:
        queued_at = NOW - timedelta(minutes=minutes_ago)
        message_id = str(UUIDT(unix_time_ms=int(queued_at.timestamp() * 1000)))
        rows = [("queued", 0, ""), *statuses]
        sync_execute(
            f"""
            INSERT INTO {EMAIL_STATUS_EVENTS_DATA_TABLE}
                (team_id, message_id, status, version, created_at, status_at, reason, recipient, function_id,
                 sending_domain, _timestamp, _offset, _partition)
            VALUES
            """,
            [
                {
                    "team_id": (team or self.team).id,
                    "message_id": message_id,
                    "status": "failed" if row_status == "run_failed" else row_status,
                    "version": RANK[row_status] * 2**48
                    + int((queued_at + timedelta(seconds=seconds)).timestamp() * 1000),
                    "created_at": queued_at,
                    "status_at": queued_at + timedelta(seconds=seconds),
                    "reason": reason,
                    "recipient": recipient if row_status == "queued" else "",
                    "function_id": (workflow_id or self.workflow_id) if row_status == "queued" else "",
                    "sending_domain": domain if row_status == "sent" else "",
                    "_timestamp": queued_at,
                    "_offset": 0,
                    "_partition": 0,
                }
                for row_status, seconds, reason in rows
            ],
        )
        return message_id

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/transactional_email_log/{suffix}"

    def test_lists_sends_newest_first_and_an_open_never_hides_a_bounce(self, _flag):
        oldest = self._send(30, "a@example.com", [("sent", 1, ""), ("delivered", 2, ""), ("opened", 60, "")])
        bounced = self._send(20, "b@example.com", [("sent", 1, ""), ("bounced", 2, "hard"), ("opened", 90, "")])
        # Message ids sort by creation time as text, but ClickHouse compares a UUID in its own byte order.
        newest = self._send(10, "c@example.com", [("sent", 1, ""), ("clicked", 30, "")])
        self._send(5, "other@example.com", [("sent", 1, "")], team=Team.objects.create(organization=self.organization))

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK, response.json()
        results = response.json()["results"]
        assert [(r["message_id"], r["status"], r["reason"], r["opened"], r["clicked"]) for r in results] == [
            (newest, "sent", None, False, True),
            (bounced, "bounced", "hard", True, False),
            (oldest, "delivered", None, True, False),
        ]
        assert results[0]["template_name"] == "Password reset"
        assert results[0]["sending_domain"] == "mail.example.com"

    @parameterized.expand(
        [
            ("part_of_the_recipient", {"search": "JANE"}, ["jane@example.com"]),
            ("status", {"status": "failed"}, ["bob@example.com"]),
            ("page_size", {"limit": 1}, ["bob@example.com"]),
        ]
    )
    def test_filters_the_list(self, _flag, _name, params, expected_recipients):
        self._send(20, "jane@example.com", [("sent", 1, "")])
        self._send(10, "bob@example.com", [("failed", 1, "provider_error")])

        response = self.client.get(self._url(), params)

        assert [r["recipient"] for r in response.json()["results"]] == expected_recipients
        assert response.json()["has_more"] == (params.get("limit") == 1)

    def test_shows_one_send_with_its_timeline(self, _flag):
        message_id = self._send(
            10, "jane@example.com", [("failed", 1, "provider_error"), ("run_failed", 2, "hog_error")]
        )

        response = self.client.get(self._url(f"{message_id}/"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert (body["status"], body["reason"]) == ("failed", "provider_error")
        # A failed email step also fails its run, and that second failure says less.
        assert [(event["kind"], event["reason"]) for event in body["timeline"]] == [
            ("queued", None),
            ("failed", "provider_error"),
        ]

    @parameterized.expand([("another_projects_send", True), ("a_deleted_template", False)])
    def test_hides_what_the_project_cannot_see(self, _flag, _name, other_team):
        team = Team.objects.create(organization=self.organization) if other_team else None
        message_id = self._send(10, "jane@example.com", [("sent", 1, "")], team=team)
        self.template.deleted = True
        self.template.save()

        response = self.client.get(self._url(f"{message_id}/"))

        if other_team:
            assert response.status_code == status.HTTP_404_NOT_FOUND
        else:
            assert (response.json()["template_id"], response.json()["template_name"]) == (None, "")

    def test_counts_sends_per_template_and_per_sending_domain(self, _flag):
        self._send(30, "a@example.com", [("sent", 1, ""), ("delivered", 2, ""), ("opened", 60, ""), ("opened", 90, "")])
        self._send(20, "b@example.com", [("sent", 1, ""), ("bounced", 2, "hard")], domain="other.example.com")
        self._send(10, "c@example.com", [("failed", 1, "provider_error")])

        by_template = self.client.get(self._url("stats/")).json()["results"]
        by_domain = self.client.get(self._url("stats/"), {"group_by": "sending_domain"}).json()["results"]

        assert [
            (r["key"], r["label"], r["sent"], r["delivered"], r["bounced"], r["opened"], r["failed"])
            for r in by_template
        ] == [(str(self.template.id), "Password reset", 2, 1, 1, 1, 1)]
        assert [(r["key"], r["sent"], r["bounced"]) for r in by_domain] == [
            ("mail.example.com", 1, 0),
            ("other.example.com", 1, 1),
        ]

    def test_counts_who_converted_within_the_window_after_their_first_send(self, _flag):
        for distinct_id, sent_minutes_ago in [("converted", 600), ("too-late", 600 * 24), ("never", 60)]:
            create_person(team=self.team, distinct_ids=[distinct_id])
            sync_execute(
                """
                INSERT INTO message_assets_data
                    (team_id, function_kind, function_id, parent_run_id, invocation_id, action_id, kind, distinct_id,
                     person_id, recipient, subject, status, sent_at, version, is_deleted, html)
                VALUES
                """,
                [
                    {
                        "team_id": self.team.id,
                        "function_kind": "hog_flow",
                        "function_id": self.workflow_id,
                        "parent_run_id": "",
                        "invocation_id": str(UUIDT()),
                        "action_id": "transactional_email",
                        "kind": "email",
                        "distinct_id": distinct_id,
                        "person_id": "",
                        "recipient": f"{distinct_id}@example.com",
                        "subject": "Reset",
                        "status": "sent",
                        "sent_at": NOW - timedelta(minutes=sent_minutes_ago),
                        "version": 1,
                        "is_deleted": 0,
                        "html": "",
                    }
                ],
            )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="converted",
            timestamp=NOW - timedelta(minutes=300),
            properties={"amount": 30},
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="too-late",
            timestamp=NOW - timedelta(minutes=300),
            properties={"amount": 50},
        )
        flush_persons_and_events()

        response = self.client.get(
            self._url("results/"),
            {
                "workflow_id": self.workflow_id,
                "event": "purchase",
                "window_days": 1,
                "revenue_property": "amount",
                "date_from": (NOW - timedelta(days=29)).isoformat(),
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"recipients": 3, "converted": 1, "revenue": 30.0, "median_hours_to_convert": 5.0}
