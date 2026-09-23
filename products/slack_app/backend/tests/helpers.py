from typing import Any

from posthog.models.integration import sign_slack_request

__all__ = ["action_ids", "all_block_text", "render_blocks", "sign_slack_request", "url_buttons"]


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


def action_ids(blocks: list[dict[str, Any]]) -> list[str]:
    ids = [el["action_id"] for b in blocks if b["type"] == "actions" for el in b["elements"] if "action_id" in el]
    ids += [b["accessory"]["action_id"] for b in blocks if (b.get("accessory") or {}).get("action_id")]
    return ids


def url_buttons(blocks: list[dict[str, Any]]) -> list[str]:
    urls = [el["url"] for b in blocks if b["type"] == "actions" for el in b["elements"] if "url" in el]
    urls += [b["accessory"]["url"] for b in blocks if (b.get("accessory") or {}).get("url")]
    return urls


def all_block_text(blocks: list[dict[str, Any]]) -> str:
    """Every string a reader could see, flattened for a substring assertion."""
    parts: list[str] = []
    for b in blocks:
        if (b.get("text") or {}).get("text"):
            parts.append(b["text"]["text"])
        for f in b.get("fields", []):
            parts.append(f.get("text", ""))
        for el in b.get("elements", []):
            txt = el.get("text")
            parts.append(txt if isinstance(txt, str) else (txt or {}).get("text", ""))
    return " ".join(parts)
