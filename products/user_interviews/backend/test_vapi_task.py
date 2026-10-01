from typing import Any

from posthog.test.base import APIBaseTest

from django.db import InterfaceError, OperationalError, connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.celery import app as celery_app

from products.user_interviews.backend.models import IntervieweeContext, UserInterview, UserInterviewTopic
from products.user_interviews.backend.tasks.tasks import handle_vapi_webhook

TASK_NAME = "products.user_interviews.backend.tasks.handle_vapi_webhook"


class TestVapiWebhookTask(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.topic = UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            interviewee_emails=["alex@example.com"],
            topic="Replay adoption",
            agent_context="ctx",
            questions=[],
        )
        self.interviewee_context = IntervieweeContext.objects.create(
            team=self.team,
            topic=self.topic,
            interviewee_identifier="alex@example.com",
            agent_context="",
            created_by=self.user,
        )

    def _report(self, call_id: str = "call_abc") -> dict[str, Any]:
        return {
            "message": {
                "type": "end-of-call-report",
                "call": {"id": call_id, "duration": 120},
                "transcript": "Hi! ...",
                "summary": "User talked about replay.",
                "recording": {"url": "https://vapi.example/recording.mp3"},
            }
        }

    def _run(self, payload: dict[str, Any]) -> None:
        handle_vapi_webhook(
            payload=payload,
            event_type="end-of-call-report",
            team_id=self.team.pk,
            topic_id=str(self.topic.pk),
            interviewee_context_id=str(self.interviewee_context.pk),
            interviewee_identifier="alex@example.com",
            received_at="2026-05-14T12:00:00+00:00",
        )

    def test_task_is_registered_under_the_name_a_publisher_sends(self):
        # The name is the contract between the web pod that publishes and the worker that runs the
        # task. A worker that does not know the name drops the message, and Vapi never resends.
        self.assertIn(TASK_NAME, celery_app.tasks)

    def test_task_survives_a_database_error_and_a_lost_worker(self):
        # Both settings are silently inert when missing: max_retries without autoretry_for never
        # retries, and the default early acknowledgement drops the report when the worker dies.
        self.assertEqual(handle_vapi_webhook.autoretry_for, (OperationalError, InterfaceError))
        self.assertTrue(handle_vapi_webhook.acks_late)
        self.assertTrue(handle_vapi_webhook.reject_on_worker_lost)
        # The default backoff spends every attempt within seconds, which is shorter than any
        # database outage worth retrying through, and Vapi never resends the report.
        window_seconds = sum(
            min(handle_vapi_webhook.retry_backoff * 2**attempt, handle_vapi_webhook.retry_backoff_max)
            for attempt in range(handle_vapi_webhook.max_retries)
        )
        self.assertGreater(window_seconds, 60 * 60)

    @parameterized.expand([("null_message", {"message": None}), ("null_call", {"message": {"call": None}})])
    def test_task_survives_a_null_message_or_call(self, _name: str, payload: dict[str, Any]) -> None:
        # A JSON null where the message or call object goes must not raise: an AttributeError is
        # outside the task's retry list. Without a call id there is no idempotency either, so the
        # report must not become a blank interview on every redelivery.
        self._run(payload)

        self.assertFalse(UserInterview.objects.filter(team=self.team).exists())

    def test_task_stores_the_report(self):
        self._run(self._report())

        interview = UserInterview.objects.get(team=self.team)
        self.assertEqual(interview.topic, self.topic)
        self.assertEqual(interview.interviewee_identifier, "alex@example.com")
        self.assertEqual(interview.transcript, "Hi! ...")
        self.assertEqual(interview.recording_url, "https://vapi.example/recording.mp3")
        # The report can wait in the queue through an outage, so the interview keeps the time the
        # endpoint accepted it rather than the time the worker got to it.
        self.assertEqual(interview.created_at.isoformat(), "2026-05-14T12:00:00+00:00")

    def test_task_serializes_persistence_per_call_id(self):
        # No unique constraint keeps a call to one row, so two runs that overlap have to queue
        # behind an advisory lock on the call id instead of both passing the existence check.
        with CaptureQueriesContext(connection) as queries:
            self._run(self._report(call_id="call_xyz"))

        statements = [query["sql"] for query in queries.captured_queries]
        locks = [index for index, sql in enumerate(statements) if "pg_advisory_xact_lock" in sql]
        inserts = [index for index, sql in enumerate(statements) if "INSERT INTO" in sql and "userinterview" in sql]
        self.assertEqual(len(locks), 1)
        self.assertIn(f"user_interviews_vapi_call:{self.team.id}:call_xyz", statements[locks[0]])
        self.assertTrue(inserts)
        self.assertLess(locks[0], inserts[0])

    def test_a_second_run_of_the_same_call_stores_nothing(self):
        # The task acknowledges late and retries a transient database error, so one call can
        # reach two runs.
        payload = self._report()
        self._run(payload)
        self._run(payload)

        self.assertEqual(UserInterview.objects.filter(team=self.team).count(), 1)
