import json
import time
import threading

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import redis
from parameterized import parameterized

from products.tasks.backend.storage import append_jsonl_object


class TestAppendJsonlObject(SimpleTestCase):
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

    @patch("products.tasks.backend.storage.get_client")
    @patch("products.tasks.backend.storage.object_storage.write")
    @patch("products.tasks.backend.storage.object_storage.read")
    def test_fails_open_when_lock_release_raises_connection_error(
        self,
        mock_read: MagicMock,
        mock_write: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        mock_read.return_value = ""

        class _ReleaseFails:
            def acquire(self) -> bool:
                return True

            def release(self) -> None:
                raise redis.exceptions.ConnectionError("redis down")

        mock_get_client.return_value.lock.return_value = _ReleaseFails()

        is_new = append_jsonl_object("sessions/example.jsonl", [{"type": "session"}])

        self.assertTrue(is_new)
        mock_write.assert_called_once_with("sessions/example.jsonl", '{"type": "session"}')
