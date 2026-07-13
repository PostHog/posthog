import json
import asyncio
import threading
from collections.abc import Sequence

from unittest.mock import patch

from django.db import OperationalError
from django.test import TestCase, override_settings

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.models import Organization, Team, User
from posthog.redis import TEST_clear_clients

from products.tasks.backend.logic.services.connection_token import (
    SANDBOX_EVENT_INGEST_TOKEN_TTL,
    create_sandbox_connection_token,
    create_sandbox_event_ingest_token,
    reset_sandbox_jwt_key_cache,
)
from products.tasks.backend.logic.services.sandbox_config import SANDBOX_TTL_SECONDS
from products.tasks.backend.logic.stream.event_ingest import (
    MAX_EVENT_LINE_BYTES,
    MAX_EVENTS_PER_REQUEST,
    STREAM_COMPLETE_CONTROL_TYPE,
    handle_task_run_event_ingest,
)
from products.tasks.backend.logic.stream.redis_stream import (
    TASK_RUN_STREAM_SEQUENCE_TIMEOUT,
    TASK_RUN_STREAM_TIMEOUT,
    TaskRunRedisStream,
    get_task_run_stream_completed_key,
    get_task_run_stream_key,
    get_task_run_stream_sequence_key,
)
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.tests.test_api import TEST_RSA_PRIVATE_KEY


