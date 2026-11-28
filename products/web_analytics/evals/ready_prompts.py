"""The ready-made web analytics prompts the PostHog MCP serves, read from the same file the server bundles."""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from pathlib import Path

import yaml

from posthog.dataclasses import frozen

READY_PROMPTS_PATH = Path(__file__).resolve().parents[1] / "mcp" / "ready_prompts" / "prompts.yaml"


@frozen
class ReadyPrompt:
    name: str
    title: str
    tools: tuple[str, ...]
    argument_names: tuple[str, ...]
    text: str


@cache
def load_ready_prompts() -> tuple[ReadyPrompt, ...]:
    with READY_PROMPTS_PATH.open() as file:
        entries = yaml.safe_load(file)["prompts"]
    return tuple(
        ReadyPrompt(
            name=entry["name"],
            title=entry["title"],
            tools=tuple(entry["tools"]),
            argument_names=tuple(argument["name"] for argument in entry.get("arguments") or ()),
            text=entry["text"].rstrip(),
        )
        for entry in entries
    )


def render_ready_prompt(prompt: ReadyPrompt, arguments: Mapping[str, str] | None = None) -> str:
    # Mirrors `appendPromptArguments` in services/mcp/src/resources/ready-prompts.ts, so an eval case
    # asks exactly what an MCP client receives from prompts/get.
    lines = [
        f"{name}: {value.strip()}"
        for name in prompt.argument_names
        if (value := (arguments or {}).get(name, "")) and value.strip()
    ]
    return f"{prompt.text}\n\n" + "\n".join(lines) if lines else prompt.text
