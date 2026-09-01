import json
from collections.abc import Awaitable, Callable
from uuid import uuid4

import pytest

from products.tasks.backend.logic.stream.redis_stream import (
    DATA_KEY,
    TASK_RUN_STREAM_COMPLETED_TIMEOUT,
    TASK_RUN_STREAM_SEQUENCE_TIMEOUT,
    TASK_RUN_STREAM_TIMEOUT,
    TaskRunRedisStream,
    TaskRunStreamAlreadyCompleted,
    TaskRunStreamCompletionSequenceMismatch,
    TaskRunStreamSequenceGap,
    _stream_id_sort_key,
    get_task_run_stream_completed_key,
    get_task_run_stream_key,
    publish_task_run_stream_complete,
    publish_task_run_stream_event,
    reset_task_run_stream,
)
from products.tasks.backend.redis import get_tasks_stream_redis_sync


def _new_stream(timeout: int = 60) -> TaskRunRedisStream:
    return TaskRunRedisStream(f"task-run-stream:test:{uuid4()}", timeout=timeout)


async def _read_stream_events(redis_stream: TaskRunRedisStream) -> list[dict]:
    messages = await redis_stream._redis_client.xrange(redis_stream._stream_key)
    return [json.loads(message[DATA_KEY]) for _stream_id, message in messages]


@pytest.mark.asyncio
async def test_write_event_with_sequence_accepts_next_sequence() -> None:
    redis_stream = _new_stream()
    try:
        stream_id = await redis_stream.write_event_with_sequence({"type": "message"}, 1)

        assert stream_id is not None
        assert await redis_stream.get_last_sequence() == 1
        assert await _read_stream_events(redis_stream) == [{"type": "message"}]
    finally:
        await redis_stream.delete_stream()


@pytest.mark.asyncio
async def test_write_event_with_sequence_rejects_sequence_gap() -> None:
    redis_stream = _new_stream()
    try:
        with pytest.raises(TaskRunStreamSequenceGap) as exc:
            await redis_stream.write_event_with_sequence({"type": "message"}, 2)

        assert exc.value.expected_sequence == 1
        assert exc.value.received_sequence == 2
        assert exc.value.last_accepted_seq == 0
        assert await redis_stream.get_last_sequence() == 0
        assert await _read_stream_events(redis_stream) == []
    finally:
        await redis_stream.delete_stream()


@pytest.mark.asyncio
async def test_write_event_with_sequence_ignores_duplicate_sequence() -> None:
    redis_stream = _new_stream()
    try:
        first_stream_id = await redis_stream.write_event_with_sequence({"type": "first"}, 1)
        duplicate_stream_id = await redis_stream.write_event_with_sequence({"type": "duplicate"}, 1)

        assert first_stream_id is not None
        assert duplicate_stream_id is None
        assert await redis_stream.get_last_sequence() == 1
        assert await _read_stream_events(redis_stream) == [{"type": "first"}]
    finally:
        await redis_stream.delete_stream()


@pytest.mark.parametrize(
    "terminal",
    [
        pytest.param(lambda stream: stream.mark_complete_after_sequence(1), id="mark_complete_after_sequence"),
        pytest.param(lambda stream: stream.mark_error("boom"), id="mark_error"),
    ],
)
@pytest.mark.asyncio
async def test_write_event_with_sequence_rejects_write_after_completion(
    terminal: Callable[[TaskRunRedisStream], Awaitable[None]],
) -> None:
    redis_stream = _new_stream()
    try:
        await redis_stream.write_event_with_sequence({"type": "message"}, 1)
        await terminal(redis_stream)

        with pytest.raises(TaskRunStreamAlreadyCompleted) as exc:
            await redis_stream.write_event_with_sequence({"type": "late"}, 2)

        assert exc.value.last_accepted_seq == 1
    finally:
        await redis_stream.delete_stream()


@pytest.mark.asyncio
async def test_mark_complete_after_sequence_rejects_sequence_mismatch() -> None:
    redis_stream = _new_stream()
    try:
        await redis_stream.write_event_with_sequence({"type": "message"}, 1)

        with pytest.raises(TaskRunStreamCompletionSequenceMismatch) as exc:
            await redis_stream.mark_complete_after_sequence(2)

        assert exc.value.final_sequence == 2
        assert exc.value.last_accepted_seq == 1
        assert await _read_stream_events(redis_stream) == [{"type": "message"}]
    finally:
        await redis_stream.delete_stream()


@pytest.mark.asyncio
async def test_mark_complete_is_idempotent() -> None:
    redis_stream = _new_stream()
    try:
        await redis_stream.mark_complete()
        await redis_stream.mark_complete()

        assert await _read_stream_events(redis_stream) == [{"type": "STREAM_STATUS", "status": "complete"}]
    finally:
        await redis_stream.delete_stream()


