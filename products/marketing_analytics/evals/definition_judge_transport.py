from __future__ import annotations

from typing import cast

from autoevals.oai import Client, LLMClient, prepare_openai
from openai import AsyncOpenAI, RateLimitError
from openai.types.responses import ResponseInputParam, ToolParam
from posthoganalytics.ai.openai import AsyncOpenAI as TracedAsyncOpenAI

from products.posthog_ai.eval_harness.scorers.tracing import _build_posthog_kwargs


def definition_judge_client(client: Client | None) -> LLMClient:
    configured = client if isinstance(client, AsyncOpenAI) else prepare_openai(client=client, is_async=True).openai
    # SDK copies omit the explicit capture client unless it is forwarded to the subclass.
    extra_kwargs = {"posthog_client": configured._ph_client} if isinstance(configured, TracedAsyncOpenAI) else {}
    provider = cast(AsyncOpenAI, configured).with_options(max_retries=0, timeout=60.0, _extra_kwargs=extra_kwargs)
    if not isinstance(provider, AsyncOpenAI):
        raise ValueError("Definition review requires an asynchronous OpenAI-compatible client")

    async def complete(**kwargs: object) -> dict[str, object]:
        tools = cast(list[dict[str, dict[str, object]]], kwargs["tools"])
        response_tools = [
            {
                "type": "function",
                "name": tool["function"]["name"],
                "description": tool["function"]["description"],
                "parameters": tool["function"]["parameters"],
            }
            for tool in tools
        ]
        tracing_kwargs = _build_posthog_kwargs() if isinstance(provider, TracedAsyncOpenAI) else {}
        try:
            response = await provider.responses.create(
                model=cast(str, kwargs["model"]),
                input=cast(ResponseInputParam, kwargs["messages"]),
                tools=cast(list[ToolParam], response_tools),
                tool_choice="required",
                reasoning={"effort": "low"},
                max_output_tokens=cast(int, kwargs["max_tokens"]),
                **tracing_kwargs,
            )
        except RateLimitError as exc:
            # Autoevals retries this exception even when SDK retries are disabled.
            raise RuntimeError(f"Provider rate-limit or quota error (HTTP {exc.status_code}); no retry") from exc
        if response.status != "completed":
            raise ValueError("Incomplete definition judge response")
        tool_calls = []
        for item in response.output:
            if item.type == "function_call":
                if item.status != "completed":
                    raise ValueError("Incomplete definition judge tool call")
                tool_calls.append(
                    {
                        "type": "function",
                        "id": item.call_id,
                        "function": {"name": item.name, "arguments": item.arguments},
                    }
                )
        return {
            "model": response.model,
            "usage": response.usage.model_dump(mode="json") if response.usage is not None else None,
            "choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": tool_calls}}],
        }

    # Supplying a callback avoids implicit tracing; replace autoevals' lossy Responses adapter.
    wrapper = LLMClient(openai=provider, is_async=True, complete=complete)
    wrapper.complete = complete
    return wrapper
