from datetime import UTC, datetime, timedelta
from uuid import UUID

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.clickhouse.client.execute import sync_execute
from posthog.models import ProjectSecretAPIKey, Team
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret
from posthog.uuidt import UUIDT

from products.messaging.backend.facade.contracts import PushSendStatus, PushStatusReason
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.services.transactional_push_log import keyed_push_run_id, push_status_reason
from products.workflows.backend.facade.testing import create_workflow_for_test

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


@time_machine.travel(NOW, tick=False)
@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
class TestTransactionalPushStatus(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.workflow_id = self._push_template(self.team)
        self.client = self._psak_client(["transactional_push:read"])

    def _push_template(self, team: Team, push: bool = True) -> str:
        workflow_id = str(create_workflow_for_test(team_id=team.id, name="Order shipped").id)
        MessageTemplate.objects.create(
            team=team, name="Order shipped", type="push" if push else "email", transactional_hog_flow_id=workflow_id
        )
        return workflow_id

    def _psak_client(self, scopes: list[str]) -> APIClient:
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label=f"push status {ProjectSecretAPIKey.objects.filter(team=self.team).count()}",
            secure_value=hash_key_value(raw_token),
            scopes=scopes,
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        return client

    def _run(
        self,
        run_status: str,
        *,
        sent: bool = False,
        logs: tuple[tuple[str, str], ...] = (),
        run_id: str | None = None,
        team: Team | None = None,
        workflow_id: str | None = None,
        at: datetime = NOW - timedelta(minutes=5),
    ) -> str:
        team = team or self.team
        workflow_id = workflow_id or self.workflow_id
        run_id = run_id or str(UUIDT(unix_time_ms=int(at.timestamp() * 1000)))
        sync_execute(
            """
            INSERT INTO hog_invocation_results_data
                (team_id, function_kind, function_id, invocation_id, parent_run_id, status, scheduled_at,
                 first_scheduled_at, finished_at, error_message, distinct_id, person_id, version, _timestamp)
            VALUES
            """,
            [
                (team.id, "hog_flow", workflow_id, run_id, "", status_, at, at, finished, "", "alice", "", version, at)
                for status_, finished, version in [
                    ("running", None, 1),
                    *([] if run_status == "running" else [(run_status, at, 2)]),
                ]
            ],
        )
        if sent:
            sync_execute(
                """
                INSERT INTO message_assets_data
                    (team_id, function_kind, function_id, parent_run_id, invocation_id, action_id, kind, distinct_id,
                     person_id, recipient, subject, status, sent_at, version, is_deleted, html)
                VALUES
                """,
                [
                    (
                        team.id,
                        "hog_flow",
                        workflow_id,
                        "",
                        run_id,
                        "push",
                        "push",
                        "alice",
                        "",
                        "alice",
                        "Hi",
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
                    (team.id, "hog_flow", workflow_id, run_id, at + timedelta(seconds=i), level, message)
                    for i, (level, message) in enumerate(logs)
                ],
            )
        return run_id

    @parameterized.expand(
        [
            ("sent", "succeeded", True, (), "sent", None),
            ("sending", "running", False, (), "sending", None),
            (
                "no_device",
                "succeeded",
                False,
                (("warn", "[Action:push] No active FCM device token found for distinct_id: alice"),),
                "not_sent",
                "no_device",
            ),
            (
                "provider_error",
                "failed",
                False,
                (
                    ("error", "[Action:push] The APNs key was rejected. [InvalidProviderToken]"),
                    ("error", "[Action:push] Errored: Error: The APNs key was rejected. [InvalidProviderToken]"),
                ),
                "failed",
                "provider_error",
            ),
        ]
    )
    def test_reports_what_happened_to_the_send(
        self, _flag, _name, run_status, sent, logs, expected_status, expected_reason
    ):
        run_id = self._run(run_status, sent=sent, logs=logs)

        with patch(
            "products.messaging.backend.presentation.views.transactional_push_status.posthoganalytics.capture"
        ) as capture:
            response = self.client.get(f"/api/projects/{self.team.id}/messaging/pushes/{run_id}/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "id": run_id,
            "status": expected_status,
            "created_at": "2026-06-15T11:55:00Z",
            "reason": expected_reason,
        }
        assert capture.call_args.kwargs["properties"]["authorized_by"] == "transactional_push"

    @parameterized.expand([("just_finished", 10, "sending"), ("finished_a_while_ago", 120, "not_sent")])
    def test_a_finished_send_whose_outcome_is_not_recorded_yet_is_still_sending(
        self, _flag, _name, seconds_ago, expected_status
    ):
        run_id = self._run("succeeded", at=NOW - timedelta(seconds=seconds_ago))

        response = self.client.get(f"/api/projects/{self.team.id}/messaging/pushes/{run_id}/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["status"] == expected_status

    @parameterized.expand(
        [
            ("project_route", "/api/projects/{team_id}/messaging/pushes/status/"),
            ("key_route", "/api/messaging/pushes/status/"),
        ]
    )
    def test_finds_a_send_by_its_idempotency_key(self, _flag, _name, path):
        run_id = self._run("succeeded", sent=True, run_id=str(keyed_push_run_id(self.team.id, "order-7")))

        response = self.client.get(path.format(team_id=self.team.id), {"idempotency_key": "order-7"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert (response.json()["id"], response.json()["status"]) == (run_id, "sent")

    @parameterized.expand(
        [
            ("another_projects_send", "other_team"),
            ("an_email_send", "email"),
            ("not_a_uuid", "not-a-uuid"),
            ("older_than_the_retention", "old"),
        ]
    )
    def test_answers_404_for_a_send_it_cannot_report(self, _flag, _name, case):
        if case == "other_team":
            other = Team.objects.create(organization=self.organization, name="Other")
            run_id = self._run("succeeded", sent=True, team=other, workflow_id=self._push_template(other))
        elif case == "email":
            run_id = self._run("succeeded", sent=True, workflow_id=self._push_template(self.team, push=False))
        elif case == "old":
            run_id = self._run("succeeded", sent=True, at=NOW - timedelta(days=31))
        else:
            run_id = case

        response = self.client.get(f"/api/projects/{self.team.id}/messaging/pushes/{run_id}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("neither", "", status.HTTP_400_BAD_REQUEST),
            ("both", "message_id={run_id}&idempotency_key=order-7", status.HTTP_400_BAD_REQUEST),
            ("a_key_with_a_space", "idempotency_key=order%207", status.HTTP_400_BAD_REQUEST),
            ("a_key_of_no_send", "idempotency_key=order-8", status.HTTP_404_NOT_FOUND),
            ("the_id", "message_id={run_id}", status.HTTP_200_OK),
        ]
    )
    def test_a_lookup_names_exactly_one_send(self, _flag, _name, query, expected_status):
        run_id = self._run("succeeded", sent=True, run_id=str(keyed_push_run_id(self.team.id, "order-7")))

        response = self.client.get(f"/api/messaging/pushes/status/?{query.format(run_id=run_id)}")

        assert response.status_code == expected_status, response.json()

    @parameterized.expand(
        [
            ("send_scope", ["transactional_push:write"], status.HTTP_200_OK),
            ("workflow_scope", ["hog_flow:read"], status.HTTP_200_OK),
            ("email_status_scope", ["transactional_email:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_project_secret_api_key_needs_the_read_scope(self, _flag, _name, scopes, expected_status):
        run_id = self._run("succeeded", sent=True)

        response = self._psak_client(scopes).get(f"/api/projects/{self.team.id}/messaging/pushes/{run_id}/")

        assert response.status_code == expected_status

    def test_a_session_cannot_read_a_status(self, _flag):
        run_id = self._run("succeeded", sent=True)
        session = APIClient()
        session.force_login(self.user)

        response = session.get(f"/api/projects/{self.team.id}/messaging/pushes/{run_id}/")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestPushStatusReason(SimpleTestCase):
    @parameterized.expand(
        [
            ("sent", PushSendStatus.SENT, "succeeded", ["FCM: The device is no longer reachable."], None),
            ("sending", PushSendStatus.SENDING, "running", [], None),
            (
                "no_person",
                PushSendStatus.NOT_SENT,
                "succeeded",
                ["No person found for distinct_id: alice; push notification skipped."],
                PushStatusReason.NO_PERSON,
            ),
            (
                "no_token",
                PushSendStatus.NOT_SENT,
                "succeeded",
                ["No active APNS device token found for distinct_id: alice"],
                PushStatusReason.NO_DEVICE,
            ),
            (
                "expired_token",
                PushSendStatus.NOT_SENT,
                "succeeded",
                ["APNs: The device token is no longer active for the topic."],
                PushStatusReason.NO_DEVICE,
            ),
            (
                "opted_out",
                PushSendStatus.NOT_SENT,
                "succeeded",
                ["Recipient has opted out, skipping message delivery."],
                PushStatusReason.OPTED_OUT,
            ),
            (
                "frequency_capped",
                PushSendStatus.NOT_SENT,
                "succeeded",
                ["Skipping send: recipient reached the frequency cap."],
                PushStatusReason.FREQUENCY_CAPPED,
            ),
            ("not_sent_without_a_line", PushSendStatus.NOT_SENT, "succeeded", [], PushStatusReason.UNKNOWN),
            (
                "integration_missing",
                PushSendStatus.FAILED,
                "failed",
                ["Push notification integration not found", "Push notification integration not found"],
                PushStatusReason.INTEGRATION_ERROR,
            ),
            (
                "integration_undecryptable",
                PushSendStatus.FAILED,
                "failed",
                ["The push notification integration could not be decrypted. Reconnect the integration."],
                PushStatusReason.INTEGRATION_ERROR,
            ),
            (
                "person_lookup_down",
                PushSendStatus.FAILED,
                "failed",
                ["Could not look up the person for distinct_id: alice; retrying (attempt 3/3).", "timeout"],
                PushStatusReason.ERROR,
            ),
            (
                "provider_refused",
                PushSendStatus.FAILED,
                "failed",
                ["The Firebase credentials were rejected. [UNAUTHENTICATED]"],
                PushStatusReason.PROVIDER_ERROR,
            ),
            ("canceled", PushSendStatus.FAILED, "canceled", [], PushStatusReason.CANCELED),
            ("failed_before_the_step", PushSendStatus.FAILED, "failed", [], PushStatusReason.ERROR),
        ]
    )
    def test_names_why_a_push_did_not_go_out(self, _name, send_status, run_status, messages, expected):
        assert push_status_reason(send_status, run_status, messages) == expected

    @parameterized.expand(
        [
            ("an_order_key", 1, "order-123", "13714ac5-d92f-55b9-afcc-5a5ac813e066"),
            ("a_key_with_characters_json_escapes", 2, 'order-"7"\\shipped', "b84f0c62-e599-531f-8bcd-6b1309ba5f79"),
        ]
    )
    def test_derives_the_id_the_cdp_service_gives_a_keyed_send(self, _name, team_id, key, expected):
        assert keyed_push_run_id(team_id, key) == UUID(expected)
