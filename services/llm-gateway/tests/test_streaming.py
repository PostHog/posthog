import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_gateway.streaming.sse import format_sse_stream


async def create_mock_stream(chunks: list[dict[str, Any]]) -> AsyncGenerator[Any, None]:
    for chunk in chunks:
        mock_chunk = MagicMock()
        mock_chunk.model_dump = MagicMock(return_value=chunk)
        yield mock_chunk


async def create_error_stream(chunks_before_error: int = 1) -> AsyncGenerator[Any, None]:
    for i in range(chunks_before_error):
        mock_chunk = MagicMock()
        mock_chunk.model_dump = MagicMock(return_value={"chunk": i})
        yield mock_chunk
    raise ValueError("Stream error")


async def collect_stream(stream: AsyncGenerator[bytes, None]) -> list[bytes]:
    return [chunk async for chunk in stream]


class TestFormatSseStream:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "chunks,expected_data_count,expected_done",
        [
            pytest.param([], 0, True, id="empty_stream"),
            pytest.param([{"content": "Hello"}], 1, True, id="single_chunk"),
            pytest.param([{"a": 1}, {"b": 2}, {"c": 3}], 3, True, id="multiple_chunks"),
        ],
    )
    async def test_stream_output_format(
        self,
        chunks: list[dict],
        expected_data_count: int,
        expected_done: bool,
    ) -> None:
        result = await collect_stream(format_sse_stream(create_mock_stream(chunks)))

        data_chunks = [r for r in result if not r.startswith(b"data: [DONE]")]
        done_chunks = [r for r in result if r == b"data: [DONE]\n\n"]

        assert len(data_chunks) == expected_data_count
        assert (len(done_chunks) == 1) == expected_done

    @pytest.mark.asyncio
    async def test_chunk_content_serialization(self) -> None:
        chunks = [{"content": "Hello", "nested": {"key": "value"}}]
        result = await collect_stream(format_sse_stream(create_mock_stream(chunks)))

        data_line = result[0].decode()
        assert data_line.startswith("data: ")
        assert data_line.endswith("\n\n")

        parsed = json.loads(data_line.replace("data: ", "").strip())
        assert parsed == chunks[0]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "chunks_before_error",
        [
            pytest.param(0, id="error_at_start"),
            pytest.param(1, id="error_after_one_chunk"),
            pytest.param(3, id="error_after_three_chunks"),
        ],
    )
    async def test_error_handling(self, chunks_before_error: int) -> None:
        result = await collect_stream(format_sse_stream(create_error_stream(chunks_before_error)))

        error_chunk = result[-1]
        error_data = json.loads(error_chunk.decode().replace("data: ", ""))

        assert "error" in error_data
        assert error_data["error"]["type"] == "internal_error"
        assert len(result) == chunks_before_error + 1
