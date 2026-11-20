import json
import time
import threading

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import redis
from parameterized import parameterized

from posthog.storage.object_storage import StoredObjectSummary

from products.tasks.backend.facade.contracts import TaskRunLogAppendUnserialized
from products.tasks.backend.storage import (
    RunLogCache,
    TaskRunLog,
    append_jsonl_object,
    append_run_log_chunk,
    read_run_log,
    read_run_log_version,
)
from products.tasks.backend.storage_errors import TaskRunLogChunkMissing


class TestAppendJsonlObject(SimpleTestCase):
    @patch("products.tasks.backend.storage.get_client")
    @patch("products.tasks.backend.storage.object_storage.append")
    def test_refuses_append_when_lock_contended(
        self,
        mock_append: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        mock_get_client.return_value.lock.return_value.acquire.return_value = False

        with self.assertRaises(TaskRunLogAppendUnserialized):
            append_jsonl_object("sessions/example.jsonl", [{"type": "session"}])

        mock_append.assert_not_called()

    @patch("products.tasks.backend.storage.get_client")
    @patch("products.tasks.backend.storage.object_storage.append")
    def test_waits_for_the_lock_again_when_asked(
        self,
        mock_append: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        lock = mock_get_client.return_value.lock.return_value
        lock.acquire.side_effect = [False, True]

        append_jsonl_object("sessions/example.jsonl", [{"type": "session"}], lock_attempts=2)

        self.assertEqual(lock.acquire.call_count, 2)
        mock_append.assert_called_once_with("sessions/example.jsonl", b'{"type": "session"}', separator=b"\n")

    @parameterized.expand(
        [
            ("", True, '{"type": "session", "batch": "b1"}'),
            ('{"type": "session"}', False, '{"type": "session"}\n{"type": "message", "batch": "b1"}'),
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

        is_new = append_jsonl_object(
            "sessions/example.jsonl", [{"type": "session" if expected_is_new else "message"}], batch_id="b1"
        )

        self.assertEqual(is_new, expected_is_new)
        mock_write.assert_called_once_with("sessions/example.jsonl", expected_content)

    @patch("products.tasks.backend.storage.get_client")
    @patch("products.tasks.backend.storage.object_storage.append")
    def test_concurrent_appends_do_not_drop_entries(
        self,
        mock_append: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        stored = b""
        mutex = threading.Lock()

        class _Mutex:
            def acquire(self) -> bool:
                return mutex.acquire(timeout=5)

            def release(self) -> None:
                mutex.release()

        mock_get_client.return_value.lock.return_value = _Mutex()

        def _append(key: str, content: bytes, separator: bytes) -> None:
            nonlocal stored
            snapshot = stored
            time.sleep(0.005)
            stored = snapshot + separator + content if snapshot else content

        mock_append.side_effect = _append

        writers = [
            threading.Thread(target=append_jsonl_object, args=("sessions/example.jsonl", [{"n": n}])) for n in range(8)
        ]
        for writer in writers:
            writer.start()
        for writer in writers:
            writer.join()

        self.assertEqual(sorted(stored.split(b"\n")), sorted(json.dumps({"n": n}).encode() for n in range(8)))

    @parameterized.expand([("acquire",), ("release",)])
    @patch("products.tasks.backend.storage.get_client")
    @patch("products.tasks.backend.storage.object_storage.append")
    def test_fails_open_when_redis_is_unavailable(
        self,
        failing_call: str,
        mock_append: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        mock_append.return_value = True
        lock = mock_get_client.return_value.lock.return_value
        lock.acquire.return_value = True
        getattr(lock, failing_call).side_effect = redis.exceptions.ConnectionError("redis down")

        is_new = append_jsonl_object("sessions/example.jsonl", [{"type": "session"}])

        self.assertTrue(is_new)
        mock_append.assert_called_once_with("sessions/example.jsonl", b'{"type": "session"}', separator=b"\n")


def _chunked_log(chunk_count: int) -> TaskRunLog:
    return TaskRunLog(key="tasks/logs/team_1/task_1/run_1.jsonl", chunked=True, chunk_count=chunk_count)


class TestChunkedRunLog(SimpleTestCase):
    def _bucket(self, chunk_count: int, *, lose_first_response: bool = False) -> dict[str, MagicMock]:
        stored = {index: (json.dumps({"index": index}).encode() + b"\n", {}) for index in range(chunk_count)}
        responses_to_lose = [lose_first_response]

        def index_of(key: str) -> int:
            return int(key.rsplit("/", 1)[1].removesuffix(".jsonl"))

        def write_if_absent(key: str, content: bytes, *, metadata: dict[str, str]) -> bool:
            if index_of(key) in stored:
                return False
            stored[index_of(key)] = (content, metadata)
            if responses_to_lose.pop() if responses_to_lose else False:
                return False
            return True

        def head_object_strict(key: str) -> dict | None:
            if index_of(key) not in stored:
                return None
            content, metadata = stored[index_of(key)]
            return {"ContentLength": len(content), "Metadata": metadata}

        def read_bytes(key: str, missing_ok: bool) -> bytes | None:
            assert missing_ok
            return stored[index_of(key)][0] if index_of(key) in stored else None

        def list_object_summaries(prefix: str) -> list[StoredObjectSummary]:
            return [
                StoredObjectSummary(key=f"{prefix}{index:010d}.jsonl", etag=None, size=len(stored[index][0]))
                for index in sorted(stored)
            ]

        return {
            "write_if_absent": MagicMock(side_effect=write_if_absent),
            "head_object_strict": MagicMock(side_effect=head_object_strict),
            "read_bytes": MagicMock(side_effect=read_bytes),
            "list_object_summaries": MagicMock(side_effect=list_object_summaries),
        }

    @patch("products.tasks.backend.storage.object_storage.read_bytes", return_value=None)
    def test_read_fails_when_a_counted_chunk_is_missing(self, _mock_read: MagicMock) -> None:
        with self.assertRaises(TaskRunLogChunkMissing):
            read_run_log(_chunked_log(2))

    @patch("products.tasks.backend.storage.get_client")
    def test_append_lands_at_the_end_when_the_count_falls_behind(self, _mock_get_client: MagicMock) -> None:
        bucket = self._bucket(100)

        with patch.multiple("products.tasks.backend.storage.object_storage", **bucket):
            chunk_count = append_run_log_chunk(_chunked_log(0), [{"type": "session"}], lock_attempts=1, batch_id=None)

        self.assertEqual(chunk_count, 101)
        self.assertEqual(bucket["list_object_summaries"].call_count, 1)

    def test_version_checks_only_chunks_past_the_count(self) -> None:
        bucket = self._bucket(7)

        with patch.multiple("products.tasks.backend.storage.object_storage", **bucket):
            version = read_run_log_version(_chunked_log(5))

        self.assertEqual(version, "chunks-7")
        self.assertEqual(bucket["head_object_strict"].call_count, 3)

    @patch("products.tasks.backend.storage.get_client")
    def test_append_keeps_a_write_whose_response_was_lost(self, _mock_get_client: MagicMock) -> None:
        bucket = self._bucket(3, lose_first_response=True)

        with patch.multiple("products.tasks.backend.storage.object_storage", **bucket):
            chunk_count = append_run_log_chunk(_chunked_log(3), [{"type": "session"}], lock_attempts=1, batch_id=None)
            content = read_run_log(_chunked_log(0))

        self.assertEqual(chunk_count, 4)
        self.assertEqual(content.count('"session"'), 1)

    def test_cache_reads_only_chunks_it_has_not_read(self) -> None:
        bucket = self._bucket(3)
        cache = RunLogCache()

        with patch.multiple("products.tasks.backend.storage.object_storage", **bucket):
            first = cache.read(_chunked_log(3))
            bucket["write_if_absent"](
                "tasks/logs/team_1/task_1/run_1/chunks/0000000003.jsonl", b'{"index": 3}\n', metadata={}
            )
            bucket["read_bytes"].reset_mock()
            second = cache.read(_chunked_log(3))

        self.assertEqual(second, first + '{"index": 3}\n')
        self.assertEqual(bucket["read_bytes"].call_count, 2)
