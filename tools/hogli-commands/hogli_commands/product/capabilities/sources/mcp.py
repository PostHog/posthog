"""MCP surface: which products expose tools to agents over MCP.

Closed world. A product's MCP tools live at ``products/<X>/mcp/tools.yaml`` and nowhere
else, so absence is provable and this source may emit `unavailable`.

Attribution is by *path*, not by the file's ``feature:`` field. `feature` is a display
key that is not guaranteed to equal the directory name, so trusting it would let a
product's tools be attributed to a different product.
"""

from __future__ import annotations

import yaml

from ..context import DerivationContext
from ..models import SurfaceFact

_TOOLS_RELPATH = ("mcp", "tools.yaml")


def _flag_gated(entry: dict) -> bool:
    return bool(entry.get("feature_flag"))


def derive(ctx: DerivationContext) -> dict[str, SurfaceFact]:
    results: dict[str, SurfaceFact] = {}

    for product in sorted(ctx.product_dirs):
        path = ctx.products_dir.joinpath(product, *_TOOLS_RELPATH)
        if not path.exists():
            results[product] = SurfaceFact(
                availability="unavailable",
                facts={"enabled_tool_count": 0},
                **{"from": [f"products/{product}/"]},
            )
            continue

        rel = ctx.rel(path)
        config = yaml.safe_load(path.read_text()) or {}
        tools = config.get("tools") or {}
        wrappers = config.get("wrappers") or {}
        ui_apps = config.get("ui_apps") or {}

        enabled = {name: e for name, e in tools.items() if isinstance(e, dict) and e.get("enabled")}
        enabled_wrappers = {name: e for name, e in wrappers.items() if isinstance(e, dict) and e.get("enabled")}
        all_enabled = {**enabled, **enabled_wrappers}

        if not all_enabled:
            # Scaffolded but nothing shipped. The file exists only because scaffold-yaml
            # discovered API operations, which is not the same as an available surface.
            results[product] = SurfaceFact(
                availability="unavailable",
                facts={"enabled_tool_count": 0, "total_operation_count": len(tools)},
                **{"from": [rel]},
            )
            continue

        scopes = sorted({s for e in all_enabled.values() for s in (e.get("scopes") or [])})
        annotations = [e.get("annotations") or {} for e in all_enabled.values()]

        # `preview` means the surface exists but nobody can reach it without a flag.
        # If even one tool is ungated the surface is genuinely available.
        availability = "preview" if all(_flag_gated(e) for e in all_enabled.values()) else "available"

        results[product] = SurfaceFact(
            availability=availability,
            facts={
                "enabled_tool_count": len(all_enabled),
                "total_operation_count": len(tools),
                "tool_names": sorted(all_enabled),
                "wrapper_names": sorted(enabled_wrappers),
                "ui_app_names": sorted(ui_apps),
                "scopes": scopes,
                "read_only_tool_count": sum(1 for a in annotations if a.get("readOnly")),
                "destructive_tool_count": sum(1 for a in annotations if a.get("destructive")),
                "url_prefix": config.get("url_prefix"),
            },
            **{"from": [rel]},
        )

    return results
