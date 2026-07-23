"""Smoke test: call GLM-5.2 on a Modal vLLM endpoint through the gateway's own Modal
anthropic-messages adapter — the exact code path a cloud-task agent on the claude runtime
uses. Proves Modal proxy-token auth + routing + Anthropic<->OpenAI tool translation, the
Modal analogue of glm_cf_smoke.py.

Run from services/llm-gateway:
    .venv/bin/python scripts/glm_modal_smoke.py

Reads LLM_GATEWAY_MODAL_API_BASE / LLM_GATEWAY_MODAL_KEY / LLM_GATEWAY_MODAL_SECRET from the
repo .env (create the token pair with `modal workspace proxy-tokens create`).
"""

import asyncio
import sys

from dotenv import load_dotenv
from fastapi import HTTPException

from llm_gateway.config import Settings
from llm_gateway.modal import (
    MODAL_ALLOWED_MODELS,
    ensure_modal_configured,
    make_modal_anthropic_call,
)

GLM_MODEL = "@cf/zai-org/glm-5.2"


async def main() -> None:
    assert GLM_MODEL in MODAL_ALLOWED_MODELS, f"{GLM_MODEL} not in allowlist"
    # Settings has no env_file, so load the repo .env into the environment first (as benchmark.py does).
    load_dotenv()
    try:
        api_base, modal_key, modal_secret = ensure_modal_configured(Settings())
    except HTTPException:
        sys.exit("Missing LLM_GATEWAY_MODAL_API_BASE / LLM_GATEWAY_MODAL_KEY / LLM_GATEWAY_MODAL_SECRET")
    print(f"api_base: {api_base}")

    llm_call = make_modal_anthropic_call(api_base, modal_key, modal_secret)

    # Anthropic Messages request WITH a tool — tool translation through litellm's adapter is the
    # part most likely to differ between backends, so it's the qualification gate for the ramp.
    response = await llm_call(
        model=GLM_MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": "What's the weather in Paris? Use the tool."}],
        tools=[
            {
                "name": "get_weather",
                "description": "Get the current weather for a city",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            }
        ],
    )

    print("\n=== raw response ===")
    print(response)

    content = getattr(response, "content", None) or (response.get("content") if isinstance(response, dict) else None)
    print("\n=== content blocks ===")
    used_tool = False
    for block in content or []:
        btype = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
        print(f"- {btype}: {block}")
        if btype == "tool_use":
            used_tool = True

    print(f"\nRESULT: GLM-5.2 via Modal responded; tool_use emitted = {used_tool}")


if __name__ == "__main__":
    asyncio.run(main())
