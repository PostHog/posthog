"""The tools the wizard can detect in a codebase, and what each one means to PostHog.

Each warehouse source declares its own `codebase_detection`. The image build renders the catalog to
`products/wizard/tool-catalog.json` with `manage.py render_wizard_tool_catalog`. The public
`/api/wizard/tool_catalog/` endpoint serves that file, and the wizard downloads it at runtime from US,
then EU. The backend reads the same file to classify reported scans.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any

from products.warehouse_sources.backend.facade.codebase_detection import Detection, fields_require_ui
from products.warehouse_sources.backend.facade.source_management import SourceRegistry, load_all_sources_or_raise
from products.wizard.backend.tool_catalog.posthog_alternatives import POSTHOG_ALTERNATIVES_WITHOUT_SOURCE
from products.wizard.backend.tool_catalog.types import Tool, ToolClassification

# Bump when the JSON shape changes in a way an older wizard cannot read.
CATALOG_SCHEMA_VERSION = 1
CATALOG_JSON = Path(__file__).resolve().parents[2] / "tool-catalog.json"


@cache
def get_tool_catalog() -> tuple[Tool, ...]:
    tools = [
        Tool(
            kind=source_type.value,
            label=source.get_source_config.label or source_type.value,
            warehouse_source_type=source_type,
            detection=source.codebase_detection,
            setup_requires_ui=source.setup_requires_ui or fields_require_ui(source.get_source_config.fields),
        )
        for source_type, source in SourceRegistry.get_all_sources().items()
        if isinstance(source.codebase_detection, Detection)
    ]
    tools += [
        Tool(kind=kind, label=kind, warehouse_source_type=None, detection=detection, setup_requires_ui=None)
        for kind, detection in POSTHOG_ALTERNATIVES_WITHOUT_SOURCE.items()
    ]
    return tuple(sorted(tools, key=lambda tool: tool.kind))


def build_catalog_document() -> dict[str, Any]:
    tools: list[dict[str, Any]] = [
        {
            "kind": tool.kind,
            "label": tool.label,
            "warehouse_source_type": tool.warehouse_source_type.value if tool.warehouse_source_type else None,
            "wizard_setup_mode": None
            if tool.setup_requires_ui is None
            else ("deep-link" if tool.setup_requires_ui else "in-cli"),
            "alternative_to": [product.value for product in tool.detection.alternative_to],
            "superseded_by": list(tool.detection.superseded_by),
            "signals": {
                "env_key_patterns": list(tool.detection.env_key_patterns),
                "script_hosts": list(tool.detection.script_hosts),
                "packages": {ecosystem.value: list(names) for ecosystem, names in tool.detection.packages.items()},
            },
        }
        for tool in get_tool_catalog()
    ]
    return {"schema_version": CATALOG_SCHEMA_VERSION, "tools": tools}


def write_catalog(path: Path) -> None:
    # The registry's own loader skips a source module that fails to import. A catalog rendered without
    # that source would silently drop its detection, so a broken source fails the image build instead.
    load_all_sources_or_raise()
    path.write_text(json.dumps(build_catalog_document(), separators=(",", ":")))


# A web worker reads the file that the image build rendered, so serving the catalog or classifying a
# reported scan never imports every warehouse source module. Local dev and tests have no such file, and
# render the catalog from the source declarations on first use.
@cache
def _catalog_document() -> dict[str, Any]:
    if CATALOG_JSON.exists():
        return json.loads(CATALOG_JSON.read_text())
    return build_catalog_document()


@cache
def tool_catalog_json() -> bytes:
    return json.dumps(_catalog_document(), separators=(",", ":")).encode()


@cache
def _classifications() -> dict[str, ToolClassification]:
    tools = _catalog_document()["tools"]
    return {
        tool["kind"]: ToolClassification(
            warehouse_source_type=tool["warehouse_source_type"], alternative_to=tuple(tool["alternative_to"])
        )
        for tool in tools
    }


def classify_tool(kind: str) -> ToolClassification | None:
    return _classifications().get(kind)
