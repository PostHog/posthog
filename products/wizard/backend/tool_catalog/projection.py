"""Project the wizard tool catalog into the JSON the wizard repo builds its detector registry from.

Registered in `tools/hogli-commands/hogli_commands/projections.py`; run
`hogli build:projections`.
"""

import json
from typing import Any

from products.wizard.backend.tool_catalog.catalog import CATALOG_SCHEMA_VERSION, get_tool_catalog
from products.wizard.backend.tool_catalog.types import Tool

OUTPUT = "products/wizard/tool-catalog.generated.json"


def _tool_json(tool: Tool) -> dict[str, Any]:
    return {
        "kind": tool.kind,
        "label": tool.label,
        "origin": tool.origin.value,
        "warehouse_source_type": tool.warehouse_source_type.value if tool.warehouse_source_type else None,
        "wizard_setup_mode": tool.wizard_setup_mode.value if tool.wizard_setup_mode else None,
        "llm": tool.llm,
        "competes_with": [product.value for product in tool.competes_with],
        "superseded_by": list(tool.superseded_by),
        "signals": {
            "packages": {ecosystem.value: list(names) for ecosystem, names in tool.signals.packages.items()},
            "env_key_patterns": list(tool.signals.env_key_patterns),
            "script_hosts": list(tool.signals.script_hosts),
        },
    }


def render() -> dict[str, str]:
    catalog = {"schema_version": CATALOG_SCHEMA_VERSION, "tools": [_tool_json(tool) for tool in get_tool_catalog()]}
    return {OUTPUT: json.dumps(catalog, indent=2) + "\n"}
