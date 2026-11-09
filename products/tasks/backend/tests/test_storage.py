import json
import time
import threading

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import redis
from parameterized import parameterized

from products.tasks.backend.facade.contracts import TaskRunLogAppendUnserialized
from products.tasks.backend.storage import append_jsonl_object


class TestAppendJsonlObject(SimpleTestCase):
    @patch("products.tasks.backend.storage.get_client")
    @patch("products.tasks.backend.storage.object_storage.write")
    @patch("products.tasks.backend.storage.object_storage.read")
    def test_refuses_append_when_lock_contended(
        self,
        mock_read: MagicMock,
        mock_write: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        mock_get_client.return_value.lock.return_value.acquire.return_value = False

        with self.assertRaises(TaskRunLogAppendUnserialized):
            append_jsonl_object("sessions/example.jsonl", [{"type": "session"}])

        mock_read.assert_not_called()
        mock_write.assert_not_called()

    @patch("products.tasks.backend.storage.get_client")
    @patch("products.tasks.backend.storage.object_storage.write")
    @patch("products.tasks.backend.storage.object_storage.read")
    def test_waits_for_the_lock_again_when_asked(
        self,
        mock_read: MagicMock,
        mock_write: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        mock_read.return_value = ""
        lock = mock_get_client.return_value.lock.return_value
        lock.acquire.side_effect = [False, True]

        append_jsonl_object("sessions/example.jsonl", [{"type": "session"}], lock_attempts=2)

        self.assertEqual(lock.acquire.call_count, 2)
        mock_write.assert_called_once_with("sessions/example.jsonl", '{"type": "session"}')

    @parameterized.expand(
        [
            ("", True, '{"type": "session"}'),
            ('{"type": "session"}', False, '{"type": "session"}\n{"type": "message"}'),
        ]
    )
    @patch("products.tasks.backend.storage.get_client")
    @patch("products.tasks.backend.storage.object_storage.write")
    @patch("products.tasks.backend.storage.object_storage.read")
    def test_appends_complete_json_lines(
        self,
        existing_content: str,
        expected_is_new: bool,
        expected_content: str,
        mock_read: MagicMock,
        mock_write: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        mock_read.return_value = existing_content

        is_new = append_jsonl_object("sessions/example.jsonl", [{"type": "session" if expected_is_new else "message"}])

        self.assertEqual(is_new, expected_is_new)
        mock_write.assert_called_once_with("sessions/example.jsonl", expected_content)

    @patch("products.tasks.backend.storage.get_client")
    @patch("products.tasks.backend.storage.object_storage.write")
    @patch("products.tasks.backend.storage.object_storage.read")
    def test_concurrent_appends_do_not_drop_entries(
        self,
        mock_read: MagicMock,
        mock_write: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        stored = ""
        mutex = threading.Lock()

        class _Mutex:
            def acquire(self) -> bool:
                return mutex.acquire(timeout=5)

            def release(self) -> None:
                mutex.release()

        mock_get_client.return_value.lock.return_value = _Mutex()

        def _read(key: str, missing_ok: bool = False) -> str:
            snapshot = stored
            time.sleep(0.005)
            return snapshot

        def _write(key: str, content: str) -> None:
            nonlocal stored
            stored = content

        mock_read.side_effect = _read
        mock_write.side_effect = _write

        writers = [
            threading.Thread(target=append_jsonl_object, args=("sessions/example.jsonl", [{"n": n}])) for n in range(8)
        ]
        for writer in writers:
            writer.start()
        for writer in writers:
            writer.join()

        self.assertEqual(sorted(stored.split("\n")), sorted(json.dumps({"n": n}) for n in range(8)))

    @parameterized.expand([("acquire",), ("release",)])
    @patch("products.tasks.backend.storage.get_client")
    @patch("products.tasks.backend.storage.object_storage.write")
    @patch("products.tasks.backend.storage.object_storage.read")
    def test_fails_open_when_redis_is_unavailable(
        self,
        failing_call: str,
        mock_read: MagicMock,
        mock_write: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        mock_read.return_value = ""
        lock = mock_get_client.return_value.lock.return_value
        lock.acquire.return_value = True
        getattr(lock, failing_call).side_effect = redis.exceptions.ConnectionError("redis down")

        is_new = append_jsonl_object("sessions/example.jsonl", [{"type": "session"}])

        self.assertTrue(is_new)
        mock_write.assert_called_once_with("sessions/example.jsonl", '{"type": "session"}')
