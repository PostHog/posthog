"""Project the `@posthog` command grammar into a JSON signature and a Markdown command table.

A renderer in the projection registry. ``backend/logic/schema.py`` stays the one authority for
every verb, option and help string, and these files let docs and other tools read it without
Python.

Registered in `tools/hogli-commands/hogli_commands/projections.py`; run
`hogli build:projections`.
"""

import json

from products.github_commands.backend.logic.schema import help_table, signature

JSON_OUTPUT = "products/github_commands/commands.generated.json"
MARKDOWN_OUTPUT = "products/github_commands/COMMANDS.generated.md"


def render() -> dict[str, str]:
    markdown_note = "<!-- Generated from backend/logic/schema.py. Do not edit. Run `hogli build:projections`. -->"
    return {
        JSON_OUTPUT: json.dumps(signature(), indent=2) + "\n",
        MARKDOWN_OUTPUT: f"{markdown_note}\n\n{help_table()}\n",
    }
