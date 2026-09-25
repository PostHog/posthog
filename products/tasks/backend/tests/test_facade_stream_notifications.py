import json

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.tasks.backend.facade.api import (
    parse_task_run_log_entries,
    publish_task_run_stream_notification,
    read_task_run_history,
    read_task_run_stream_entries,
)
from products.tasks.backend.facade.contracts import StreamNotificationDelivery
from products.tasks.backend.logic.stream.redis_stream import get_task_run_stream_key, publish_task_run_stream_event
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.redis import get_tasks_stream_redis_sync

USER_PROMPT = {"type": "notification", "notification": {"method": "_posthog/user_message", "params": {}}}
SERVER_NOTIFICATION = {
    "type": "notification",
    "timestamp": "2026-01-01T00:00:00+00:00",
    "notification": {"jsonrpc": "2.0", "method": "_posthog/turn_suggestion", "params": {}},
}


def _frame(event_id: str) -> dict:
    return {"type": "notification", "event_id": event_id, "notification": {"method": "session/update"}}


def _frame_without_id() -> dict:
    return {"type": "notification", "notification": {"method": "session/update"}}


def _stamped_at(entry: dict, timestamp: str) -> dict:
    return {**entry, "timestamp": timestamp}


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
        self.task_run = task.create_run(
            mode="interactive",
            extra_state={"use_dedicated_stream": False, "stream_presence_gated": False},
        )
        stream_key = get_task_run_stream_key(str(self.task_run.id))
        get_tasks_stream_redis_sync().delete(stream_key)
        self.addCleanup(get_tasks_stream_redis_sync().delete, stream_key)

    def _entries(self, team_id: int | None = None) -> list[dict]:
        return read_task_run_stream_entries(self.task_run.id, self.task_run.task_id, team_id or self.team.id)

    def _publish(self, params: dict, team_id: int | None = None, persist: bool = True) -> StreamNotificationDelivery:
        return publish_task_run_stream_notification(
            self.task_run.id,
            self.task_run.task_id,
            team_id or self.team.id,
            "_posthog/turn_suggestion",
            params,
            persist=persist,
        )

    def _history(self, max_bytes: int = 1024) -> list[dict] | None:
        return read_task_run_history(self.task_run.id, self.task_run.task_id, self.team.id, max_bytes=max_bytes)

    @parameterized.expand([("persisted", True), ("live_only", False)])
    def test_notification_reaches_the_live_stream_and_the_log_when_persisted(self, _name: str, persist: bool):
        with patch.object(TaskRun, "append_log") as append_log:
            assert self._publish({"turnIndex": 0}, persist=persist) == StreamNotificationDelivery(
                live=True, persisted=persist
            )

        live = self._entries()[-1]
        assert live["notification"] == {
            "jsonrpc": "2.0",
            "method": "_posthog/turn_suggestion",
            "params": {"turnIndex": 0},
        }
        assert live["timestamp"]
        if persist:
            append_log.assert_called_once_with([live], lock_attempts=1)
        else:
            append_log.assert_not_called()

    def test_log_append_failure_still_reports_the_live_write(self):
        before = len(self._entries())

        with patch.object(TaskRun, "append_log", side_effect=RuntimeError("lock busy")):
            assert self._publish({}) == StreamNotificationDelivery(live=True, persisted=False)

        assert len(self._entries()) == before + 1

    def test_a_run_outside_the_team_publishes_nothing(self):
        assert self._publish({}, team_id=self.team.id + 1) == StreamNotificationDelivery(live=False, persisted=False)
        assert self._entries(team_id=self.team.id + 1) == []

    def test_parse_task_run_log_entries_skips_lines_that_are_not_objects(self):
        content = "\n".join([json.dumps({"type": "notification"}), "not json", json.dumps([1, 2]), "", "{}"])

        assert list(parse_task_run_log_entries(content)) == [{"type": "notification"}, {}]

    @parameterized.expand(
        [
            # No event ids and a user prompt: the stream holds the whole run, so its log is not read.
            ("unstamped_stream_stands_in_for_the_log", [USER_PROMPT], [_frame("b-1")], [USER_PROMPT]),
            # Stamped ids: the log comes first and the stream adds only what the log has not caught up with.
            (
                "stamped_stream_adds_its_tail",
                [_frame("b-1"), _frame("b-2")],
                [_frame("b-1")],
                [_frame("b-1"), _frame("b-2")],
            ),
            # No user prompt: a stream of server frames alone does not replace the log.
            (
                "server_frames_do_not_replace_the_log",
                [{"type": "notification"}],
                [_frame("b-1")],
                [_frame("b-1"), {"type": "notification"}],
            ),
            # A persisted server notification sits in both stores without an id, and appears once.
            (
                "persisted_server_notification_appears_once",
                [_frame("b-1"), SERVER_NOTIFICATION],
                [_frame("b-1"), SERVER_NOTIFICATION],
                [_frame("b-1"), SERVER_NOTIFICATION],
            ),
            # A persisted server notification whose live write was skipped comes from the log, in timestamp order.
            (
                "unstamped_stream_keeps_a_server_notification_only_the_log_holds",
                [USER_PROMPT, _stamped_at(_frame_without_id(), "2026-01-01T00:00:01+00:00")],
                [_frame("b-1"), SERVER_NOTIFICATION],
                [USER_PROMPT, SERVER_NOTIFICATION, _stamped_at(_frame_without_id(), "2026-01-01T00:00:01+00:00")],
            ),
            # An unstamped stream at the length cap may be a trimmed tail, so the log is still read.
            (
                "unstamped_stream_at_the_cap_keeps_the_log",
                [USER_PROMPT, USER_PROMPT],
                [_frame("b-1")],
                [_frame("b-1"), USER_PROMPT, USER_PROMPT],
                2,
            ),
        ]
    )
    def test_history_merges_the_log_and_the_live_stream(
        self, _name: str, stream: list[dict], log: list[dict], expected: list[dict], stream_cap: int = 5_000
    ):
        for event in stream:
            publish_task_run_stream_event(str(self.task_run.id), event)
        log_content = "\n".join(json.dumps(entry) for entry in log)

        with (
            patch("posthog.storage.object_storage.head_object", return_value={"ContentLength": len(log_content)}),
            patch("posthog.storage.object_storage.read", return_value=log_content),
            patch("products.tasks.backend.logic.stream.redis_stream.TASK_RUN_STREAM_MAX_LENGTH", stream_cap),
        ):
            assert self._history() == expected

    def test_history_over_the_byte_cap_downloads_nothing(self):
        with (
            patch("posthog.storage.object_storage.head_object", return_value={"ContentLength": 2048}),
            patch("posthog.storage.object_storage.read") as read,
        ):
            assert self._history(max_bytes=1024) is None

        read.assert_not_called()
