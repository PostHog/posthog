"""Smoke test: call GLM-5.2 via Cloudflare Workers AI through the gateway's own
CF anthropic-messages adapter — the exact code path a scout on the claude runtime
uses (issue 28). Proves CF creds + routing + Anthropic<->OpenAI tool translation.

Run from services/llm-gateway:
    .venv/bin/python scripts/glm_cf_smoke.py

Reads LLM_GATEWAY_CLOUDFLARE_API_KEY / LLM_GATEWAY_CLOUDFLARE_ACCOUNT_ID from the
repo .env (Workers AI token needs the "Workers AI: Read + Run" scope).
"""

import asyncio
import sys

from dotenv import load_dotenv
from fastapi import HTTPException

from llm_gateway.cloudflare import (
    CLOUDFLARE_ALLOWED_MODELS,
    ensure_cloudflare_configured,
    make_cloudflare_anthropic_call,
)
from llm_gateway.config import Settings

GLM_MODEL = "@cf/zai-org/glm-5.2"


async def main() -> None:
    assert GLM_MODEL in CLOUDFLARE_ALLOWED_MODELS, f"{GLM_MODEL} not in allowlist"
    # Settings has no env_file, so load the repo .env into the environment first (as benchmark.py does).
    load_dotenv()
    try:
        api_base, api_key = ensure_cloudflare_configured(Settings())
    except HTTPException:
        sys.exit("Missing LLM_GATEWAY_CLOUDFLARE_API_KEY / LLM_GATEWAY_CLOUDFLARE_ACCOUNT_ID")
    print(f"api_base: {api_base}")

    llm_call = make_cloudflare_anthropic_call(api_base, api_key)

    # Anthropic Messages request WITH a tool — the codex/Responses path can't
    # translate tools (issue 28 root-cause v2); this claude path must.
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

    print(f"\nRESULT: GLM-5.2 via Cloudflare responded; tool_use emitted = {used_tool}")


if __name__ == "__main__":
    asyncio.run(main())
