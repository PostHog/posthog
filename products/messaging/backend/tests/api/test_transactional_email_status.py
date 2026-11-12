from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.clickhouse.client.execute import sync_execute
from posthog.models import ProjectSecretAPIKey, Team
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret
from posthog.uuidt import UUIDT

from products.messaging.backend.models.email_status_sql import EMAIL_STATUS_DATA_TABLE
from products.messaging.backend.tests.fake_cdp_api import FakeAnalytics, FakeCdpApi

# The read only compares versions, so these ranks must keep the writer's order but not its values. A status only
# moves forward, and a later status of the same rank wins by its time.
RANK = {
    "scheduled": 0,
    "queued": 0,
    "canceled": 1,
    "deferred": 1,
    "failed": 2,
    "sent": 3,
    "delivered": 5,
    "bounced": 6,
    "complained": 7,
}


class EmailsApiTestBase(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.queued_at = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
        self.message_id = self._message_id(self.queued_at)
        self.client = self._psak_client(["hog_flow:read"])

    def _message_id(self, at: datetime) -> str:
        return str(UUIDT(unix_time_ms=int(at.timestamp() * 1000)))

    def _psak_client(self, scopes: list[str], team: Team | None = None) -> APIClient:
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=team or self.team,
            label=f"email status {ProjectSecretAPIKey.objects.filter(team=team or self.team).count()}",
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


@time_machine.travel("2026-06-15T12:00:00Z", tick=False)
@patch(
    "products.messaging.backend.presentation.views.transactional_email_access.posthoganalytics.feature_enabled",
    return_value=True,
)
class TestTransactionalEmailStatus(EmailsApiTestBase):
    @parameterized.expand(
        [
            ("queued", [("queued", 0, "")], "queued", 0, None),
            ("scheduled", [("scheduled", 0, "")], "scheduled", 0, None),
            ("canceled_while_it_waited", [("scheduled", 0, ""), ("canceled", 60, "")], "canceled", 60, None),
            ("sent_at_its_scheduled_time", [("scheduled", 0, ""), ("sent", 3600, "")], "sent", 3600, None),
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

        response = self.client.get(self._url(self.message_id))

        assert response.status_code == status.HTTP_200_OK, response.json()
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
            ("a_status_this_server_does_not_know", "unknown_status", False),
            ("another_projects_send", "message_id", True),
            ("not_a_uuid", "not-a-uuid", False),
            ("an_id_from_the_future", "ffffffff-ffff-4fff-bfff-ffffffffffff", False),
            ("older_than_the_retention", "old", False),
        ]
    )
    def test_answers_404_for_an_email_it_cannot_report(self, _flag, _name, message_id, other_project):
        if other_project:
            self._status_rows([("sent", 2, "")], team=Team.objects.create(organization=self.organization, name="Other"))
        if message_id == "unknown_status":
            self._status_rows([("deferred", 0, "")])
        ids = {
            "message_id": self.message_id,
            "unknown_status": self.message_id,
            "old": self._message_id(datetime.now(UTC) - timedelta(days=61)),
        }

        response = self.client.get(self._url(ids.get(message_id, message_id)))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("found", [("scheduled", 0, "")], "found", "scheduled"),
            ("not_found", [], "not_found", None),
        ]
    )
    def test_records_each_read_for_usage(self, _flag, _name, rows, expected_outcome, expected_status):
        self._status_rows(rows)

        analytics = FakeAnalytics()

        with patch(
            "products.messaging.backend.presentation.views.transactional_email_status.posthoganalytics.capture",
            side_effect=analytics.capture,
        ):
            self.client.get(self._url(self.message_id))

        assert analytics.properties_of("transactional email api status read") == [
            {
                "team_id": self.team.id,
                "outcome": expected_outcome,
                "status": expected_status,
                "auth_method": "project_secret_api_key",
                "authorized_by": "hog_flow",
            }
        ]

    @parameterized.expand(
        [
            ("read_scope", ["hog_flow:read"], status.HTTP_200_OK, "hog_flow"),
            ("status_scope", ["transactional_email:read"], status.HTTP_200_OK, "transactional_email"),
            ("send_scope", ["transactional_email:write"], status.HTTP_200_OK, "transactional_email"),
            ("no_workflow_scope", ["feature_flag:read"], status.HTTP_403_FORBIDDEN, None),
            ("preference_scope", ["messaging_preference:write"], status.HTTP_403_FORBIDDEN, None),
        ]
    )
    def test_project_secret_api_key_needs_the_read_scope(
        self, _flag, _name, scopes, expected_status, expected_authorized_by
    ):
        self._status_rows([("queued", 0, "")])

        analytics = FakeAnalytics()

        with patch(
            "products.messaging.backend.presentation.views.transactional_email_status.posthoganalytics.capture",
            side_effect=analytics.capture,
        ):
            response = self._psak_client(scopes).get(self._url(self.message_id))

        assert response.status_code == expected_status
        assert [event["authorized_by"] for event in analytics.properties_of("transactional email api status read")] == (
            [expected_authorized_by] if expected_authorized_by else []
        )

    def test_a_session_cannot_read_a_status(self, _flag):
        self._status_rows([("queued", 0, "")])
        session = APIClient()
        session.force_login(self.user)

        response = session.get(self._url(self.message_id))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @parameterized.expand(
        [
            ("both_send_flags_off", set(), status.HTTP_404_NOT_FOUND),
            ("only_the_template_send_flag", {"workflows-transactional-email-api"}, status.HTTP_200_OK),
            ("only_the_code_send_flag", {"workflows-email-from-code"}, status.HTTP_200_OK),
        ]
    )
    def test_reads_a_status_under_either_send_flag(self, flag, _name, enabled_flags, expected_status):
        flag.side_effect = lambda key, *args, **kwargs: key in enabled_flags
        self._status_rows([("queued", 0, "")])

        response = self.client.get(self._url(self.message_id))

        assert response.status_code == expected_status

    def test_reads_a_send_up_to_60_days_old(self, _flag):
        self.queued_at = datetime.now(UTC).replace(microsecond=0) - timedelta(days=59)
        self.message_id = self._message_id(self.queued_at)
        self._status_rows([("scheduled", 0, ""), ("sent", 30 * 24 * 3600, "")])

        response = self.client.get(self._url(self.message_id))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["status"] == "sent"


