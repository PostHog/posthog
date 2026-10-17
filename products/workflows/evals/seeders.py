"""Two email templates in the case's team: one managed by code, one made in PostHog.

All names, keys, repositories and content are invented for these evals.
"""

from typing import Any, Final

from products.messaging.backend.facade import templates as templates_facade
from products.messaging.backend.facade.contracts import TemplateSource
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

CODE_MANAGED_TEMPLATE_NAME: Final = "Welcome to Hedgebox"
CODE_MANAGED_TEMPLATE_KEY: Final = "hedgebox-welcome"
CODE_MANAGED_TEMPLATE_SOURCE: Final = TemplateSource(
    repository="github.com/example/hedgebox-app",
    path="emails/welcome.html",
    ref="4b1d0c9e8f7a6b5c4d3e2f1a0b9c8d7e6f5a4b3c",
)
GUI_TEMPLATE_NAME: Final = "Weekly storage digest"

_CODE_MANAGED_HTML: Final = """<!doctype html>
<html>
  <head>
    <title>Welcome to Hedgebox, {{ variables.first_name }}</title>
    <meta name="preheader" content="Your files are ready when you are." />
  </head>
  <body style="font-family: sans-serif; background: #f5f5f4; padding: 24px;">
    <h1>Welcome to Hedgebox, {{ variables.first_name }}</h1>
    <p>Upload your first file and share it with one link.</p>
    <a href="{{ variables.files_url }}" style="background: #1d4ed8; color: #ffffff; padding: 12px 20px; border-radius: 6px; text-decoration: none;">Open your files</a>
  </body>
</html>
"""

_GUI_DESIGN: Final[dict[str, Any]] = {
    "counters": {"u_row": 1, "u_column": 1, "u_content_text": 1, "u_content_button": 1},
    "schemaVersion": 16,
    "body": {
        "id": "body",
        "rows": [
            {
                "id": "row1",
                "cells": [1],
                "columns": [
                    {
                        "id": "col1",
                        "contents": [
                            {
                                "id": "txt1",
                                "type": "text",
                                "values": {
                                    "text": "<p>Here is what changed in your Hedgebox storage this week.</p>",
                                    "_meta": {"htmlID": "u_content_text_1", "htmlClassNames": "u_content_text"},
                                },
                            },
                            {
                                "id": "btn1",
                                "type": "button",
                                "values": {
                                    "text": "<span>See your storage</span>",
                                    "href": {
                                        "name": "web",
                                        "values": {"href": "https://hedgebox.example.com/files", "target": "_blank"},
                                    },
                                    "buttonColors": {
                                        "color": "#FFFFFF",
                                        "backgroundColor": "#1D4ED8",
                                        "hoverColor": "#FFFFFF",
                                        "hoverBackgroundColor": "#1E40AF",
                                    },
                                    "_meta": {"htmlID": "u_content_button_1", "htmlClassNames": "u_content_button"},
                                },
                            },
                        ],
                        "values": {"_meta": {"htmlID": "u_column_1", "htmlClassNames": "u_column"}},
                    }
                ],
                "values": {"_meta": {"htmlID": "u_row_1", "htmlClassNames": "u_row"}},
            }
        ],
        "values": {},
    },
}


def seed_email_templates(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """One template as an upload from a file leaves it, and one made in PostHog."""
    source = CODE_MANAGED_TEMPLATE_SOURCE
    code_managed = templates_facade.create_template(
        context.team_id,
        context.user_id,
        {
            "name": CODE_MANAGED_TEMPLATE_NAME,
            "description": "",
            "type": "email",
            "key": CODE_MANAGED_TEMPLATE_KEY,
            "managed_by": "code",
            "source_repository": source.repository,
            "source_path": source.path,
            "source_ref": source.ref,
            "content": {
                "templating": "liquid",
                "email": {
                    "subject": "Welcome to Hedgebox, {{ variables.first_name }}",
                    "preheader": "Your files are ready when you are.",
                    "text": "",
                    "html": _CODE_MANAGED_HTML,
                },
            },
        },
    )
    gui = templates_facade.create_template(
        context.team_id,
        context.user_id,
        {
            "name": GUI_TEMPLATE_NAME,
            "description": "Sent every Monday",
            "type": "email",
            "content": {
                "templating": "liquid",
                "email": {
                    "subject": "Your Hedgebox week",
                    "text": "Here is what changed in your Hedgebox storage this week. See your storage: "
                    "https://hedgebox.example.com/files",
                    "html": "",
                    "design": _GUI_DESIGN,
                },
            },
        },
    )
    return {
        "code_managed_template_id": str(code_managed.id),
        "gui_template_id": str(gui.id),
    }
