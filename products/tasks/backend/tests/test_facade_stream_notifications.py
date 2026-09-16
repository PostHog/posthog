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

    def _entries(self, team_id: int | None = None) -> list[dict]:
        return read_task_run_stream_entries(self.task_run.id, self.task_run.task_id, team_id or self.team.id)

    def _publish(self, params: dict, team_id: int | None = None) -> bool:
        return publish_task_run_stream_notification(
            self.task_run.id, self.task_run.task_id, team_id or self.team.id, "_posthog/turn_suggestion", params
        )

    def test_notification_reaches_the_live_stream_and_the_log(self):
        with patch.object(TaskRun, "append_log") as append_log:
            assert self._publish({"turnIndex": 0})

        expected = {
            "type": "notification",
            "notification": {"method": "_posthog/turn_suggestion", "params": {"turnIndex": 0}},
        }
        # Creating the run already mirrored a state frame into the stream; the notification lands after it.
        assert self._entries()[-1] == expected
        append_log.assert_called_once_with([expected], lock_attempts=1)

    def test_log_append_failure_still_counts_the_live_write(self):
        before = len(self._entries())

        with patch.object(TaskRun, "append_log", side_effect=RuntimeError("lock busy")):
            assert self._publish({})

        assert len(self._entries()) == before + 1

    def test_a_run_outside_the_team_publishes_nothing(self):
        assert self._publish({}, team_id=self.team.id + 1) is False
        assert self._entries(team_id=self.team.id + 1) == []

    def test_parse_task_run_log_entries_skips_lines_that_are_not_objects(self):
        content = "\n".join([json.dumps({"type": "notification"}), "not json", json.dumps([1, 2]), "", "{}"])

        assert list(parse_task_run_log_entries(content)) == [{"type": "notification"}, {}]
