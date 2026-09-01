"""Starting content for a new doc.

A template is plain ProseMirror content, not a live type: once the doc exists nothing
remembers which template made it.
"""

from typing import Any

from products.docs.backend.facade.enums import DocTemplate

_BLANK: dict[str, Any] = {"type": "doc", "content": [{"type": "paragraph"}]}

_NOTES: dict[str, Any] = {
    "type": "doc",
    "content": [
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "What we heard"}]},
        {"type": "bulletList", "content": [{"type": "listItem", "content": [{"type": "paragraph"}]}]},
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "What happens next"}]},
        {
            "type": "taskList",
            "content": [{"type": "taskItem", "attrs": {"checked": False}, "content": [{"type": "paragraph"}]}],
        },
    ],
}

_TEMPLATE_CONTENT: dict[str, dict[str, Any]] = {
    DocTemplate.BLANK: _BLANK,
    DocTemplate.NOTES: _NOTES,
}

DEFAULT_TITLES: dict[str, str] = {
    DocTemplate.BLANK: "Untitled",
    DocTemplate.NOTES: "Notes",
}


def template_content(template: str) -> dict[str, Any]:
    return _TEMPLATE_CONTENT.get(template, _BLANK)


def template_title(template: str) -> str:
    return DEFAULT_TITLES.get(template, DEFAULT_TITLES[DocTemplate.BLANK])
