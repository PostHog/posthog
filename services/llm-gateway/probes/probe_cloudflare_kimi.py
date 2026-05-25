"""Probe Cloudflare Workers AI Kimi K2.6 via LiteLLM.

Goal: validate whether LiteLLM 1.83.7's `anthropic_messages` adapter correctly
translates Anthropic Messages format into Cloudflare Workers AI's OpenAI-compatible
chat-completions endpoint, including tool calls and streaming. If it does, the
gateway integration is mostly a config change. If not, we need our own translator.

Requires:
    CLOUDFLARE_API_KEY      — Workers AI API token
    CLOUDFLARE_ACCOUNT_ID   — your Cloudflare account ID

Usage:
    cp .env.example .env  # fill in keys
    python probe_cloudflare_kimi.py [--routing native|openai-compat|both]

The probe runs four checks against each routing it tries:
    1. acompletion (OpenAI format)            — baseline that CF works at all
    2. anthropic_messages, no tools           — does the Anthropic adapter translate?
    3. anthropic_messages, with a tool        — does tool_use round-trip cleanly?
    4. anthropic_messages, streaming          — does SSE produce Anthropic events?

Exits 0 if all checks pass on at least one routing, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import litellm
from dotenv import load_dotenv

MODEL_SLUG = "@cf/moonshotai/kimi-k2.6"


@dataclass
class CheckResult:
    name: str
    routing: str
    passed: bool
    detail: str = ""
    raw: Any = field(default=None, repr=False)


def _cf_api_base(account_id: str) -> str:
    return f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"


def _build_model_id(routing: str) -> str:
    if routing == "native":
        return f"cloudflare/{MODEL_SLUG}"
    if routing == "openai-compat":
        return f"openai/{MODEL_SLUG}"
    raise ValueError(f"unknown routing: {routing}")


def _extra_kwargs(routing: str, account_id: str, api_key: str) -> dict[str, Any]:
    if routing == "openai-compat":
        return {"api_base": _cf_api_base(account_id), "api_key": api_key}
    return {}


async def _check_acompletion(routing: str, account_id: str, api_key: str) -> CheckResult:
    try:
        resp = await litellm.acompletion(
            model=_build_model_id(routing),
            messages=[{"role": "user", "content": "Reply with the single word: ping"}],
            max_tokens=20,
            **_extra_kwargs(routing, account_id, api_key),
        )
        content = resp.choices[0].message.content or ""
        ok = "ping" in content.lower()
        return CheckResult("acompletion baseline", routing, ok, detail=f"content={content!r}", raw=resp)
    except Exception as exc:
        return CheckResult("acompletion baseline", routing, False, detail=f"{type(exc).__name__}: {exc}")


async def _check_anthropic_messages_plain(routing: str, account_id: str, api_key: str) -> CheckResult:
    try:
        resp = await litellm.anthropic_messages(
            model=_build_model_id(routing),
            messages=[{"role": "user", "content": "Reply with the single word: pong"}],
            max_tokens=20,
            **_extra_kwargs(routing, account_id, api_key),
        )
        # Expected Anthropic shape: dict with "content": [{"type":"text","text":...}], "stop_reason", "usage"
        if not isinstance(resp, dict):
            resp = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        content_blocks = resp.get("content") or []
        text = next(
            (b.get("text", "") for b in content_blocks if isinstance(b, dict) and b.get("type") == "text"),
            "",
        )
        has_shape = "stop_reason" in resp and "usage" in resp and isinstance(content_blocks, list)
        ok = has_shape and "pong" in text.lower()
        return CheckResult(
            "anthropic_messages plain",
            routing,
            ok,
            detail=f"text={text!r} stop_reason={resp.get('stop_reason')!r} usage={resp.get('usage')}",
            raw=resp,
        )
    except Exception as exc:
        return CheckResult("anthropic_messages plain", routing, False, detail=f"{type(exc).__name__}: {exc}")


async def _check_anthropic_messages_tool(routing: str, account_id: str, api_key: str) -> CheckResult:
    tools = [
        {
            "name": "get_weather",
            "description": "Get the current weather for a city",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ]
    try:
        resp = await litellm.anthropic_messages(
            model=_build_model_id(routing),
            messages=[{"role": "user", "content": "What's the weather in Paris? Use the get_weather tool."}],
            tools=tools,
            max_tokens=200,
            **_extra_kwargs(routing, account_id, api_key),
        )
        if not isinstance(resp, dict):
            resp = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        content_blocks = resp.get("content") or []
        tool_use = next((b for b in content_blocks if isinstance(b, dict) and b.get("type") == "tool_use"), None)
        ok = (
            tool_use is not None
            and tool_use.get("name") == "get_weather"
            and isinstance(tool_use.get("input"), dict)
            and "paris" in json.dumps(tool_use.get("input", {})).lower()
            and resp.get("stop_reason") == "tool_use"
        )
        return CheckResult(
            "anthropic_messages tool",
            routing,
            ok,
            detail=f"tool_use={tool_use!r} stop_reason={resp.get('stop_reason')!r}",
            raw=resp,
        )
    except Exception as exc:
        return CheckResult("anthropic_messages tool", routing, False, detail=f"{type(exc).__name__}: {exc}")


async def _check_anthropic_messages_stream(routing: str, account_id: str, api_key: str) -> CheckResult:
    try:
        stream = await litellm.anthropic_messages(
            model=_build_model_id(routing),
            messages=[{"role": "user", "content": "Count from 1 to 5."}],
            max_tokens=80,
            stream=True,
            **_extra_kwargs(routing, account_id, api_key),
        )

        seen_event_types: list[str] = []
        text_chunks: list[str] = []
        async for event in stream:
            payload = event if isinstance(event, dict) else getattr(event, "model_dump", lambda: {})()
            etype = payload.get("type") if isinstance(payload, dict) else None
            if etype:
                seen_event_types.append(etype)
            if isinstance(payload, dict) and payload.get("type") == "content_block_delta":
                delta = payload.get("delta") or {}
                if delta.get("type") == "text_delta":
                    text_chunks.append(delta.get("text", ""))

        expected = {"message_start", "content_block_start", "content_block_delta", "content_block_stop", "message_stop"}
        missing = expected - set(seen_event_types)
        ok = not missing and any(text_chunks)
        return CheckResult(
            "anthropic_messages stream",
            routing,
            ok,
            detail=f"events={list(dict.fromkeys(seen_event_types))} missing={sorted(missing)} text={''.join(text_chunks)[:80]!r}",
        )
    except Exception as exc:
        return CheckResult("anthropic_messages stream", routing, False, detail=f"{type(exc).__name__}: {exc}")


CHECKS: list[Callable[[str, str, str], Awaitable[CheckResult]]] = [
    _check_acompletion,
    _check_anthropic_messages_plain,
    _check_anthropic_messages_tool,
    _check_anthropic_messages_stream,
]


async def run_routing(routing: str, account_id: str, api_key: str) -> list[CheckResult]:
    print(f"\n=== routing: {routing} (model_id={_build_model_id(routing)}) ===")
    results: list[CheckResult] = []
    for check in CHECKS:
        result = await check(routing, account_id, api_key)
        results.append(result)
        marker = "PASS" if result.passed else "FAIL"
        print(f"  [{marker}] {result.name}")
        if result.detail:
            print(f"         {result.detail}")
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routing", choices=["native", "openai-compat", "both"], default="both")
    parser.add_argument("--verbose", action="store_true", help="enable litellm verbose logging")
    return parser.parse_args()


async def main() -> int:
    load_dotenv()
    args = parse_args()

    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    api_key = os.environ.get("CLOUDFLARE_API_KEY")
    if not account_id or not api_key:
        print("ERROR: set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_KEY (see .env.example)", file=sys.stderr)
        return 2

    if args.verbose:
        litellm.set_verbose = True  # type: ignore[attr-defined]

    # LiteLLM's native cloudflare provider reads these env vars.
    os.environ["CLOUDFLARE_API_KEY"] = api_key
    os.environ["CLOUDFLARE_ACCOUNT_ID"] = account_id

    routings = ["native", "openai-compat"] if args.routing == "both" else [args.routing]
    all_results: dict[str, list[CheckResult]] = {}
    for routing in routings:
        try:
            all_results[routing] = await run_routing(routing, account_id, api_key)
        except Exception:
            traceback.print_exc()
            all_results[routing] = []

    print("\n=== summary ===")
    any_full_pass = False
    for routing, results in all_results.items():
        passed = sum(1 for r in results if r.passed)
        print(f"  {routing}: {passed}/{len(results)} checks passed")
        if results and passed == len(results):
            any_full_pass = True

    if any_full_pass:
        print("\nAt least one routing passed every check — the gateway integration is mostly config.")
        return 0
    print("\nNo routing passed every check — see failures above; likely needs a translator (Option C).")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
