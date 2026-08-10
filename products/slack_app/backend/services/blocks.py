"""Block Kit primitives shared across the Slack app's surfaces.

Small builders only — anything that needs a client, a flag, or the database belongs
with the surface that owns it.
"""

from __future__ import annotations

from typing import Any


def context_block(text: str) -> dict[str, Any]:
    """A line of muted supporting text.

    Block Kit has no footer block; `context` is what renders small and grey under the
    content it describes.
    """
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}