@pytest.mark.parametrize(
    "terminal",
    [
        pytest.param(lambda stream: stream.mark_complete(), id="mark_complete"),
        pytest.param(lambda stream: stream.mark_complete_after_sequence(1), id="mark_complete_after_sequence"),
        pytest.param(lambda stream: stream.mark_error("boom"), id="mark_error"),
    ],
)
@pytest.mark.asyncio
async def test_terminal_sentinel_shortens_stream_ttl(
    terminal: Callable[[TaskRunRedisStream], Awaitable[None]],
) -> None:
    redis_stream = _new_stream(timeout=TASK_RUN_STREAM_TIMEOUT)
    try:
        await redis_stream.write_event_with_sequence({"type": "message"}, 1)
        assert await redis_stream._redis_client.ttl(redis_stream._stream_key) > TASK_RUN_STREAM_COMPLETED_TIMEOUT

        await terminal(redis_stream)

        stream_ttl = await redis_stream._redis_client.ttl(redis_stream._stream_key)
        assert 0 < stream_ttl <= TASK_RUN_STREAM_COMPLETED_TIMEOUT
    finally:
        await redis_stream.delete_stream()


@pytest.mark.parametrize("already_completed", [False, True])
def test_publish_task_run_stream_complete_shortens_stream_ttl(already_completed: bool) -> None:
    run_id = f"test:{uuid4()}"
    stream_key = get_task_run_stream_key(run_id)
    client = get_tasks_stream_redis_sync()
    try:
        assert publish_task_run_stream_event(run_id, {"type": "message"}) is not None
        if already_completed:
            client.set(get_task_run_stream_completed_key(stream_key), "1", ex=TASK_RUN_STREAM_SEQUENCE_TIMEOUT)
        assert client.ttl(stream_key) > TASK_RUN_STREAM_COMPLETED_TIMEOUT

        assert publish_task_run_stream_complete(run_id) is True

        stream_ttl = client.ttl(stream_key)
        assert 0 < stream_ttl <= TASK_RUN_STREAM_COMPLETED_TIMEOUT
    finally:
        reset_task_run_stream(run_id)


def test_publish_stream_event_after_completion_keeps_short_ttl() -> None:
    run_id = f"test:{uuid4()}"
    stream_key = get_task_run_stream_key(run_id)
    client = get_tasks_stream_redis_sync()
    try:
        assert publish_task_run_stream_event(run_id, {"type": "message"}) is not None
        assert publish_task_run_stream_complete(run_id) is True

        assert publish_task_run_stream_event(run_id, {"type": "task_run_state"}) is not None

        stream_ttl = client.ttl(stream_key)
        assert 0 < stream_ttl <= TASK_RUN_STREAM_COMPLETED_TIMEOUT
    finally:
        reset_task_run_stream(run_id)


@pytest.mark.parametrize(
    "left,right,expected_less",
    [
        ("5-0", "10-0", True),
        ("10-0", "5-0", False),
        ("10-0", "10-1", True),
        ("10-1", "10-0", False),
        ("10-5", "10-5", False),
        ("not-an-id", "10-0", True),
    ],
)
def test_stream_id_sort_key_orders_ids(left: str, right: str, expected_less: bool) -> None:
    assert (_stream_id_sort_key(left) < _stream_id_sort_key(right)) is expected_less


@pytest.mark.asyncio
async def test_get_length_and_first_stream_id() -> None:
    redis_stream = _new_stream()
    try:
        assert await redis_stream.get_length() == 0
        assert await redis_stream.get_first_stream_id() is None

        first_id = await redis_stream.write_event({"type": "a"})
        await redis_stream.write_event({"type": "b"})

        assert await redis_stream.get_length() == 2
        assert await redis_stream.get_first_stream_id() == first_id
    finally:
        await redis_stream.delete_stream()


@pytest.mark.asyncio
async def test_resume_point_trimmed_only_when_cursor_predates_surviving_entries() -> None:
    redis_stream = _new_stream()
    try:
        first_id = await redis_stream.write_event({"type": "a"})
        second_id = await redis_stream.write_event({"type": "b"})

        # Special-case cursors and a still-present cursor are never gaps.
        assert await redis_stream.resume_point_trimmed("0") is False
        assert await redis_stream.resume_point_trimmed("") is False
        assert await redis_stream.resume_point_trimmed(first_id) is False
        assert await redis_stream.resume_point_trimmed(second_id) is False

        # A cursor older than the oldest surviving entry means events were trimmed.
        assert await redis_stream.resume_point_trimmed("1-0") is True
    finally:
        await redis_stream.delete_stream()


@pytest.mark.asyncio
async def test_resume_point_trimmed_false_when_stream_empty() -> None:
    redis_stream = _new_stream()
    try:
        assert await redis_stream.resume_point_trimmed("123-0") is False
    finally:
        await redis_stream.delete_stream()
