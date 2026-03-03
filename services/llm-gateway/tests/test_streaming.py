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


class ProviderError(Exception):
    def __init__(self, message: str, error_type: str, status_code: int):
        super().__init__(message)
        self.message = message
        self.type = error_type
        self.status_code = status_code


async def create_error_stream(chunks_before_error: int = 1) -> AsyncGenerator[Any, None]:
    for i in range(chunks_before_error):
        mock_chunk = MagicMock()
        mock_chunk.model_dump = MagicMock(return_value={"chunk": i})
        yield mock_chunk
    raise ValueError("Stream error")


async def create_provider_error_stream(
    chunks_before_error: int = 1,
    message: str = "Service overloaded",
    error_type: str = "overloaded_error",
    status_code: int = 529,
) -> AsyncGenerator[Any, None]:
    for i in range(chunks_before_error):
        mock_chunk = MagicMock()
        mock_chunk.model_dump = MagicMock(return_value={"chunk": i})
        yield mock_chunk
    raise ProviderError(message, error_type, status_code)


async def collect_stream(stream: AsyncGenerator[bytes, None]) -> list[bytes]:
    chunks: list[bytes] = []
    try:
        async for chunk in stream:
            chunks.append(chunk)
    except Exception:
        pass
    return chunks


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
        assert error_data["error"]["message"] == "Stream error"
        assert len(result) == chunks_before_error + 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "message,error_type,status_code",
        [
            pytest.param("Service overloaded", "overloaded_error", 529, id="overloaded"),
            pytest.param("Rate limit exceeded", "rate_limit_error", 429, id="rate_limited"),
            pytest.param("Service unavailable", "service_unavailable", 503, id="unavailable"),
        ],
    )
    async def test_provider_error_surfaces_details(self, message: str, error_type: str, status_code: int) -> None:
        result = await collect_stream(
            format_sse_stream(create_provider_error_stream(1, message, error_type, status_code))
        )

        error_chunk = result[-1]
        error_data = json.loads(error_chunk.decode().replace("data: ", ""))

        assert error_data["error"]["message"] == message
        assert error_data["error"]["type"] == error_type
        assert error_data["error"]["code"] is None
