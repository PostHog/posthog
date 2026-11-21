from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client.execute import sync_execute
from posthog.constants import AvailableFeature
from posthog.uuidt import UUIDT

from products.access_control.backend.models.access_control import AccessControl
from products.messaging.backend.models.message_template import MessageTemplate
from products.workflows.backend.facade.testing import create_workflow_for_test

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


@time_machine.travel(NOW, tick=False)
@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
class TestTransactionalPushLog(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.workflow_id = str(create_workflow_for_test(team_id=self.team.id, name="Order shipped").id)
        self.template = MessageTemplate.objects.create(
            team=self.team, name="Order shipped", type="push", transactional_hog_flow_id=self.workflow_id
        )

    def _run(
        self,
        minutes_ago: int,
        distinct_id: str,
        run_status: str,
        *,
        title: str | None = None,
        logs: list[tuple[str, str]] | None = None,
        error: str = "",
        workflow_id: str | None = None,
        retried_after: timedelta | None = None,
    ) -> str:
        workflow_id = workflow_id or self.workflow_id
        at = NOW - timedelta(minutes=minutes_ago)
        run_id = str(UUIDT(unix_time_ms=int(at.timestamp() * 1000)))
        sync_execute(
            """
            INSERT INTO hog_invocation_results_data
                (team_id, function_kind, function_id, invocation_id, parent_run_id, status, scheduled_at,
                 first_scheduled_at, error_message, distinct_id, person_id, version, _timestamp)
            VALUES
            """,
            [
                (
                    self.team.id,
                    "hog_flow",
                    workflow_id,
                    run_id,
                    "",
                    status_,
                    # A retry moves the run's later rows, and keeps the time it was first queued.
                    at + (retried_after or timedelta()) if version > 1 else at,
                    at,
                    err,
                    distinct_id,
                    "",
                    version,
                    at,
                )
                for status_, err, version in [
                    ("running", "", 1),
                    *([] if run_status == "running" else [(run_status, error, 2)]),
                ]
            ],
        )
        if title is not None:
            sync_execute(
                """
                INSERT INTO message_assets_data
                    (team_id, function_kind, function_id, parent_run_id, invocation_id, action_id, kind, distinct_id,
                     person_id, recipient, subject, status, sent_at, version, is_deleted, html)
                VALUES
                """,
                [
                    (
                        self.team.id,
                        "hog_flow",
                        workflow_id,
                        "",
                        run_id,
                        "transactional_push",
                        "push",
                        distinct_id,
                        "",
                        distinct_id,
                        title,
                        "sent",
                        at,
                        1,
                        0,
                        "",
                    )
                ],
            )
        if logs:
            sync_execute(
                "INSERT INTO log_entries (team_id, log_source, log_source_id, instance_id, timestamp, level, message) VALUES",
                [
                    (self.team.id, "hog_flow", workflow_id, run_id, at + timedelta(seconds=i), level, message)
                    for i, (level, message) in enumerate(logs)
                ],
            )
        return run_id

    def test_lists_each_send_with_its_outcome(self, _flag):
        sent = self._run(
            4,
            "alice",
            "succeeded",
            title="Your order shipped",
            logs=[("warn", "[Action:transactional_push] FCM: The device is no longer reachable.")],
        )
        not_sent = self._run(
            3,
            "bob",
            "succeeded",
            logs=[
                ("info", "[Action:transactional_push] Push notification accepted by FCM for 0 of 0 device(s)."),
                ("warn", "[Action:transactional_push] No active FCM device token found for distinct_id: bob"),
                ("warn", "Workflow-level warning that is not about the push step"),
            ],
        )
        failed = self._run(
            2,
            "carol",
            "failed",
            logs=[
                ("error", "[Action:transactional_push] Push integration not found"),
                ("error", "[Action:transactional_push] Errored: Error: Push integration not found"),
            ],
            error="Push integration not found",
        )
        sending = self._run(1, "dave", "running")
        other_workflow = str(create_workflow_for_test(team_id=self.team.id, name="Password reset").id)
        MessageTemplate.objects.create(team=self.team, name="Password reset", transactional_hog_flow_id=other_workflow)
        self._run(0, "erin", "succeeded", title="An email workflow", workflow_id=other_workflow)

        response = self.client.get(f"/api/projects/{self.team.id}/transactional_push_log/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        rows = [
            (row["run_id"], row["status"], row["distinct_id"], row["title"], row["messages"], row["template_name"])
            for row in response.json()["results"]
        ]
        assert rows == [
            (sending, "sending", "dave", "", [], "Order shipped"),
            (failed, "failed", "carol", "", ["Push integration not found"], "Order shipped"),
            (
                not_sent,
                "not_sent",
                "bob",
                "",
                ["No active FCM device token found for distinct_id: bob"],
                "Order shipped",
            ),
            (sent, "sent", "alice", "Your order shipped", ["FCM: The device is no longer reachable."], "Order shipped"),
        ]

        filtered = self.client.get(f"/api/projects/{self.team.id}/transactional_push_log/?status=not_sent")
        assert [row["run_id"] for row in filtered.json()["results"]] == [not_sent]

        stats = self.client.get(f"/api/projects/{self.team.id}/transactional_push_log/stats/")
        assert stats.json()["results"] == [
            {
                "template_id": str(self.template.id),
                "template_name": "Order shipped",
                "sent": 1,
                "not_sent": 1,
                "failed": 1,
            }
        ]

    def test_a_send_retried_past_the_end_of_the_range_shows_its_outcome(self, _flag):
        run_id = self._run(30, "ada", "failed", retried_after=timedelta(minutes=25))

        date_to = (NOW - timedelta(minutes=10)).isoformat()
        response = self.client.get(f"/api/projects/{self.team.id}/transactional_push_log/", {"date_to": date_to})

        assert [(row["run_id"], row["status"]) for row in response.json()["results"]] == [(run_id, "failed")]

    @parameterized.expand([("no_person_access", "none", 403), ("person_viewer", "viewer", 200)])
    def test_listing_sends_needs_access_to_people(self, _flag, _name, person_access, expected_status):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(team=self.team, resource="person", resource_id=None, access_level=person_access)

        response = self.client.get(f"/api/projects/{self.team.id}/transactional_push_log/")

        assert response.status_code == expected_status, response.json()

    def test_pages_through_sends(self, _flag):
        runs = [self._run(minutes_ago, f"person-{minutes_ago}", "succeeded", title="Hi") for minutes_ago in range(3)]

        first = self.client.get(f"/api/projects/{self.team.id}/transactional_push_log/?limit=2").json()
        second = self.client.get(f"/api/projects/{self.team.id}/transactional_push_log/?limit=2&offset=2").json()

        assert [row["run_id"] for row in first["results"]] == runs[:2]
        assert first["has_more"] is True
        assert [row["run_id"] for row in second["results"]] == runs[2:]
        assert second["has_more"] is False
