"""The tools the wizard can detect, and what each one means to PostHog.

PostHog owns this catalog. `projection.py` renders it to
`products/wizard/tool-catalog.generated.json`, and a change to that file on `master` makes the
wizard repo regenerate its detector registry from it. The backend reads the same catalog to
classify the scans the wizard reports.
"""

import re
from functools import cache

from products.wizard.backend.tool_catalog.curated import CURATED_TOOLS
from products.wizard.backend.tool_catalog.derived import derived_tools
from products.wizard.backend.tool_catalog.types import Tool

# Bump when the JSON shape changes in a way an older wizard cannot read.
CATALOG_SCHEMA_VERSION = 1


@cache
def get_tool_catalog() -> tuple[Tool, ...]:
    curated_kinds = {tool.kind for tool in CURATED_TOOLS}
    if len(curated_kinds) != len(CURATED_TOOLS):
        raise ValueError("Two curated tools share a kind")
    tools = CURATED_TOOLS + derived_tools(curated_kinds)
    for tool in tools:
        for pattern in tool.signals.env_key_patterns:
            # Unanchored, a pattern matches any key that merely contains the vendor name.
            if not pattern.startswith("^"):
                raise ValueError(f"{tool.kind}: env key pattern {pattern!r} is not anchored")
            re.compile(pattern)
    return tools


@cache
def _tools_by_kind() -> dict[str, Tool]:
    return {tool.kind: tool for tool in get_tool_catalog()}


def get_tool(kind: str) -> Tool | None:
    return _tools_by_kind().get(kind)