@time_machine.travel("2026-06-15T12:00:00Z", tick=False)
@patch(
    "products.messaging.backend.presentation.views.transactional_email_access.posthoganalytics.feature_enabled",
    return_value=True,
)
@patch("posthog.plugins.plugin_server_api.internal_requests.post")
class TestManageScheduledEmails(EmailsApiTestBase):
    def setUp(self):
        super().setUp()
        self.client = self._psak_client(["transactional_email:write"])
        self.cdp = FakeCdpApi()

    def _cancel(self, mock_post: MagicMock, client: APIClient | None = None, message_id: str | None = None) -> Any:
        with self.cdp.serving(mock_post):
            return (client or self.client).post(f"{self._url(message_id or self.message_id)}cancel/")

    def _move(self, mock_post: MagicMock, body: dict[str, Any], client: APIClient | None = None) -> Any:
        with self.cdp.serving(mock_post):
            return (client or self.client).patch(self._url(self.message_id), body, format="json")

    def _job(self, state: str | None) -> None:
        if state is not None:
            self.cdp.jobs[(self.team.id, self.message_id)] = state

    @parameterized.expand(
        [
            ("waiting", "waiting", [], status.HTTP_200_OK, None, "canceled"),
            ("a_repeat_while_the_job_is_kept", "canceled", [], status.HTTP_200_OK, None, "canceled"),
            ("claimed_by_a_worker", "claimed", [], status.HTTP_409_CONFLICT, "already_sending", "claimed"),
            ("a_repeat_after_the_job_is_gone", None, [("canceled", 60, "")], status.HTTP_200_OK, None, None),
            ("gone_after_it_went_out", None, [("sent", 60, "")], status.HTTP_404_NOT_FOUND, "not_found", None),
            (
                "gone_before_its_send_status_landed",
                None,
                [("queued", 0, "")],
                status.HTTP_404_NOT_FOUND,
                "not_found",
                None,
            ),
            (
                "gone_with_only_its_scheduled_status",
                None,
                [("scheduled", 0, "")],
                status.HTTP_404_NOT_FOUND,
                "not_found",
                None,
            ),
            ("unknown", None, [], status.HTTP_404_NOT_FOUND, "not_found", None),
        ]
    )
    def test_cancel_answers_for_each_state_of_the_email(
        self, mock_post, _flag, _name, job, status_rows, expected_status, expected_code, expected_job
    ):
        self._job(job)
        self._status_rows(status_rows)

        response = self._cancel(mock_post)

        assert response.status_code == expected_status, response.json()
        if expected_code:
            assert response.json()["code"] == expected_code
        else:
            assert response.json() == {"id": self.message_id, "status": "canceled"}
        assert self.cdp.jobs.get((self.team.id, self.message_id)) == expected_job

    def test_the_schema_requires_the_time_to_move_an_email(self, _mock_post, _flag):
        schema = self.client.get("/api/schema/").data

        move = schema["paths"]["/api/projects/{project_id}/messaging/emails/{id}/"]["patch"]["requestBody"]
        body = schema["components"]["schemas"][move["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]]
        assert (move.get("required"), body.get("required")) == (True, ["scheduled_at"])

    @parameterized.expand(
        [
            ("before_any_status_landed", []),
            ("before_its_cancel_status_landed", [("scheduled", 0, "")]),
        ]
    )
    def test_a_repeat_cancel_after_the_job_is_gone_answers_canceled(self, mock_post, _flag, _name, status_rows):
        self._job("waiting")
        self._status_rows(status_rows)
        self._cancel(mock_post)
        del self.cdp.jobs[(self.team.id, self.message_id)]

        response = self._cancel(mock_post)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"id": self.message_id, "status": "canceled"}

    @parameterized.expand(
        [
            ("just_queued_before_any_status_landed", 10, [], [], status.HTTP_503_SERVICE_UNAVAILABLE),
            (
                "before_its_cancel_status_landed",
                3600,
                [("scheduled", 0, "")],
                [],
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ),
            (
                "before_its_queued_cancel_landed",
                3600,
                [("queued", 0, "")],
                [],
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ),
            (
                "once_its_cancel_status_landed",
                3600,
                [("scheduled", 0, "")],
                [("canceled", 60, "")],
                status.HTTP_200_OK,
            ),
            (
                "after_it_went_out_unchanged",
                3600,
                [("scheduled", 0, "")],
                [("sent", 60, "")],
                status.HTTP_404_NOT_FOUND,
            ),
            ("with_no_status_long_after_it_was_queued", 3600, [], [], status.HTTP_404_NOT_FOUND),
        ]
    )
    def test_a_retry_after_a_lost_cancel_answer(
        self, mock_post, _flag, _name, queued_seconds_ago, status_rows, later_rows, expected_status
    ):
        self.queued_at = datetime.now(UTC) - timedelta(seconds=queued_seconds_ago)
        self.message_id = self._message_id(self.queued_at)
        self._job("waiting")
        self._status_rows(status_rows)
        mock_post.side_effect = self._lose_the_answer()
        lost = self.client.post(f"{self._url(self.message_id)}cancel/")
        self.cdp.jobs.pop((self.team.id, self.message_id), None)
        self._status_rows(later_rows)

        response = self._cancel(mock_post)

        assert lost.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.status_code == expected_status, response.json()

    def test_a_lost_answer_on_a_repeat_cancel_keeps_it_canceled(self, mock_post, _flag):
        self._job("waiting")
        self._cancel(mock_post)
        del self.cdp.jobs[(self.team.id, self.message_id)]
        mock_post.side_effect = self._lose_the_answer()
        self.client.post(f"{self._url(self.message_id)}cancel/")

        response = self._cancel(mock_post)

        assert response.status_code == status.HTTP_200_OK, response.json()

    def _lose_the_answer(self) -> Any:
        def post(*args: Any, **kwargs: Any) -> requests.Response:
            raise requests.Timeout()

        return post

    def test_a_cancel_reaches_the_pipeline_when_writing_the_mark_fails(self, mock_post, _flag):
        self._job("waiting")

        with patch(
            "products.messaging.backend.services.scheduled_emails.cache.set", side_effect=ConnectionError("down")
        ):
            response = self._cancel(mock_post)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self.cdp.jobs.get((self.team.id, self.message_id)) == "canceled"

    def test_a_repeat_cancel_answers_from_the_status_when_reading_the_mark_fails(self, mock_post, _flag):
        self._status_rows([("canceled", 60, "")])

        with patch(
            "products.messaging.backend.services.scheduled_emails.cache.get", side_effect=ConnectionError("down")
        ):
            response = self._cancel(mock_post)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"id": self.message_id, "status": "canceled"}

    @parameterized.expand(
        [
            ("to_a_later_time", "waiting", "2026-06-17T09:30:00+02:00", status.HTTP_200_OK, "2026-06-17T07:30:00Z"),
            ("to_a_time_that_passed", "waiting", "2026-06-01T00:00:00Z", status.HTTP_200_OK, "2026-06-15T12:00:00Z"),
            ("past_30_days_after_the_send", "waiting", "2026-07-16T00:00:00Z", status.HTTP_400_BAD_REQUEST, None),
            ("claimed_by_a_worker", "claimed", "2026-06-17T00:00:00Z", status.HTTP_409_CONFLICT, None),
            ("canceled", "canceled", "2026-06-17T00:00:00Z", status.HTTP_409_CONFLICT, None),
            ("unknown", None, "2026-06-17T00:00:00Z", status.HTTP_404_NOT_FOUND, None),
        ]
    )
    def test_reschedule_answers_for_each_state_of_the_email(
        self, mock_post, _flag, name, job, scheduled_at, expected_status, expected_scheduled_at
    ):
        self._job(job)

        response = self._move(mock_post, {"scheduled_at": scheduled_at})

        assert response.status_code == expected_status, response.json()
        body = response.json()
        if expected_scheduled_at:
            assert body == {"id": self.message_id, "status": "scheduled", "scheduled_at": expected_scheduled_at}
            return
        expected_code = {
            "past_30_days_after_the_send": "invalid_scheduled_at",
            "claimed_by_a_worker": "already_sending",
            "canceled": "canceled",
            "unknown": "not_found",
        }[name]
        assert body["code"] == expected_code
        if expected_code != "not_found":
            assert body["why"] and body["fix"]
        assert self.cdp.scheduled_for == {}

    @parameterized.expand(
        [
            ("no_offset", {"scheduled_at": "2026-06-17T09:00:00"}, "scheduled_at", "no_offset"),
            ("missing", {}, "scheduled_at", "required"),
            (
                "another_field",
                {"scheduled_at": "2026-06-17T09:00:00Z", "to": "jane@example.com"},
                "to",
                "invalid_request",
            ),
        ]
    )
    def test_reschedule_refuses_a_body_it_cannot_take(self, mock_post, _flag, _name, body, attr, code):
        self._job("waiting")

        response = self._move(mock_post, body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (response.json()["attr"], response.json()["code"]) == (attr, code)
        assert self.cdp.received == []

    @parameterized.expand(
        [
            ("cancel_with_the_scheduled_flag_off", {"workflows-email-from-code"}, "cancel", None, status.HTTP_200_OK),
            (
                "move_to_now_with_the_scheduled_flag_off",
                {"workflows-email-from-code"},
                "move",
                "2026-06-01T00:00:00Z",
                status.HTTP_200_OK,
            ),
            (
                "move_later_with_the_scheduled_flag_off",
                {"workflows-email-from-code"},
                "move",
                "2026-06-17T00:00:00Z",
                status.HTTP_400_BAD_REQUEST,
            ),
            (
                "move_later_with_the_scheduled_flag_on",
                {"workflows-email-from-code", "workflows-email-scheduled-sends"},
                "move",
                "2026-06-17T00:00:00Z",
                status.HTTP_200_OK,
            ),
            (
                "cancel_with_both_send_flags_off",
                {"workflows-email-scheduled-sends"},
                "cancel",
                None,
                status.HTTP_404_NOT_FOUND,
            ),
            (
                "move_with_both_send_flags_off",
                {"workflows-email-scheduled-sends"},
                "move",
                "2026-06-01T00:00:00Z",
                status.HTTP_404_NOT_FOUND,
            ),
        ]
    )
    def test_each_call_needs_its_flags(
        self, mock_post, flag, _name, enabled_flags, call, scheduled_at, expected_status
    ):
        flag.side_effect = lambda key, *args, **kwargs: key in enabled_flags
        self._job("waiting")

        if call == "cancel":
            response = self._cancel(mock_post)
        else:
            response = self._move(mock_post, {"scheduled_at": scheduled_at})

        assert response.status_code == expected_status
        assert self.cdp.jobs[(self.team.id, self.message_id)] == (
            "canceled" if expected_status == 200 and call == "cancel" else "waiting"
        )

    @parameterized.expand(
        [
            ("a_plain_404_from_a_pipeline_without_the_route", 404, b"Not Found", "text/html"),
            ("a_server_error", 500, b'{"error": "boom"}', "application/json"),
            ("a_refused_token", 401, b'{"error": "Unauthorized"}', "application/json"),
            ("an_unknown_refusal", 409, b'{"error": "something_new"}', "application/json"),
        ]
    )
    def test_an_answer_that_names_no_state_is_unavailable(
        self, mock_post, _flag, _name, status_code, content, content_type
    ):
        answer = requests.Response()
        answer.status_code, answer._content = status_code, content
        answer.headers["Content-Type"] = content_type
        mock_post.return_value = answer

        for response in (
            self.client.post(f"{self._url(self.message_id)}cancel/"),
            self.client.patch(self._url(self.message_id), {"scheduled_at": "2026-06-17T00:00:00Z"}, format="json"),
        ):
            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            assert response.json()["code"] == "delivery_unavailable"

    def test_an_unreachable_pipeline_is_unavailable(self, mock_post, _flag):
        mock_post.side_effect = requests.ConnectionError()

        response = self.client.post(f"{self._url(self.message_id)}cancel/")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_another_projects_email_is_not_found(self, mock_post, _flag):
        self._job("waiting")

        responses = self._manage_from_another_project(mock_post)

        assert [response.status_code for response in responses] == [404, 404]
        assert self.cdp.jobs.get((self.team.id, self.message_id)) == "waiting"

    def test_another_projects_repeat_cancel_after_ours_is_not_found(self, mock_post, _flag):
        self._job("waiting")
        self._cancel(mock_post)
        del self.cdp.jobs[(self.team.id, self.message_id)]

        responses = self._manage_from_another_project(mock_post)

        assert [response.status_code for response in responses] == [404, 404]

    def _manage_from_another_project(self, mock_post: MagicMock) -> list[Any]:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_client = self._psak_client(["transactional_email:write"], team=other_team)
        other_url = f"/api/projects/{other_team.id}/messaging/emails/{self.message_id}/"

        with self.cdp.serving(mock_post):
            responses = [
                other_client.post(f"{other_url}cancel/"),
                other_client.patch(other_url, {"scheduled_at": "2026-06-17T00:00:00Z"}, format="json"),
            ]
        return responses

    @parameterized.expand(
        [
            ("write_scope", ["transactional_email:write"], status.HTTP_200_OK, "transactional_email"),
            ("workflow_write_scope", ["hog_flow:write"], status.HTTP_200_OK, "hog_flow"),
            ("read_scope", ["transactional_email:read"], status.HTTP_403_FORBIDDEN, None),
            ("workflow_read_scope", ["hog_flow:read"], status.HTTP_403_FORBIDDEN, None),
        ]
    )
    def test_project_secret_api_key_needs_the_write_scope(
        self, mock_post, _flag, _name, scopes, expected_status, expected_authorized_by
    ):
        self._job("waiting")
        analytics = FakeAnalytics()

        with patch(
            "products.messaging.backend.presentation.views.transactional_email_status.posthoganalytics.capture",
            side_effect=analytics.capture,
        ):
            responses = [
                self._move(mock_post, {"scheduled_at": "2026-06-17T00:00:00Z"}, client=self._psak_client(scopes)),
                self._cancel(mock_post, client=self._psak_client(scopes)),
            ]

        assert [response.status_code for response in responses] == [expected_status, expected_status]
        assert [event["authorized_by"] for event in analytics.properties_of("transactional email api manage")] == (
            [expected_authorized_by] * 2 if expected_authorized_by else []
        )

    def test_a_session_cannot_cancel_or_move_an_email(self, mock_post, _flag):
        self._job("waiting")
        session = APIClient()
        session.force_login(self.user)

        responses = [
            self._cancel(mock_post, client=session),
            self._move(mock_post, {"scheduled_at": "2026-06-17T00:00:00Z"}, client=session),
        ]

        assert [response.status_code for response in responses] == [401, 401]
        assert self.cdp.received == []

    @parameterized.expand(
        [
            ("canceled", "cancel", "waiting", None, {"outcome": "canceled"}),
            ("already_sending", "cancel", "claimed", None, {"outcome": "already_sending"}),
            ("not_found", "cancel", None, None, {"outcome": "not_found"}),
            (
                "moved",
                "move",
                "waiting",
                "2026-06-17T00:00:00Z",
                {"outcome": "scheduled", "lead_time_bucket": "1d_to_3d"},
            ),
            (
                "moved_to_now",
                "move",
                "waiting",
                "2026-06-01T00:00:00Z",
                {"outcome": "scheduled", "lead_time_bucket": "now"},
            ),
            (
                "move_canceled",
                "move",
                "canceled",
                "2026-06-15T12:30:00Z",
                {"outcome": "canceled_before", "lead_time_bucket": "under_1h"},
            ),
            (
                "move_too_far",
                "move",
                "waiting",
                "2026-07-16T00:00:00Z",
                {"outcome": "invalid_scheduled_at", "lead_time_bucket": "over_30d"},
            ),
            ("move_without_an_offset", "move", "waiting", "2026-06-17T09:00:00", {"outcome": "invalid_request"}),
            (
                "move_later_with_the_scheduled_flag_off",
                "move",
                "waiting",
                "2026-06-17T00:00:00Z",
                {"outcome": "scheduled_sends_off", "lead_time_bucket": "1d_to_3d"},
                {"workflows-email-from-code"},
            ),
        ]
    )
    def test_records_each_call_for_usage(
        self, mock_post, flag, _name, call, job, scheduled_at, expected, enabled_flags=None
    ):
        if enabled_flags is not None:
            flag.side_effect = lambda key, *args, **kwargs: key in enabled_flags
        self._job(job)
        analytics = FakeAnalytics()

        with patch(
            "products.messaging.backend.presentation.views.transactional_email_status.posthoganalytics.capture",
            side_effect=analytics.capture,
        ):
            if call == "cancel":
                self._cancel(mock_post)
            else:
                self._move(mock_post, {"scheduled_at": scheduled_at})

        assert analytics.properties_of("transactional email api manage") == [
            {
                "team_id": self.team.id,
                "action": "cancel" if call == "cancel" else "reschedule",
                **expected,
                "auth_method": "project_secret_api_key",
                "authorized_by": "transactional_email",
            }
        ]

    @parameterized.expand([("cancel", "canceled"), ("move", "waiting")])
    def test_a_failed_usage_capture_keeps_the_answer(self, mock_post, _flag, call, expected_job):
        self._job("waiting")

        with patch(
            "products.messaging.backend.presentation.views.transactional_email_status.posthoganalytics.capture",
            side_effect=RuntimeError("analytics is down"),
        ):
            if call == "cancel":
                response = self._cancel(mock_post)
            else:
                response = self._move(mock_post, {"scheduled_at": "2026-06-17T00:00:00Z"})

        assert response.status_code == status.HTTP_200_OK
        assert self.cdp.jobs[(self.team.id, self.message_id)] == expected_job
