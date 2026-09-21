from typing import Any

from posthog.models.integration import sign_slack_request

__all__ = ["render_blocks", "sign_slack_request"]


def render_blocks(blocks: list[dict[str, Any]]) -> str:
    """Block Kit as a reader sees it, so a copy snapshot diffs as prose rather than as JSON."""
    lines = []
    for block in blocks:
        if block["type"] == "section":
            lines.append(block["text"]["text"])
            for field in block.get("fields", []):
                lines.append(field.get("text", ""))
            accessory = block.get("accessory") or {}
            if accessory.get("type") == "button":
                lines.append(f"[{accessory['text']['text']}]({accessory.get('url', accessory.get('action_id'))})")
        elif block["type"] == "context":
            lines.append(" ".join(e.get("text", "") for e in block["elements"] if isinstance(e.get("text"), str)))
        elif block["type"] == "header":
            lines.append(f"# {block['text']['text']}")
        elif block["type"] == "divider":
            lines.append("---")
        elif block["type"] == "actions":
            rendered = []
            for element in block["elements"]:
                if element.get("type") == "button":
                    target = element.get("url") or element.get("action_id")
                    rendered.append(f"[{element['text']['text']}]({target})")
                elif element.get("type") == "checkboxes":
                    for option in element.get("options", []):
                        rendered.append(f"[ ] {option['text']['text']}")
                else:
                    rendered.append(f"<{element.get('type')}>")
            lines.append(" ".join(rendered))
    return "\n\n".join(lines)
