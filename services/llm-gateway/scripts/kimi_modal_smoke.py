import asyncio
import sys

from dotenv import load_dotenv
from fastapi import HTTPException

from llm_gateway.config import Settings
from llm_gateway.modal import ensure_modal_model_configured, make_modal_anthropic_call

KIMI_MODEL = "moonshotai/kimi-k3"


async def main() -> None:
    load_dotenv()
    try:
        api_base, modal_key, modal_secret = ensure_modal_model_configured(KIMI_MODEL, Settings())
    except HTTPException:
        sys.exit("Missing Modal Kimi configuration")

    response = await make_modal_anthropic_call(api_base, modal_key, modal_secret)(
        model=KIMI_MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": "Use the tool to get the weather in Paris."}],
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
    content = getattr(response, "content", None) or (response.get("content") if isinstance(response, dict) else None)
    if not any(
        (getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)) == "tool_use"
        for block in content or []
    ):
        sys.exit("Kimi K3 did not return a tool call")


if __name__ == "__main__":
    asyncio.run(main())
