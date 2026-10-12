"""The tools the wizard can detect in a codebase, and what each one means to PostHog.

Each warehouse source declares its own `codebase_detection`. `projection.py` renders the catalog to
`products/wizard/tool-catalog.generated.json`, and a change to that file on `master` makes the wizard
repo regenerate its detector registry. The backend reads the same catalog to classify reported scans.
"""

from functools import cache

from products.warehouse_sources.backend.facade.codebase_detection import Detection, fields_require_ui
from products.warehouse_sources.backend.facade.source_management import SourceRegistry
from products.wizard.backend.tool_catalog.competitors import COMPETITORS_WITHOUT_SOURCE
from products.wizard.backend.tool_catalog.types import Tool

# Bump when the JSON shape changes in a way an older wizard cannot read.
CATALOG_SCHEMA_VERSION = 1


@cache
def get_tool_catalog() -> tuple[Tool, ...]:
    tools = [
        Tool(
            kind=source_type.value,
            label=source.get_source_config.label or source_type.value,
            warehouse_source_type=source_type,
            detection=source.codebase_detection,
            setup_requires_ui=source.codebase_detection.setup_requires_ui
            or fields_require_ui(source.get_source_config.fields),
        )
        for source_type, source in SourceRegistry.get_all_sources().items()
        if isinstance(source.codebase_detection, Detection)
    ]
    tools += [
        Tool(kind=kind, label=kind, warehouse_source_type=None, detection=detection, setup_requires_ui=None)
        for kind, detection in COMPETITORS_WITHOUT_SOURCE.items()
    ]
    return tuple(sorted(tools, key=lambda tool: tool.kind))


@cache
def _tools_by_kind() -> dict[str, Tool]:
    return {tool.kind: tool for tool in get_tool_catalog()}


def get_tool(kind: str) -> Tool | None:
    return _tools_by_kind().get(kind)
