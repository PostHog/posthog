from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

from posthog.admin import register_all_admin
from posthog.models.user import User
from posthog.redis import get_client

from products.workflows.backend.services.ses_events_dlq import DlqQueue, ReplayOptions
from products.workflows.backend.services.ses_events_dlq_runs import recent_runs, start_run
from products.workflows.backend.tasks.ses_events_dlq import replay_ses_events_dlq_task
from products.workflows.backend.test.test_ses_events_dlq import QUEUE, FakeSqs, sns_message

REPLAY_URL = "/admin/workflows/hogflow/ses-events-dlq/replay/"


def clear_runs() -> None:
    redis = get_client()
    for key in redis.keys("workflows:ses_events_dlq:*"):
        redis.delete(key)


@override_settings(SES_EVENTS_DLQ_URLS=[QUEUE.url])
class TestSesEventsDlqReplayView(TestCase):
    def setUp(self) -> None:
        super().setUp()
        register_all_admin()
        clear_runs()
        self.staff = User.objects.create(email="staff@example.com", is_staff=True)

    @patch("products.workflows.backend.admin.ses_events_dlq_admin.replay_ses_events_dlq_task")
    def test_a_second_submit_while_a_run_holds_the_queue_starts_nothing(self, task: MagicMock) -> None:
        self.client.force_login(self.staff)
        form = {"queue": QUEUE.name, "limit": "50", "max_per_second": "5"}

        self.client.post(REPLAY_URL, form)
        self.client.post(REPLAY_URL, form)

        assert task.delay.call_count == 1
        assert task.delay.call_args.kwargs | {"run_id": None} == {
            "run_id": None,
            "queue_name": QUEUE.name,
            "dry_run": False,
            "limit": 50,
            "max_per_second": 5.0,
            "triggered_by": "staff@example.com",
        }
        assert [run["triggered_by"] for run in recent_runs()] == ["staff@example.com"]

    @patch("products.workflows.backend.admin.ses_events_dlq_admin.replay_ses_events_dlq_task")
    def test_a_run_whose_task_cannot_be_queued_fails_and_frees_the_queue(self, task: MagicMock) -> None:
        self.client.force_login(self.staff)
        form = {"queue": QUEUE.name, "limit": "50", "max_per_second": "5"}
        task.delay.side_effect = [ConnectionError("broker down"), None]

        self.client.post(REPLAY_URL, form)
        self.client.post(REPLAY_URL, form)

        assert task.delay.call_count == 2
        assert [run["status"] for run in recent_runs()] == ["queued", "failed"]

    @patch("products.workflows.backend.admin.ses_events_dlq_admin.replay_ses_events_dlq_task")
    def test_non_staff_cannot_start_a_replay(self, task: MagicMock) -> None:
        self.client.force_login(User.objects.create(email="member@example.com"))

        self.client.post(REPLAY_URL, {"queue": QUEUE.name, "limit": "50", "max_per_second": "5"})

        task.delay.assert_not_called()


@override_settings(SES_EVENTS_DLQ_URLS=[QUEUE.url])
class TestReplaySesEventsDlqTask(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        clear_runs()

    def test_a_finished_run_keeps_its_report_and_frees_the_queue(self) -> None:
        options = ReplayOptions(dry_run=True, limit=10, max_per_second=5)
        run_id = start_run(QUEUE, options, "staff@example.com")
        assert run_id is not None

        with patch(
            "products.workflows.backend.tasks.ses_events_dlq.sqs_client",
            return_value=FakeSqs([sns_message("a", "Bounce"), sns_message("b", "Click")]),
        ):
            replay_ses_events_dlq_task(
                run_id=run_id,
                queue_name=QUEUE.name,
                dry_run=True,
                limit=10,
                max_per_second=5,
                triggered_by="staff@example.com",
            )

        [run] = recent_runs()
        assert (run["status"], run["report"]["totals"]) == ("finished", {"would_replay": 2})
        assert start_run(DlqQueue(url=QUEUE.url), options, "staff@example.com") is not None

    def test_a_task_that_starts_after_another_run_took_its_queue_reads_nothing(self) -> None:
        options = ReplayOptions(dry_run=False, limit=10, max_per_second=5)
        run_id = start_run(QUEUE, options, "staff@example.com")
        assert run_id is not None
        get_client().set(f"workflows:ses_events_dlq:lock:{QUEUE.name}", "a-later-run")

        with patch("products.workflows.backend.tasks.ses_events_dlq.sqs_client") as sqs_client:
            replay_ses_events_dlq_task(
                run_id=run_id,
                queue_name=QUEUE.name,
                dry_run=False,
                limit=10,
                max_per_second=5,
                triggered_by="staff@example.com",
            )

        sqs_client.assert_not_called()
        [run] = recent_runs()
        assert run["status"] == "failed"
        assert get_client().get(f"workflows:ses_events_dlq:lock:{QUEUE.name}") == b"a-later-run"
