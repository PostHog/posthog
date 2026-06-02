import json
from uuid import uuid4

import pytest

from products.tasks.backend.stream.redis_stream import (
    DATA_KEY,
    TaskRunRedisStream,
    TaskRunStreamAlreadyCompleted,
    TaskRunStreamCompletionSequenceMismatch,
    TaskRunStreamSequenceGap,
)


def _new_stream() -> TaskRunRedisStream:
    return TaskRunRedisStream(f"task-run-stream:test:{uuid4()}", timeout=60)


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


@pytest.mark.asyncio
async def test_write_event_with_sequence_rejects_write_after_completion() -> None:
    redis_stream = _new_stream()
    try:
        await redis_stream.write_event_with_sequence({"type": "message"}, 1)
        await redis_stream.mark_complete_after_sequence(1)

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
