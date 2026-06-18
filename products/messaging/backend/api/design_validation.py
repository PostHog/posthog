from typing import NoReturn

from rest_framework import serializers

# Structural validation for an Unlayer email design after operations are applied. Hard errors (raised)
# are things Unlayer's renderer can't recover from — a missing body, a non-list rows, or duplicate ids
# that would make later id-addressed edits ambiguous. Everything else is advisory: returned as warnings
# for the caller to log, not reject, so the design model stays forward-compatible as Unlayer adds block
# types.

# Content types the Unlayer editor emits today; an unknown type is a warning, not a hard error.
KNOWN_CONTENT_TYPES = frozenset(
    {
        "text",
        "heading",
        "button",
        "image",
        "divider",
        "social",
        "html",
        "video",
        "menu",
        "timer",
        "table",
        "carousel",
    }
)


def _fail(message: str) -> NoReturn:
    raise serializers.ValidationError({"design": message})


def validate_design(design: dict) -> list[str]:
    """Validate the structure of an Unlayer design. Raises ValidationError on hard errors; returns a
    list of advisory warnings the caller should log rather than reject."""
    if not isinstance(design, dict):
        _fail("design must be an object")

    body = design.get("body")
    if not isinstance(body, dict):
        _fail("design.body must be an object")

    rows = body.get("rows")
    if not isinstance(rows, list):
        _fail("design.body.rows must be a list")

    warnings: list[str] = []
    seen_ids: set[str] = set()

    def check_id(node_id: object, label: str) -> None:
        if not isinstance(node_id, str) or not node_id:
            warnings.append(f"{label} is missing an id")
            return
        if node_id in seen_ids:
            _fail(f"duplicate id '{node_id}' — ids must be unique so edits can address one node")
        seen_ids.add(node_id)

    if not rows:
        warnings.append("design has no rows — the rendered email will be empty")

    for row in rows:
        check_id(row.get("id"), "row")
        for column in row.get("columns") or []:
            check_id(column.get("id"), "column")
            for content in column.get("contents") or []:
                check_id(content.get("id"), "content")
                content_type = content.get("type")
                if content_type not in KNOWN_CONTENT_TYPES:
                    warnings.append(f"content '{content.get('id')}' has unknown type '{content_type}'")

    return warnings
