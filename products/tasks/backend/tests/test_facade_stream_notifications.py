import json

from posthog.test.base import BaseTest
from unittest.mock import patch

from products.tasks.backend.facade.api import (
    parse_task_run_log_entries,
    publish_task_run_stream_notification,
    read_task_run_stream_entries,
)
from products.tasks.backend.logic.stream.redis_stream import get_task_run_stream_key
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.redis import get_tasks_stream_redis_sync


class TestStreamNotifications(BaseTest):
    def setUp(self):
        super().setUp()
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        self.task_run = task.create_run(mode="interactive")
        self.addCleanup(get_tasks_stream_redis_sync().delete, get_task_run_stream_key(str(self.task_run.id)))

    def test_notification_reaches_the_live_stream_and_the_log(self):
        with patch.object(TaskRun, "append_log") as append_log:
            assert publish_task_run_stream_notification(self.task_run.id, "_posthog/turn_suggestion", {"turnIndex": 0})

        expected = {
            "type": "notification",
            "notification": {"method": "_posthog/turn_suggestion", "params": {"turnIndex": 0}},
        }
        # Creating the run already mirrored a state frame into the stream; the notification lands after it.
        assert read_task_run_stream_entries(self.task_run.id)[-1] == expected
        append_log.assert_called_once_with([expected], lock_attempts=1)

    def test_log_append_failure_does_not_fail_the_live_write(self):
        before = len(read_task_run_stream_entries(self.task_run.id))

        with patch.object(TaskRun, "append_log", side_effect=RuntimeError("lock busy")):
            assert publish_task_run_stream_notification(self.task_run.id, "_posthog/turn_suggestion", {})

        assert len(read_task_run_stream_entries(self.task_run.id)) == before + 1

    def test_unknown_run_publishes_nothing(self):
        assert publish_task_run_stream_notification("00000000-0000-0000-0000-000000000000", "_posthog/x", {}) is False
        assert read_task_run_stream_entries("00000000-0000-0000-0000-000000000000") == []

    def test_parse_task_run_log_entries_skips_lines_that_are_not_objects(self):
        content = "\n".join([json.dumps({"type": "notification"}), "not json", json.dumps([1, 2]), "", "{}"])

        assert parse_task_run_log_entries(content) == [{"type": "notification"}, {}]
