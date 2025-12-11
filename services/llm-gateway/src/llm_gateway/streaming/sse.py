import json
from collections.abc import AsyncGenerator
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def _serialize_chunk(obj: Any) -> Any:
    if isinstance(obj, bytes):
        return obj.decode("utf-8")
    if isinstance(obj, dict):
        return {k: _serialize_chunk(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_chunk(item) for item in obj]
    return obj


async def format_sse_stream(llm_stream: AsyncGenerator[Any, None]) -> AsyncGenerator[bytes, None]:
    is_raw_passthrough = None

    try:
        async for chunk in llm_stream:
            if isinstance(chunk, bytes):
                if is_raw_passthrough is None:
                    is_raw_passthrough = True
                yield chunk
                continue

            if is_raw_passthrough is None:
                is_raw_passthrough = False

            chunk_dict = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
            serializable = _serialize_chunk(chunk_dict)
            yield f"data: {json.dumps(serializable)}\n\n".encode()

        if not is_raw_passthrough:
            yield b"data: [DONE]\n\n"
    except Exception:
        logger.exception("Error in LLM stream")
        error_data = {"error": {"message": "An internal error has occurred.", "type": "internal_error"}}
        yield f"data: {json.dumps(error_data)}\n\n".encode()