class TestTaskRunEventIngest(TestCase):
    def setUp(self) -> None:
        super().setUp()
        TEST_clear_clients()
        reset_sandbox_jwt_key_cache()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self.task_run: TaskRun = self.task.create_run()
        self._delete_run_stream()

    def tearDown(self) -> None:
        self._delete_run_stream()
        TEST_clear_clients()
        reset_sandbox_jwt_key_cache()
        super().tearDown()

    def _delete_run_stream(self) -> None:
        async def _delete_stream() -> None:
            redis_stream = TaskRunRedisStream(get_task_run_stream_key(str(self.task_run.id)))
            await redis_stream.delete_stream()

        asyncio.run(_delete_stream())

    def _ingest_url(
        self,
        task: Task | None = None,
        run: TaskRun | None = None,
        project_id: str | int | None = None,
    ) -> str:
        task = task or self.task
        run = run or self.task_run
        project_id = project_id if project_id is not None else self.team.id
        return f"/api/projects/{project_id}/tasks/{task.id}/runs/{run.id}/event_stream/"

    def _create_token(self, run: TaskRun | None = None) -> str:
        return create_sandbox_event_ingest_token(run or self.task_run)

    def _call_ingest(
        self,
        token: str,
        lines: Sequence[dict],
        path: str | None = None,
    ) -> tuple[int, dict]:
        body = "".join(json.dumps(line) + "\n" for line in lines).encode("utf-8")
        return self._call_ingest_chunks(
            token,
            [body[: len(body) // 2], body[len(body) // 2 :]],
            path=path,
        )

    def _call_ingest_chunks(
        self,
        token: str,
        chunks: Sequence[bytes],
        path: str | None = None,
    ) -> tuple[int, dict]:
        async def _call() -> tuple[int, dict]:
            messages = [
                {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
                for index, chunk in enumerate(chunks)
            ]
            sent: list[dict] = []

            async def receive() -> dict:
                return messages.pop(0)

            async def send(message: dict) -> None:
                sent.append(message)

            headers = [(b"authorization", f"Bearer {token}".encode())]

            handled = await handle_task_run_event_ingest(
                {
                    "type": "http",
                    "method": "POST",
                    "path": path or self._ingest_url(),
                    "headers": headers,
                },
                receive,
                send,
            )
            self.assertTrue(handled)
            status = sent[0]["status"]
            body = json.loads(sent[1]["body"])
            return status, body

        # async_to_sync (not asyncio.run) so the handler's thread_sensitive DB
        # access runs on the test thread's connection and sees uncommitted rows.
        return async_to_sync(_call)()

    def _read_stream_events(self) -> list[dict]:
        async def _read() -> list[dict]:
            redis_stream = TaskRunRedisStream(get_task_run_stream_key(str(self.task_run.id)))
            messages = await redis_stream._redis_client.xrange(get_task_run_stream_key(str(self.task_run.id)))
            return [json.loads(message[b"data"]) for _, message in messages]

        return asyncio.run(_read())

    def _seed_stream_events(self, events: Sequence[tuple[int, dict]]) -> None:
        async def _seed() -> None:
            redis_stream = TaskRunRedisStream(get_task_run_stream_key(str(self.task_run.id)))
            for sequence, event in events:
                await redis_stream.write_event_with_sequence(event, sequence)

        asyncio.run(_seed())

    def _read_notification_methods(self) -> list[str]:
        methods: list[str] = []
        for event in self._read_stream_events():
            notification = event.get("notification")
            if isinstance(notification, dict) and isinstance(notification.get("method"), str):
                methods.append(notification["method"])
        return methods

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_streaming_ingest_writes_ordered_events_with_explicit_completion(self) -> None:
        token = self._create_token()

        with patch.object(TaskRun, "heartbeat_workflow") as heartbeat_workflow:
            status, body = self._call_ingest(
                token,
                [
                    {
                        "seq": 1,
                        "event": {"type": "notification", "notification": {"method": "session/update"}},
                    },
                    {
                        "seq": 2,
                        "event": {"type": "notification", "notification": {"method": "_posthog/task_complete"}},
                    },
                    {"type": STREAM_COMPLETE_CONTROL_TYPE, "final_seq": 2},
                ],
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], 2)
        self.assertEqual(body["last_accepted_seq"], 2)
        heartbeat_workflow.assert_called_once_with(agent_active=True)

        events = self._read_stream_events()
        self.assertEqual(self._read_notification_methods(), ["session/update", "_posthog/task_complete"])
        self.assertIn({"type": "STREAM_STATUS", "status": "complete"}, events)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_current_project_path_ingests_with_token_scoped_task_run(self) -> None:
        token = self._create_token()

        status, body = self._call_ingest(
            token,
            [{"seq": 1, "event": {"type": "notification", "notification": {"method": "session/update"}}}],
            path=self._ingest_url(project_id="@current"),
        )

        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], 1)
        self.assertEqual(self._read_notification_methods(), ["session/update"])

    @parameterized.expand([(True,), (False,)])
    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_turn_complete_ingest_notifies_interactive_run_awaiting_input_only_with_flag(
        self, flag_enabled: bool
    ) -> None:
        self.task.created_by = User.objects.create_user("ingest-push@posthog.com", None, "Ingest")
        self.task.save(update_fields=["created_by"])
        self.task_run.state = {"mode": "interactive"}
        self.task_run.save(update_fields=["state"])
        token = self._create_token()

        with (
            patch(
                "products.tasks.backend.logic.stream.event_ingest.notify_task_run_awaiting_input"
            ) as notify_awaiting_input,
            patch(
                "products.tasks.backend.logic.stream.event_ingest.posthoganalytics.feature_enabled",
                return_value=flag_enabled,
            ),
        ):
            status, body = self._call_ingest(
                token,
                [
                    {
                        "seq": 1,
                        "event": {
                            "type": "notification",
                            "notification": {"method": "_posthog/turn_complete"},
                        },
                    }
                ],
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], 1)
        if flag_enabled:
            notify_awaiting_input.assert_called_once()
            self.assertEqual(notify_awaiting_input.call_args.args[0].id, self.task_run.id)
        else:
            notify_awaiting_input.assert_not_called()

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_workflow_heartbeat_does_not_block_event_loop(self) -> None:
        token = self._create_token()
        heartbeat_entered = threading.Event()
        heartbeat_released = threading.Event()
        heartbeat_timed_out = threading.Event()

        def blocking_heartbeat(_run_id: str, _agent_active: bool) -> None:
            heartbeat_entered.set()
            if not heartbeat_released.wait(timeout=1):
                heartbeat_timed_out.set()

        async def _call() -> tuple[int, dict]:
            body = (
                json.dumps(
                    {
                        "seq": 1,
                        "event": {"type": "notification", "notification": {"method": "session/update"}},
                    }
                )
                + "\n"
            ).encode("utf-8")
            messages = [{"type": "http.request", "body": body, "more_body": False}]
            sent: list[dict] = []

            async def receive() -> dict:
                return messages.pop(0)

            async def send(message: dict) -> None:
                sent.append(message)

            async def release_heartbeat_from_event_loop() -> None:
                for _ in range(1000):
                    if heartbeat_entered.is_set():
                        break
                    await asyncio.sleep(0.001)
                heartbeat_released.set()

            await asyncio.gather(
                handle_task_run_event_ingest(
                    {
                        "type": "http",
                        "method": "POST",
                        "path": self._ingest_url(),
                        "headers": [(b"authorization", f"Bearer {token}".encode())],
                    },
                    receive,
                    send,
                ),
                release_heartbeat_from_event_loop(),
            )
            return sent[0]["status"], json.loads(sent[1]["body"])

        with patch(
            "products.tasks.backend.logic.stream.event_ingest._heartbeat_workflow", side_effect=blocking_heartbeat
        ):
            status, body = async_to_sync(_call)()

        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], 1)
        self.assertTrue(heartbeat_entered.is_set())
        self.assertFalse(heartbeat_timed_out.is_set())

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_duplicate_sequence_is_skipped_on_reconnect(self) -> None:
        token = self._create_token()

        self._seed_stream_events([(1, {"type": "notification", "notification": {"method": "first"}})])

        with patch.object(TaskRun, "heartbeat_workflow"):
            status, body = self._call_ingest(
                token,
                [
                    {"seq": 1, "event": {"type": "notification", "notification": {"method": "first"}}},
                    {"seq": 2, "event": {"type": "notification", "notification": {"method": "second"}}},
                ],
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], 1)
        self.assertEqual(body["duplicate"], 1)
        self.assertEqual(body["last_accepted_seq"], 2)
        self.assertEqual(self._read_notification_methods(), ["first", "second"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_duplicate_terminal_sequence_does_not_complete_without_completion_line(self) -> None:
        token = self._create_token()
        terminal_event = {"type": "notification", "notification": {"method": "_posthog/task_complete"}}

        self._seed_stream_events([(1, terminal_event)])

        with patch.object(TaskRun, "heartbeat_workflow"):
            status, body = self._call_ingest(token, [{"seq": 1, "event": terminal_event}])

        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], 0)
        self.assertEqual(body["duplicate"], 1)
        self.assertEqual(body["last_accepted_seq"], 1)
        self.assertNotIn({"type": "STREAM_STATUS", "status": "complete"}, self._read_stream_events())

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_duplicate_terminal_sequence_can_complete_with_completion_line(self) -> None:
        token = self._create_token()
        terminal_event = {"type": "notification", "notification": {"method": "_posthog/task_complete"}}

        self._seed_stream_events([(1, terminal_event)])

        with patch.object(TaskRun, "heartbeat_workflow"):
            status, body = self._call_ingest(
                token,
                [{"seq": 1, "event": terminal_event}, {"type": STREAM_COMPLETE_CONTROL_TYPE, "final_seq": 1}],
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], 0)
        self.assertEqual(body["duplicate"], 1)
        self.assertEqual(body["last_accepted_seq"], 1)
        self.assertIn({"type": "STREAM_STATUS", "status": "complete"}, self._read_stream_events())

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_completion_control_line_completes_after_streamed_events(self) -> None:
        token = self._create_token()

        status, body = self._call_ingest(
            token,
            [
                {
                    "seq": 1,
                    "event": {"type": "notification", "notification": {"method": "session/update"}},
                },
                {
                    "seq": 2,
                    "event": {"type": "notification", "notification": {"method": "_posthog/task_complete"}},
                },
                {"type": STREAM_COMPLETE_CONTROL_TYPE, "final_seq": 2},
            ],
        )

        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], 2)
        self.assertEqual(body["last_accepted_seq"], 2)
        events = self._read_stream_events()
        self.assertEqual(self._read_notification_methods(), ["session/update", "_posthog/task_complete"])
        self.assertIn({"type": "STREAM_STATUS", "status": "complete"}, events)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_completion_control_line_rejects_unaccepted_final_sequence(self) -> None:
        token = self._create_token()

        status, body = self._call_ingest(
            token,
            [
                {
                    "seq": 1,
                    "event": {"type": "notification", "notification": {"method": "session/update"}},
                },
                {"type": STREAM_COMPLETE_CONTROL_TYPE, "final_seq": 2},
            ],
        )

        self.assertEqual(status, 409)
        self.assertEqual(body["last_accepted_seq"], 1)
        self.assertNotIn({"type": "STREAM_STATUS", "status": "complete"}, self._read_stream_events())

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_completion_control_line_must_be_final_line(self) -> None:
        token = self._create_token()

        status, body = self._call_ingest(
            token,
            [
                {"type": STREAM_COMPLETE_CONTROL_TYPE, "final_seq": 0},
                {
                    "seq": 1,
                    "event": {"type": "notification", "notification": {"method": "session/update"}},
                },
            ],
        )

        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "Completion line must be the final event stream line")
        self.assertNotIn({"type": "STREAM_STATUS", "status": "complete"}, self._read_stream_events())
        self.assertEqual(self._read_notification_methods(), [])

    @parameterized.expand(
        [
            ("missing_final_seq", {"type": STREAM_COMPLETE_CONTROL_TYPE}),
            ("negative_final_seq", {"type": STREAM_COMPLETE_CONTROL_TYPE, "final_seq": -1}),
            ("string_final_seq", {"type": STREAM_COMPLETE_CONTROL_TYPE, "final_seq": "1"}),
        ]
    )
    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_completion_control_line_rejects_invalid_final_sequence(self, _case_name: str, line: dict) -> None:
        token = self._create_token()

        status, body = self._call_ingest(token, [line])

        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "Completion final sequence must be a non-negative integer")

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_sequence_gap_returns_last_accepted_sequence(self) -> None:
        token = self._create_token()

        self._seed_stream_events([(1, {"type": "notification", "notification": {"method": "first"}})])

        status, body = self._call_ingest(
            token,
            [{"seq": 3, "event": {"type": "notification", "notification": {"method": "third"}}}],
        )

        self.assertEqual(status, 409)
        self.assertEqual(body["last_accepted_seq"], 1)
        self.assertEqual(self._read_notification_methods(), ["first"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_completed_stream_rejects_late_sequenced_events(self) -> None:
        token = self._create_token()

        async def _seed_and_complete_stream() -> None:
            stream_key = get_task_run_stream_key(str(self.task_run.id))
            redis_stream = TaskRunRedisStream(stream_key)
            # This test needs a completed stream fixture; sequencing writes are covered separately.
            await redis_stream.write_event({"type": "notification", "notification": {"method": "first"}})
            await redis_stream.write_event({"type": "STREAM_STATUS", "status": "complete"})
            await redis_stream._redis_client.set(
                get_task_run_stream_sequence_key(stream_key),
                1,
                ex=TASK_RUN_STREAM_SEQUENCE_TIMEOUT,
            )
            await redis_stream._redis_client.set(
                get_task_run_stream_completed_key(stream_key),
                "1",
                ex=TASK_RUN_STREAM_SEQUENCE_TIMEOUT,
            )

        asyncio.run(_seed_and_complete_stream())

        status, body = self._call_ingest(
            token,
            [{"seq": 2, "event": {"type": "notification", "notification": {"method": "late"}}}],
        )

        self.assertEqual(status, 409)
        self.assertEqual(body["last_accepted_seq"], 1)
        self.assertIn({"type": "STREAM_STATUS", "status": "complete"}, self._read_stream_events())
        self.assertEqual(self._read_notification_methods(), ["first"])

    def test_live_stream_ttl_matches_sandbox_ttl(self) -> None:
        async def _write_and_get_ttl() -> int:
            stream_key = get_task_run_stream_key(str(self.task_run.id))
            redis_stream = TaskRunRedisStream(stream_key)
            await redis_stream.write_event({"type": "notification", "notification": {"method": "first"}})
            return await redis_stream._redis_client.ttl(stream_key)

        stream_ttl = asyncio.run(_write_and_get_ttl())

        self.assertEqual(TASK_RUN_STREAM_TIMEOUT, SANDBOX_TTL_SECONDS)
        self.assertGreater(stream_ttl, SANDBOX_TTL_SECONDS - 5)
        self.assertLessEqual(stream_ttl, SANDBOX_TTL_SECONDS)

    def test_sequence_key_ttl_outlives_live_stream_ttl(self) -> None:
        async def _write_and_get_ttls() -> tuple[int, int]:
            stream_key = get_task_run_stream_key(str(self.task_run.id))
            redis_stream = TaskRunRedisStream(stream_key, timeout=5)
            await redis_stream.write_event_with_sequence(
                {"type": "notification", "notification": {"method": "first"}},
                1,
            )
            return (
                await redis_stream._redis_client.ttl(stream_key),
                await redis_stream._redis_client.ttl(get_task_run_stream_sequence_key(stream_key)),
            )

        stream_ttl, sequence_ttl = asyncio.run(_write_and_get_ttls())

        self.assertGreater(stream_ttl, 0)
        self.assertLessEqual(stream_ttl, 5)
        self.assertEqual(TASK_RUN_STREAM_SEQUENCE_TIMEOUT, int(SANDBOX_EVENT_INGEST_TOKEN_TTL.total_seconds()))
        self.assertGreater(sequence_ttl, TASK_RUN_STREAM_SEQUENCE_TIMEOUT - 5)
        self.assertLessEqual(sequence_ttl, TASK_RUN_STREAM_SEQUENCE_TIMEOUT)
        self.assertGreater(sequence_ttl, stream_ttl)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_non_terminal_request_close_does_not_complete(self) -> None:
        token = self._create_token()

        status, body = self._call_ingest(
            token,
            [{"seq": 1, "event": {"type": "notification", "notification": {"method": "session/update"}}}],
        )

        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], 1)
        self.assertNotIn({"type": "STREAM_STATUS", "status": "complete"}, self._read_stream_events())

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_empty_request_returns_last_accepted_sequence(self) -> None:
        token = self._create_token()

        self._seed_stream_events(
            [
                (1, {"type": "notification", "notification": {"method": "first"}}),
                (2, {"type": "notification", "notification": {"method": "second"}}),
            ]
        )

        status, body = self._call_ingest(token, [])

        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], 0)
        self.assertEqual(body["last_accepted_seq"], 2)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_multibyte_utf8_can_span_request_chunks(self) -> None:
        token = self._create_token()
        line = (
            json.dumps(
                {
                    "seq": 1,
                    "event": {
                        "type": "notification",
                        "notification": {"method": "_posthog/console", "params": {"message": "hello ☃"}},
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
        split_at = line.index("☃".encode()) + 1

        status, body = self._call_ingest_chunks(token, [line[:split_at], line[split_at:]])

        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], 1)
        events = self._read_stream_events()
        notifications = [event["notification"] for event in events if "notification" in event]
        self.assertEqual(notifications[-1]["params"]["message"], "hello ☃")

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_connection_token_cannot_ingest_events(self) -> None:
        token = create_sandbox_connection_token(self.task_run, user_id=1, distinct_id="user-1")

        status, body = self._call_ingest(
            token,
            [{"seq": 1, "event": {"type": "notification", "notification": {"method": "session/update"}}}],
        )

        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "Invalid event ingest token")

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_stale_db_connection_during_authorization_retries(self) -> None:
        # A stale pooled connection makes the run-existence check raise OperationalError.
        # Without the retry this crashes the ingest mid-stream; the reconnect must recover it.
        token = self._create_token()

        real_exists = TaskRun.objects.filter(id=self.task_run.id).exists()
        self.assertTrue(real_exists)

        with patch(
            "products.tasks.backend.logic.stream.event_ingest._task_run_exists_sync",
            side_effect=[OperationalError("server closed the connection unexpectedly"), True],
        ) as exists_sync:
            status, body = self._call_ingest(
                token,
                [{"seq": 1, "event": {"type": "notification", "notification": {"method": "session/update"}}}],
            )

        self.assertEqual(exists_sync.call_count, 2)
        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], 1)
        self.assertEqual(self._read_notification_methods(), ["session/update"])

    @parameterized.expand(
        [
            ("single_oversized_line", False, 0, []),
            ("accepted_prefix_before_oversized_line", True, 1, ["first"]),
        ]
    )
    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_rejects_oversized_event_line_cases(
        self,
        _case_name: str,
        include_accepted_prefix: bool,
        expected_last_accepted_seq: int,
        expected_notification_methods: Sequence[str],
    ) -> None:
        token = self._create_token()
        chunks: list[bytes] = []
        if include_accepted_prefix:
            chunks.append(
                (
                    json.dumps({"seq": 1, "event": {"type": "notification", "notification": {"method": "first"}}})
                    + "\n"
                ).encode("utf-8")
            )

        oversized_line = (
            json.dumps(
                {
                    "seq": 2 if include_accepted_prefix else 1,
                    "event": {
                        "type": "notification",
                        "notification": {
                            "method": "_posthog/console",
                            "params": {"message": "x" * MAX_EVENT_LINE_BYTES},
                        },
                    },
                },
            )
        ).encode("utf-8")
        chunks.append(oversized_line)

        status, body = self._call_ingest_chunks(token, [b"".join(chunks)])

        self.assertEqual(status, 413)
        self.assertEqual(body["error"], "Event line is too large")
        self.assertEqual(body["last_accepted_seq"], expected_last_accepted_seq)
        self.assertEqual(self._read_notification_methods(), expected_notification_methods)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_rejects_too_many_events_in_single_request(self) -> None:
        token = self._create_token()
        lines = [
            {"seq": sequence, "event": {"type": "notification", "notification": {"method": "session/update"}}}
            for sequence in range(1, MAX_EVENTS_PER_REQUEST + 2)
        ]

        status, body = self._call_ingest(token, lines)

        self.assertEqual(status, 413)
        self.assertEqual(body["error"], "Too many events in request")
        self.assertEqual(body["last_accepted_seq"], MAX_EVENTS_PER_REQUEST)

    @parameterized.expand(
        [
            (
                "initial_console",
                [
                    {
                        "seq": 1,
                        "event": {
                            "type": "notification",
                            "notification": {"method": "_posthog/console", "params": {"message": "starting"}},
                        },
                    }
                ],
                1,
            ),
            (
                "turn_complete_then_console",
                [
                    {
                        "seq": 1,
                        "event": {
                            "type": "notification",
                            "notification": {
                                "method": "_posthog/turn_complete",
                                "params": {"stopReason": "end_turn"},
                            },
                        },
                    },
                    {
                        "seq": 2,
                        "event": {
                            "type": "notification",
                            "notification": {"method": "_posthog/console", "params": {"message": "tail"}},
                        },
                    },
                ],
                2,
            ),
        ]
    )
    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_inactive_agent_events_do_not_heartbeat_workflow(
        self, _case_name: str, lines: Sequence[dict], expected_accepted: int
    ) -> None:
        token = self._create_token()

        with patch.object(TaskRun, "heartbeat_workflow") as heartbeat_workflow:
            status, body = self._call_ingest(token, lines)

        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], expected_accepted)
        heartbeat_workflow.assert_not_called()
