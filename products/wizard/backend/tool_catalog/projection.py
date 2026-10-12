"""Project the wizard tool catalog into the JSON the wizard repo builds its detector registry from.

The catalog reads every warehouse source class, and some of them import Django models. The renderer
builds it in a child process with test settings, so the projections check needs no database and the
other renderers keep their own process state.

Registered in `tools/hogli-commands/hogli_commands/projections.py`; run
`hogli build:projections`.
"""

import os
import sys
import json
import tempfile
import subprocess
from pathlib import Path
from typing import Any

OUTPUT = "products/wizard/tool-catalog.generated.json"
REPO_ROOT = Path(__file__).resolve().parents[4]

_CHILD = """
import sys
import django
django.setup()
from products.wizard.backend.tool_catalog.projection import catalog_json
with open(sys.argv[1], "w") as output:
    output.write(catalog_json())
"""


def catalog_json() -> str:
    # Imported here because the catalog needs Django set up, which only the child process does.
    from products.wizard.backend.tool_catalog.catalog import CATALOG_SCHEMA_VERSION, get_tool_catalog  # noqa: PLC0415

    tools: list[dict[str, Any]] = [
        {
            "kind": tool.kind,
            "label": tool.label,
            "warehouse_source_type": tool.warehouse_source_type.value if tool.warehouse_source_type else None,
            "wizard_setup_mode": None
            if tool.setup_requires_ui is None
            else ("deep-link" if tool.setup_requires_ui else "in-cli"),
            "competes_with": [product.value for product in tool.detection.competes_with],
            "superseded_by": list(tool.detection.superseded_by),
            "signals": {
                "env_key_patterns": list(tool.detection.env_key_patterns),
                "script_hosts": list(tool.detection.script_hosts),
                "packages": {ecosystem.value: list(names) for ecosystem, names in tool.detection.packages.items()},
            },
        }
        for tool in get_tool_catalog()
    ]
    return json.dumps({"schema_version": CATALOG_SCHEMA_VERSION, "tools": tools}, indent=2) + "\n"


def render() -> dict[str, str]:
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "posthog.settings", "TEST": "1"}
    # DEBUG settings run startup hooks that query the database.
    env.pop("DEBUG", None)
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "catalog.json"
        subprocess.run([sys.executable, "-c", _CHILD, str(output)], cwd=REPO_ROOT, env=env, check=True)
        return {OUTPUT: output.read_text()}
